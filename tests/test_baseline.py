"""AC-16: 비성수기 기준가 갱신."""
from datetime import date, datetime, timedelta

from collector import flights as fl
from collector.baseline import refresh_baseline, refresh_targets
from collector.config import KST, iso_kst
from collector.main import RunState
from conftest import BOT_HTML, FakeTime, make_html, make_payload, simple_html

NOW = datetime(2026, 11, 19, 8, 0, 0, tzinfo=KST)


def entry(d, nights, price=100000, age_days=0.0):
    return {
        "origin": d.origin, "destination": d.code, "nights": nights, "depart_date": "2027-03-09",
        "return_date": (date(2027, 3, 9) + timedelta(days=nights)).isoformat(), "price_krw": price,
        "airlines": ["A"], "stops": 0, "search_url": "https://x", "collected_at": iso_kst(NOW - timedelta(days=age_days)),
    }


def state_with(cfg, responder):
    t = FakeTime(NOW)
    seen = []

    def fetch(query, timeout):
        a, b = query.flight_data[0], query.flight_data[1]
        seen.append((a.to_airport.airport, a.date, b.date))
        return responder(a.to_airport.airport, a.date, b.date)

    client = fl.FlightClient(cfg, fetch, t.sleep, t.clock, lambda: 0.0)
    return RunState(cfg=cfg, client=client, now=t.now), seen


def test_targets_missing_or_older_than_seven_days(cfg):
    kix, cju = [d for d in cfg.destinations if d.code in ("KIX", "CJU")][::-1]
    entries = [
        entry(kix, 3, age_days=7.5),   # 7일 초과 -> 대상
        entry(kix, 4, age_days=6.9),   # 7일 이내 -> 제외
        entry(kix, 5, age_days=20),    # 가장 오래됨
        entry(cju, 3, age_days=7.0),   # 정확히 7일 -> 제외
    ]
    targets = [(d.code, n) for d, n in refresh_targets(cfg, [kix, cju], entries, NOW)]
    # 없는 항목이 먼저, 그다음 오래된 순서
    assert targets == [("KIX", 6), ("KIX", 7), ("CJU", 4), ("CJU", 5), ("CJU", 6), ("CJU", 7), ("KIX", 5), ("KIX", 3)]


def test_at_most_100_queries_per_run_and_300_total(cfg):
    assert len(refresh_targets(cfg, cfg.destinations, [], NOW)) == 100
    import dataclasses
    assert len(refresh_targets(dataclasses.replace(cfg, baseline_max_queries=1000), cfg.destinations, [], NOW)) == 300


def test_refresh_queries_march_dates_and_stores_price(cfg):
    kix = next(d for d in cfg.destinations if d.code == "KIX")
    state, seen = state_with(cfg, lambda dest, dep, ret: simple_html(200000 + int(ret[-2:]) * 1000))
    entries = []
    assert refresh_baseline(state, [kix], entries) is True
    assert seen == [("KIX", "2027-03-09", f"2027-03-{9 + n:02d}") for n in range(3, 8)]
    assert sorted((e["nights"], e["price_krw"]) for e in entries) == [(n, 200000 + (9 + n) * 1000) for n in range(3, 8)]
    e = entries[0]
    assert (e["origin"], e["destination"], e["depart_date"], e["stops"]) == ("ICN", "KIX", "2027-03-09", 0)
    assert e["search_url"].startswith("https://") and e["collected_at"].endswith("+09:00")
    assert state.baseline_queries == 5 and state.attempted == 0
    # 방금 수집했으므로 다시 조회하지 않는다
    assert refresh_baseline(state, [kix], entries) is False and len(seen) == 5


def test_failure_or_no_result_keeps_existing_value(cfg):
    kix = next(d for d in cfg.destinations if d.code == "KIX")
    old = [entry(kix, n, price=111000, age_days=30) for n in range(3, 8)]

    def responder(dest, dep, ret):
        if ret == "2027-03-12":
            return BOT_HTML
        if ret == "2027-03-13":
            return make_html(make_payload([]))
        return simple_html(99000)

    state, _ = state_with(cfg, responder)
    entries = [dict(e) for e in old]
    assert refresh_baseline(state, [kix], entries) is True
    by_n = {e["nights"]: e for e in entries}
    assert by_n[3] == old[0]  # 조회 실패: 변경 없음(다음 실행에서 다시 조회)
    # 결과 없음: 가격은 유지하고 checked_at 을 기록해 refresh_days 동안 다시 조회하지 않는다
    assert by_n[4].pop("checked_at").startswith("2026-11-19T08:0") and by_n[4] == old[1]
    by_n[4]["checked_at"] = iso_kst(NOW)
    assert [(d.code, n) for d, n in refresh_targets(cfg, [kix], entries, NOW)] == [("KIX", 3)]
    assert [by_n[n]["price_krw"] for n in (5, 6, 7)] == [99000] * 3
    assert len(entries) == 5
    assert state.errors[0]["kind"] == "bot_check" and state.errors[0]["message"].startswith("기준가 조회: ")
    assert state.failed == 0  # 기준가 조회 실패는 실행 결과 집계에 포함하지 않는다


def test_skipped_when_run_aborted_or_budget_exhausted(cfg):
    kix = next(d for d in cfg.destinations if d.code == "KIX")
    state, seen = state_with(cfg, lambda *a: simple_html(1))
    state.aborted_reason = "중단"
    assert refresh_baseline(state, [kix], []) is False and seen == []
    state, seen = state_with(cfg, lambda *a: simple_html(1))
    state.max_queries = 2
    entries = []
    refresh_baseline(state, [kix], entries)
    assert len(seen) == 2 and len(entries) == 2


def test_no_result_without_existing_value_is_recorded_and_not_requeried(cfg):
    """3월에 운항하지 않는 노선: price_krw=null 로 기록하고 7일 동안 다시 조회하지 않는다."""
    kix = next(d for d in cfg.destinations if d.code == "KIX")
    state, seen = state_with(cfg, lambda *a: make_html(make_payload([])))
    entries = []
    assert refresh_baseline(state, [kix], entries) is True
    assert len(seen) == 5 and len(entries) == 5
    assert all(e["price_krw"] is None and e["airlines"] == [] and e["stops"] is None for e in entries)
    assert refresh_baseline(state, [kix], entries) is False and len(seen) == 5
    assert refresh_targets(cfg, [kix], entries, NOW + timedelta(days=6)) == []
    assert len(refresh_targets(cfg, [kix], entries, NOW + timedelta(days=8))) == 5
