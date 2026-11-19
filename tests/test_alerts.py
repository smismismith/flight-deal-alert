"""AC-11, AC-12, AC-14(상태): 알림 상태 관리."""
from datetime import date

from collector.alerts import Outcome, trim_alerts, update_alerts
from collector.config import Combo
from collector.flights import FlightOption, QueryResult
from collector.judge import build_fare

T1, T2, T3 = "2026-11-19T09:00:00+09:00", "2026-11-19T15:00:00+09:00", "2026-11-19T22:00:00+09:00"


def fare(cfg, code, price, depart=date(2026, 12, 21), nights=4):
    d = next(x for x in cfg.destinations if x.code == code)
    f = FlightOption(price, "VJ", ["비엣젯항공"], 0, 295, "18:40", "21:35", depart.isoformat(), depart.isoformat())
    res = QueryResult("ok", "https://www.google.com/travel/flights/search?tfs=x", f, None)
    return build_fare(d, Combo(depart, nights), res, T1, True, price, [], cfg)


def step(cfg, alerts, code, deal, run_id, now, refreshed=True):
    dests = {d.code: d for d in cfg.destinations}
    return update_alerts(alerts, {code: Outcome(refreshed, deal)}, dests, run_id, now, cfg.realert_drop_pct)


def mark_sent(alert, at=T1):
    alert["notification"].update(sent=True, sent_at=at, attempts=1, error=None)


def test_first_deal_creates_new_alert(cfg):
    alerts = []
    send = step(cfg, alerts, "DAD", fare(cfg, "DAD", 359000), "20261119T080000", T1)
    assert len(alerts) == 1 and send == [alerts[0]]
    a = alerts[0]
    assert (a["id"], a["status"], a["kind"]) == ("DAD-20261119T080000", "active", "new")
    assert a["alerted_price_krw"] == 359000 and a["previous_alerted_price_krw"] is None
    assert a["notification"] == {"channel": "telegram", "sent": False, "sent_at": None, "attempts": 0, "error": None}
    assert a["hotels"]["source"] == "links" and a["hotels"]["items"] == []


def test_realert_exactly_five_percent(cfg):
    alerts = []
    step(cfg, alerts, "DAD", fare(cfg, "DAD", 359000), "20261119T080000", T1)
    mark_sent(alerts[0])
    send = step(cfg, alerts, "DAD", fare(cfg, "DAD", 341050), "20261119T140000", T2)
    assert len(send) == 1 and len(alerts) == 2
    new, old = alerts
    assert (new["kind"], new["status"], new["previous_alerted_price_krw"], new["alerted_price_krw"]) == ("realert", "active", 359000, 341050)
    assert (old["status"], old["ended_at"], old["current_fare"]) == ("replaced", T2, None)
    assert sum(a["status"] == "active" for a in alerts) == 1


def test_less_than_five_percent_only_updates_current_fare(cfg):
    alerts = []
    step(cfg, alerts, "DAD", fare(cfg, "DAD", 359000), "20261119T080000", T1)
    mark_sent(alerts[0])
    send = step(cfg, alerts, "DAD", fare(cfg, "DAD", 341100), "20261119T140000", T2)
    assert send == [] and len(alerts) == 1
    a = alerts[0]
    assert a["status"] == "active" and a["alerted_price_krw"] == 359000 and a["fare"]["price_krw"] == 359000
    assert a["current_fare"]["price_krw"] == 341100 and a["current_checked_at"] == T2
    # 가격이 올라도 특가가 유지되면 발송하지 않는다
    assert step(cfg, alerts, "DAD", fare(cfg, "DAD", 365000), "20261119T210000", T3) == []
    assert alerts[0]["current_fare"]["price_krw"] == 365000


def test_deal_gone_ends_alert_and_stale_keeps_state(cfg):
    alerts = []
    step(cfg, alerts, "DAD", fare(cfg, "DAD", 359000), "20261119T080000", T1)
    mark_sent(alerts[0])
    assert step(cfg, alerts, "DAD", None, "20261119T140000", T2, refreshed=False) == []
    assert alerts[0]["status"] == "active" and alerts[0]["current_fare"]["price_krw"] == 359000
    assert step(cfg, alerts, "DAD", None, "20261119T210000", T3) == []
    a = alerts[0]
    assert (a["status"], a["ended_at"], a["current_fare"]) == ("ended", T3, None)


def test_ended_alert_returns_to_active_without_sending(cfg):
    alerts = []
    step(cfg, alerts, "DAD", fare(cfg, "DAD", 359000), "20261119T080000", T1)
    mark_sent(alerts[0])
    step(cfg, alerts, "DAD", None, "20261119T140000", T2)
    send = step(cfg, alerts, "DAD", fare(cfg, "DAD", 350000), "20261119T210000", T3)
    assert send == [] and len(alerts) == 1
    assert (alerts[0]["status"], alerts[0]["ended_at"]) == ("active", None)
    assert alerts[0]["current_fare"]["price_krw"] == 350000


def test_realert_after_ended_uses_last_sent_price(cfg):
    alerts = []
    step(cfg, alerts, "DAD", fare(cfg, "DAD", 359000), "20261119T080000", T1)
    mark_sent(alerts[0])
    step(cfg, alerts, "DAD", None, "20261119T140000", T2)
    send = step(cfg, alerts, "DAD", fare(cfg, "DAD", 330000), "20261119T210000", T3)
    assert len(send) == 1 and send[0]["kind"] == "realert" and send[0]["previous_alerted_price_krw"] == 359000
    assert [a["status"] for a in alerts] == ["active", "ended"]


def test_unsent_alert_is_retried_with_same_record(cfg):
    alerts = []
    step(cfg, alerts, "DAD", fare(cfg, "DAD", 359000), "20261119T080000", T1)
    alerts[0]["notification"]["error"] = "토큰 없음"
    send = step(cfg, alerts, "DAD", fare(cfg, "DAD", 362000, nights=5), "20261119T140000", T2)
    assert len(alerts) == 1 and send == [alerts[0]]
    a = alerts[0]
    assert a["id"] == "DAD-20261119T080000" and a["kind"] == "new"
    assert a["alerted_price_krw"] == 362000 and a["fare"]["nights"] == 5
    assert a["hotels"]["check_out"] == "2026-12-26"  # 날짜가 바뀌면 호텔 검색 조건도 갱신한다


def test_one_active_alert_per_destination_over_many_runs(cfg):
    alerts = []
    prices = [359000, 341050, 341000, None, 300000, 299000, None, 280000]
    for i, p in enumerate(prices):
        now = f"2026-11-{19 + i:02d}T09:00:00+09:00"
        send = step(cfg, alerts, "DAD", fare(cfg, "DAD", p) if p else None, f"202611{19 + i:02d}T080000", now)
        for a in send:
            mark_sent(a, now)
        assert sum(a["status"] == "active" for a in alerts) <= 1
        assert [a["created_at"] for a in alerts] == sorted((a["created_at"] for a in alerts), reverse=True)
        for a in alerts:
            assert (a["status"] == "active") == (a["current_fare"] is not None)
            assert (a["status"] == "active") == (a["ended_at"] is None)
    assert [a["alerted_price_krw"] for a in alerts] == [280000, 300000, 341050, 359000]


def test_other_destinations_are_independent(cfg):
    alerts = []
    dests = {d.code: d for d in cfg.destinations}
    out = {"DAD": Outcome(True, fare(cfg, "DAD", 300000)), "FUK": Outcome(True, fare(cfg, "FUK", 200000)), "KIX": Outcome(True, None)}
    send = update_alerts(alerts, out, dests, "20261119T080000", T1, 5)
    assert {a["destination"] for a in send} == {"DAD", "FUK"}
    update_alerts(alerts, {"DAD": Outcome(True, None)}, dests, "20261119T140000", T2, 5)
    assert {a["destination"]: a["status"] for a in alerts} == {"DAD": "ended", "FUK": "active"}


def test_trim_keeps_newest_and_all_active(cfg):
    alerts = []
    for i in range(205):
        a = {"created_at": f"{i:04d}", "status": "ended"}
        alerts.insert(0, a)
    alerts[-1]["status"] = "active"  # 가장 오래된 알림이 active
    out = trim_alerts(alerts, 200)
    assert len(out) == 200 and out[-1]["status"] == "active" and out[0]["created_at"] == "0204"
