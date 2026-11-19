"""모의 수집 실행: AC-10, AC-14, AC-18 ~ AC-22."""
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime, timedelta

import pytest

from collector import flights as fl
from collector.config import KST
from collector.main import RunState, classify, run, update_status
from collector.store import DataStore, default_status
from conftest import BOT_HTML, ROOT, Sim, make_history, make_html, make_payload, simple_html

DAY1 = datetime(2026, 11, 19, 8, 0, 0, tzinfo=KST)


def validate(path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(ROOT / "schemas/validate.py"), str(path)], capture_output=True, text=True)


def load(path, name):
    return json.loads((path / name).read_text(encoding="utf-8"))


def price_table(cfg):
    """목적지 순서대로 가격이 높아지는 표. 3월 기준가는 연말 가격보다 낮다."""
    order = {d.code: i for i, d in enumerate(cfg.destinations)}

    def price(dest, depart, ret):
        base = 150000 + order[dest] * 20000
        if depart.startswith("2027-03"):
            return base - 30000
        return base + int(depart[-2:]) * 100 + int(ret[-2:]) * 10

    return price


def normal_responder(cfg, deal_dest=None, deal_price=None):
    price = price_table(cfg)

    def responder(origin, dest, depart, ret):
        p = price(dest, depart, ret)
        if dest == deal_dest and not depart.startswith("2027-03"):
            # 평소 범위 하한보다 낮고 최근 60일 하위 10% 이하 -> 기준 a + d
            p = deal_price
            return simple_html(p, low=p + 50000, high=p + 300000, history=make_history([p + 80000] * 60 + [p]))
        return simple_html(p, low=p - 20000, high=p + 200000, history=make_history([p - 10000] * 60 + [p]))

    return responder


def test_full_run_then_second_run(cfg, tmp_path):
    """1차: 토큰 없음. 2차: 토큰 있음. 두 번 모두 스키마와 교차 규칙을 통과한다(AC-20)."""
    out = tmp_path / "data"
    # JFK 는 가격 순위가 낮아 1차에서는 확대 대상이 아니다
    sim = Sim(normal_responder(cfg, "JFK", 900000))
    code = run(["--out", str(out)], sim.deps())
    assert code == 0
    v = validate(out)
    assert v.returncode == 0, v.stdout
    status = load(out, "status.json")
    r = status["last_run"]
    assert r["result"] == "ok" and status["state"] == "ok"
    assert r["queries"] == {"planned": 940, "attempted": 940, "succeeded": 940, "no_result": 0, "failed": 0, "bot_checks": 0, "retries": 0, "skipped": 0}
    assert r["baseline_queries"] == 100
    assert r["destinations_total"] == 60 and r["destinations_succeeded"] == 60
    # AC-10: 대표 조합 최저가 하위 10개(목록 앞 10개)만 확대
    assert r["expanded_destinations"] == [d.code for d in cfg.destinations[:10]]
    counts = Counter(k[1] for k in sim.fetched if not k[2].startswith("2027-03"))
    assert all(counts[d.code] == (64 if i < 10 else 6) for i, d in enumerate(cfg.destinations))
    assert r["deals_found"] == 1 and r["alerts_sent"] == 0 and r["telegram_enabled"] is False
    assert sim.posts == [] and sim.gets == []

    alerts = load(out, "alerts.json")["alerts"]
    assert len(alerts) == 1
    a = alerts[0]
    assert (a["destination"], a["status"], a["kind"], a["alerted_price_krw"]) == ("JFK", "active", "new", 900000)
    assert a["notification"]["sent"] is False and a["notification"]["attempts"] == 0
    assert "설정되지 않음" in a["notification"]["error"]
    assert a["fare"]["judgement"]["matched"] == ["google_low", "google_60d"]
    assert a["hotels"]["source"] == "links"

    latest = load(out, "latest.json")
    assert [d["destination"] for d in latest["destinations"]] == [d.code for d in cfg.destinations]
    cju = latest["destinations"][0]
    assert cju["expanded"] and len(cju["combos"]) == 64 and cju["best"]["price_krw"] == min(c["price_krw"] for c in cju["combos"])
    assert cju["best"]["insight"]["history_count"] == 61 and len(cju["best"]["insight"]["history"]) == 61
    assert "insight" not in cju["combos"][0]
    jfk = next(d for d in latest["destinations"] if d["destination"] == "JFK")
    assert not jfk["expanded"] and len(jfk["combos"]) == 6 and jfk["deal"]["price_krw"] == 900000
    assert len(load(out, "baseline.json")["entries"]) == 100
    hist = load(out, "history/CJU.json")["points"]
    assert len(hist) == 1 and hist[0]["combos_checked"] == 64 and hist[0]["rep_price_krw"] >= hist[0]["price_krw"]
    assert load(out, "index.json")["is_sample"] is False
    # AC-05: 실제 실행 흐름에서도 요청 시작 간격이 6초 이상
    assert min(b - a for a, b in zip(sim.fetch_times, sim.fetch_times[1:])) >= 6

    # ---- 2차 실행: 토큰 있음, SerpApi 키 있음
    sim2 = Sim(normal_responder(cfg, "JFK", 905000), env={"TELEGRAM_BOT_TOKEN": "111:AAA", "TELEGRAM_CHAT_ID": "42", "SERPAPI_KEY": "SERP"},
               start=DAY1 + timedelta(hours=6))
    sim2.get_response = {"properties": [{"name": "뉴욕 호텔", "rate_per_night": {"extracted_lowest": 210000}, "total_rate": {"extracted_lowest": 840000}, "overall_rating": 4.1, "link": "https://h.example/1"}]}
    assert run(["--out", str(out)], sim2.deps()) == 0
    v = validate(out)
    assert v.returncode == 0, v.stdout
    status = load(out, "status.json")
    r = status["last_run"]
    # active 알림이 있는 JFK 도 확대 조회한다(AC-10)
    assert r["expanded_destinations"] == [d.code for d in cfg.destinations[:10]] + ["JFK"]
    assert r["queries"]["planned"] == 360 + 11 * 58 and r["baseline_queries"] == 100
    assert r["alerts_sent"] == 1 and r["hotel_api_calls"] == 1 and r["telegram_enabled"] and r["serpapi_enabled"]
    assert status["serpapi"] == {"month": "2026-11", "calls": 1} and len(status["runs"]) == 2
    alerts = load(out, "alerts.json")["alerts"]
    assert len(alerts) == 1  # 같은 레코드로 다시 발송한다(AC-14)
    a = alerts[0]
    assert a["id"].startswith("JFK-20261119T080000") and a["alerted_price_krw"] == 905000
    assert a["notification"]["sent"] is True and a["notification"]["attempts"] == 1 and a["notification"]["error"] is None
    assert a["hotels"]["source"] == "serpapi" and a["hotels"]["items"][0]["name"] == "뉴욕 호텔"
    assert len(sim2.posts) == 1
    url, payload = sim2.posts[0]
    assert url == "https://api.telegram.org/bot111:AAA/sendMessage" and payload["chat_id"] == "42"
    assert "[특가] 뉴욕" in payload["text"] and "905,000원" in payload["text"] and "뉴욕 호텔 210,000원" in payload["text"]
    assert "SERP" not in json.dumps(payload) and "111:AAA" not in json.dumps(payload)
    assert len(load(out, "history/CJU.json")["points"]) == 2
    assert len(load(out, "baseline.json")["entries"]) == 200
    # 저장한 파일 어디에도 비밀 값이 없다
    for p in out.rglob("*.json"):
        text = p.read_text(encoding="utf-8")
        assert "111:AAA" not in text and "SERP" not in text.replace("SERPAPI", "").replace("serpapi", "")

    # ---- 3차 실행: 5% 미만 변동이면 발송하지 않는다. 특가가 해제되면 ended.
    sim3 = Sim(normal_responder(cfg, "JFK", 880000), env=sim2.env, start=DAY1 + timedelta(hours=13))
    assert run(["--out", str(out), "--destinations", "JFK,CJU"], sim3.deps()) == 0
    assert sim3.posts == [] and validate(out).returncode == 0
    a = load(out, "alerts.json")["alerts"][0]
    assert a["status"] == "active" and a["alerted_price_krw"] == 905000 and a["current_fare"]["price_krw"] == 880000
    sim4 = Sim(normal_responder(cfg), env=sim2.env, start=DAY1 + timedelta(hours=24))
    assert run(["--out", str(out), "--destinations", "JFK,CJU"], sim4.deps()) == 0
    v = validate(out)
    assert v.returncode == 0, v.stdout
    a = load(out, "alerts.json")["alerts"][0]
    assert a["status"] == "ended" and a["current_fare"] is None and sim4.posts == []
    latest = {d["destination"]: d for d in load(out, "latest.json")["destinations"]}
    assert latest["JFK"]["deal"] is None and latest["JFK"]["stale"] is False
    # 조회 대상이 아닌 목적지는 이전 항목을 변경하지 않는다(stale 로 표시하지 않는다)
    assert latest["KIX"]["stale"] is False and latest["KIX"]["best"] is not None


def test_dry_run_writes_nothing_and_sends_nothing(cfg, tmp_path):
    data = tmp_path / "data"
    sim = Sim(normal_responder(cfg, "CJU", 60000), env={"TELEGRAM_BOT_TOKEN": "1:A", "TELEGRAM_CHAT_ID": "2", "SERPAPI_KEY": "K"})
    code = run(["--dry-run", "--limit", "2", "--data", str(data)], sim.deps())
    assert code == 0
    assert not data.exists() and list(tmp_path.iterdir()) == []
    assert sim.posts == [] and sim.gets == []
    text = "\n".join(sim.lines)
    assert "결과: ok" in text and "제주" in text and "60,000원" in text and "저장하지 않음" in text
    assert "발송하지 않은 알림 메시지" in text and "[특가] 제주" in text


def test_dry_run_with_out_writes_only_there(cfg, tmp_path):
    data, out = tmp_path / "data", tmp_path / "out"
    sim = Sim(normal_responder(cfg, "CJU", 60000), env={"TELEGRAM_BOT_TOKEN": "1:A", "TELEGRAM_CHAT_ID": "2"})
    assert run(["--dry-run", "--limit", "2", "--data", str(data), "--out", str(out)], sim.deps()) == 0
    assert not data.exists() and sim.posts == []
    v = validate(out)
    assert v.returncode == 0, v.stdout
    a = load(out, "alerts.json")["alerts"][0]
    assert a["notification"]["sent"] is False and "dry-run" in a["notification"]["error"]
    r = load(out, "status.json")["last_run"]
    assert r["telegram_enabled"] is False and r["destinations_total"] == 2
    assert r["queries"]["attempted"] == 2 * 64 and r["baseline_queries"] == 10


def test_max_queries_skips_the_rest(cfg, tmp_path):
    out = tmp_path / "out"
    sim = Sim(normal_responder(cfg))
    assert run(["--out", str(out), "--destinations", "KIX,CJU", "--max-queries", "4"], sim.deps()) == 0
    q = load(out, "status.json")["last_run"]["queries"]
    assert (q["planned"], q["attempted"], q["skipped"]) == (12, 4, 8)
    assert Counter(k[1] for k in sim.fetched) == {"CJU": 2, "KIX": 2}
    assert validate(out).returncode == 0


def test_bot_check_retry_counts_in_status(cfg, tmp_path):
    out = tmp_path / "out"
    normal = normal_responder(cfg)
    seen = Counter()

    def responder(origin, dest, depart, ret):
        seen[(dest, depart, ret)] += 1
        if dest == "CJU" and depart == "2026-12-17" and seen[(dest, depart, ret)] == 1:
            return BOT_HTML
        return normal(origin, dest, depart, ret)

    sim = Sim(responder)
    assert run(["--out", str(out), "--limit", "1", "--max-queries", "6"], sim.deps()) == 0
    r = load(out, "status.json")["last_run"]
    assert r["result"] == "ok" and r["queries"]["bot_checks"] == 1 and r["queries"]["retries"] == 1
    assert r["queries"]["succeeded"] == 6 and r["errors"] == []
    assert 20 in sim.time.sleeps


def test_stale_destination_keeps_previous_values(cfg, tmp_path):
    """AC-21: 조회에 모두 실패한 목적지는 이전 값을 유지하고 이력을 추가하지 않는다."""
    out = tmp_path / "out"
    normal = normal_responder(cfg, "KIX", 100000)
    assert run(["--out", str(out), "--destinations", "KIX,CJU"], Sim(normal).deps()) == 0
    before = {d["destination"]: d for d in load(out, "latest.json")["destinations"]}
    assert before["KIX"]["deal"] is not None

    def responder(origin, dest, depart, ret):
        return ConnectionError("down") if dest == "KIX" else normal(origin, dest, depart, ret)

    sim = Sim(responder, start=DAY1 + timedelta(hours=6))
    assert run(["--out", str(out), "--destinations", "KIX,CJU"], sim.deps()) == 0
    v = validate(out)
    assert v.returncode == 0, v.stdout
    status = load(out, "status.json")
    r = status["last_run"]
    assert r["result"] == "partial" and status["state"] == "partial" and r["failed_destinations"] == ["KIX"]
    assert r["queries"]["failed"] == 6 and r["queries"]["retries"] == 12 and r["destinations_succeeded"] == 1
    assert all(e["kind"] == "network" and e["destination"] == "KIX" for e in r["errors"][:6])
    after = {d["destination"]: d for d in load(out, "latest.json")["destinations"]}
    assert after["KIX"]["stale"] is True
    assert {k: v for k, v in after["KIX"].items() if k != "stale"} == {k: v for k, v in before["KIX"].items() if k != "stale"}
    assert after["CJU"]["stale"] is False
    assert len(load(out, "history/KIX.json")["points"]) == 1 and len(load(out, "history/CJU.json")["points"]) == 2
    # 알림 상태도 유지한다(AC-12)
    a = load(out, "alerts.json")["alerts"][0]
    assert a["destination"] == "KIX" and a["status"] == "active"


def test_abort_after_eight_consecutive_failures_and_stop_notice(cfg, tmp_path):
    """AC-18, AC-19: 연속 실패 8건이면 중단, failed 3회 연속이면 수집 중단 안내 1회, 이후 재개 안내 1회."""
    out = tmp_path / "out"
    env = {"TELEGRAM_BOT_TOKEN": "1:A", "TELEGRAM_CHAT_ID": "2"}
    posts = []
    for i in range(4):
        sim = Sim(lambda *a: BOT_HTML, env=env, start=DAY1 + timedelta(hours=6 * i))
        assert run(["--out", str(out), "--limit", "3"], sim.deps()) == 1
        posts.append(sim.posts)
        status = load(out, "status.json")
        r = status["last_run"]
        assert r["result"] == "failed" and r["queries"]["attempted"] == 8 and r["queries"]["failed"] == 8
        assert r["queries"]["planned"] == 18 and r["queries"]["skipped"] == 10 and r["baseline_queries"] == 0
        assert "연속 8건" in r["aborted_reason"] and len(sim.fetched) == 24
        assert status["consecutive_failures"] == i + 1
        assert status["state"] == ("stopped" if i >= 2 else "failed")
        assert status["stop_notice_sent"] is (i >= 2)
        assert validate(out).returncode == 0
    assert [len(p) for p in posts] == [0, 0, 1, 0]
    text = posts[2][0][1]["text"]
    assert text.startswith("[수집 중단] 항공권 수집이 3회 연속 실패했습니다. 마지막 성공: 없음. 주요 원인: 봇 확인 페이지 응답.")
    assert "parse_mode" not in posts[2][0][1]

    sim = Sim(normal_responder(cfg), env=env, start=DAY1 + timedelta(hours=30))
    assert run(["--out", str(out), "--limit", "3"], sim.deps()) == 0
    status = load(out, "status.json")
    assert [p[1]["text"] for p in sim.posts] == ["[수집 재개] 항공권 수집이 다시 정상 처리되었습니다."]
    assert status["state"] == "ok" and status["consecutive_failures"] == 0 and status["stop_notice_sent"] is False
    assert status["last_success_at"] == status["last_run"]["finished_at"] and len(status["runs"]) == 5
    sim = Sim(normal_responder(cfg), env=env, start=DAY1 + timedelta(hours=36))
    run(["--out", str(out), "--limit", "3"], sim.deps())
    assert sim.posts == []


def test_stop_notice_is_retried_until_sent(cfg, tmp_path):
    out = tmp_path / "out"
    for i in range(3):
        sim = Sim(lambda *a: BOT_HTML, start=DAY1 + timedelta(hours=6 * i))  # 토큰 없음
        assert run(["--out", str(out), "--limit", "1"], sim.deps()) == 1
    status = load(out, "status.json")
    assert status["state"] == "stopped" and status["stop_notice_sent"] is False
    sim = Sim(lambda *a: BOT_HTML, env={"TELEGRAM_BOT_TOKEN": "1:A", "TELEGRAM_CHAT_ID": "2"}, start=DAY1 + timedelta(hours=24))
    run(["--out", str(out), "--limit", "1"], sim.deps())
    assert len(sim.posts) == 1 and load(out, "status.json")["stop_notice_sent"] is True


def test_telegram_failure_does_not_change_result(cfg, tmp_path):
    """AC-14: 발송 실패는 errors 에만 기록하고 다음 실행에서 같은 레코드로 다시 시도한다."""
    out = tmp_path / "out"
    env = {"TELEGRAM_BOT_TOKEN": "1:A", "TELEGRAM_CHAT_ID": "2"}
    sim = Sim(normal_responder(cfg, "CJU", 60000), env=env)
    sim.post_response = {"ok": False, "description": "Forbidden: bot was blocked by the user"}
    assert run(["--out", str(out), "--limit", "1"], sim.deps()) == 0
    r = load(out, "status.json")["last_run"]
    assert r["result"] == "ok" and r["alerts_sent"] == 0 and r["deals_found"] == 1
    assert [e["kind"] for e in r["errors"]] == ["telegram"]
    a = load(out, "alerts.json")["alerts"][0]
    assert a["notification"] == {"channel": "telegram", "sent": False, "sent_at": None, "attempts": 1, "error": "Forbidden: bot was blocked by the user"}
    sim = Sim(normal_responder(cfg, "CJU", 60000), env=env, start=DAY1 + timedelta(hours=6))
    assert run(["--out", str(out), "--limit", "1"], sim.deps()) == 0
    alerts = load(out, "alerts.json")["alerts"]
    assert len(alerts) == 1 and alerts[0]["notification"]["sent"] is True and alerts[0]["notification"]["attempts"] == 2
    assert validate(out).returncode == 0


def test_realert_end_to_end(cfg, tmp_path):
    out = tmp_path / "out"
    env = {"TELEGRAM_BOT_TOKEN": "1:A", "TELEGRAM_CHAT_ID": "2"}
    for i, (price, expect_posts) in enumerate([(359000, 1), (341100, 0), (341050, 1)]):
        sim = Sim(normal_responder(cfg, "DAD", price), env=env, start=DAY1 + timedelta(hours=6 * i))
        assert run(["--out", str(out), "--destinations", "DAD", "--max-queries", "6"], sim.deps()) == 0
        assert len(sim.posts) == expect_posts
        assert validate(out).returncode == 0
    alerts = load(out, "alerts.json")["alerts"]
    assert [(a["status"], a["kind"], a["alerted_price_krw"]) for a in alerts] == [("active", "realert", 341050), ("replaced", "new", 359000)]
    assert "[특가·추가 인하] 다낭(베트남) 341,050원 (직전 알림 359,000원)" in sim.posts[0][1]["text"]


def test_no_result_is_not_a_query_failure_but_all_no_result_run_fails(cfg, tmp_path):
    """결과 없음은 조회 실패로 세지 않는다. 다만 가격을 1건도 얻지 못한 실행은 failed 로 기록한다."""
    out = tmp_path / "out"
    sim = Sim(lambda *a: make_html(make_payload([])))
    assert run(["--out", str(out), "--limit", "2"], sim.deps()) == 1
    r = load(out, "status.json")["last_run"]
    assert r["result"] == "failed" and r["queries"]["no_result"] == 12 and r["queries"]["succeeded"] == 0
    assert r["queries"]["failed"] == 0 and r["aborted_reason"] is None
    assert r["expanded_destinations"] == [] and r["failed_destinations"] == []
    assert r["errors"][0]["kind"] == "other" and "항공편을 찾지 못해" in r["errors"][0]["message"]
    latest = load(out, "latest.json")["destinations"]
    assert latest[0]["best"] is None and latest[0]["stale"] is False and latest[0]["combos"] == []
    assert load(out, "index.json")["destinations"][0]["history_file"] is None
    assert not (out / "history").exists() and validate(out).returncode == 0


def test_all_no_result_run_keeps_previous_data_and_alerts(cfg, tmp_path):
    """응답이 모두 빈 항공편 목록이면 이전 가격·알림을 유지하고 실행을 failed 로 기록한다."""
    out = tmp_path / "out"
    env = {"TELEGRAM_BOT_TOKEN": "1:A", "TELEGRAM_CHAT_ID": "2"}
    assert run(["--out", str(out), "--limit", "3"], Sim(normal_responder(cfg, "CJU", 60000), env=env).deps()) == 0
    before = {d["destination"]: d for d in load(out, "latest.json")["destinations"]}
    sim = Sim(lambda *a: make_html(make_payload([])), env=env, start=DAY1 + timedelta(hours=6))
    assert run(["--out", str(out), "--limit", "3"], sim.deps()) == 1
    v = validate(out)
    assert v.returncode == 0, v.stdout
    status = load(out, "status.json")
    assert status["last_run"]["result"] == "failed" and status["consecutive_failures"] == 1
    after = {d["destination"]: d for d in load(out, "latest.json")["destinations"]}
    for code in [d.code for d in cfg.destinations[:3]]:
        assert after[code]["stale"] is True
        assert after[code]["best"] == before[code]["best"] and after[code]["combos"] == before[code]["combos"]
    assert after["CJU"]["deal"] is not None
    assert [(a["destination"], a["status"]) for a in load(out, "alerts.json")["alerts"]] == [("CJU", "active")]
    assert sim.posts == []
    assert len(load(out, "history/CJU.json")["points"]) == 1


def test_high_no_result_ratio_is_partial(cfg, tmp_path):
    out = tmp_path / "out"
    normal = normal_responder(cfg)

    def responder(origin, dest, depart, ret):
        if depart.startswith("2027-03") or depart == "2026-12-17":
            return normal(origin, dest, depart, ret)
        return make_html(make_payload([]))

    assert run(["--out", str(out), "--limit", "1", "--max-queries", "6"], Sim(responder).deps()) == 0
    r = load(out, "status.json")["last_run"]
    assert r["result"] == "partial" and (r["queries"]["succeeded"], r["queries"]["no_result"]) == (1, 5)
    assert "결과 없음이 5건" in r["errors"][0]["message"]


def deal_on(cfg, dest, depart_date, price=60000):
    """dest 의 depart_date 출발 조합만 특가인 응답."""
    normal = normal_responder(cfg)

    def responder(origin, d, depart, ret):
        if d == dest and depart == depart_date:
            return simple_html(price, low=price + 50000, high=price + 300000, history=make_history([price + 80000] * 60 + [price]))
        return normal(origin, d, depart, ret)

    return responder


def test_aborted_run_keeps_deal_and_combos_of_unqueried_combos(cfg, tmp_path):
    """연속 실패로 중단된 실행: 조회하지 못한 조합의 이전 값·특가·알림 상태를 유지한다."""
    out = tmp_path / "out"
    env = {"TELEGRAM_BOT_TOKEN": "1:A", "TELEGRAM_CHAT_ID": "2"}
    first = deal_on(cfg, "CJU", "2026-12-19")  # 12/19 출발은 대표 조합이 아니다(확대 조회에서만 조회)
    sim = Sim(first, env=env)
    assert run(["--out", str(out), "--limit", "2"], sim.deps()) == 0
    assert len(sim.posts) == 1
    before = {d["destination"]: d for d in load(out, "latest.json")["destinations"]}["CJU"]
    assert before["deal"]["depart_date"] == "2026-12-19" and len(before["combos"]) == 64

    calls = Counter()

    def second(origin, dest, depart, ret):
        calls["n"] += 1
        return first(origin, dest, depart, ret) if calls["n"] <= 12 else BOT_HTML  # 대표 조합 12건 후 봇 확인

    sim = Sim(second, env=env, start=DAY1 + timedelta(hours=6))
    assert run(["--out", str(out), "--limit", "2"], sim.deps()) == 0
    v = validate(out)
    assert v.returncode == 0, v.stdout
    r = load(out, "status.json")["last_run"]
    assert r["result"] == "partial" and "연속 8건" in r["aborted_reason"]
    cju = {d["destination"]: d for d in load(out, "latest.json")["destinations"]}["CJU"]
    assert cju["stale"] is False and cju["deal"] == before["deal"] and cju["best"] == before["best"]
    assert len(cju["combos"]) == 64 and cju["expanded"] is True
    fresh = [c for c in cju["combos"] if c["collected_at"] > before["last_success_at"]]
    assert len(fresh) == 6 and all(c["is_representative"] for c in fresh)
    a = load(out, "alerts.json")["alerts"]
    assert [(x["destination"], x["status"], x["ended_at"]) for x in a] == [("CJU", "active", None)]
    assert a[0]["current_checked_at"] < r["started_at"]  # 조회하지 못했으므로 확인 시각을 갱신하지 않는다
    assert sim.posts == []
    hist = load(out, "history/CJU.json")["points"]
    assert len(hist) == 2 and hist[-1]["combos_checked"] == 6 and hist[-1]["price_krw"] == hist[-1]["rep_price_krw"]

    # 다음 정상 실행에서 특가 조합을 조회해 해제되면 그때 ended 로 처리한다
    sim = Sim(normal_responder(cfg), env=env, start=DAY1 + timedelta(hours=12))
    assert run(["--out", str(out), "--limit", "2"], sim.deps()) == 0
    assert load(out, "alerts.json")["alerts"][0]["status"] == "ended" and validate(out).returncode == 0


def test_failed_combo_keeps_previous_combo_value(cfg, tmp_path):
    """조회 대상 중 일부 조합만 실패한 실행: 실패한 조합은 이전 값을 유지하고, 응답을 받은 조합만 갱신한다."""
    out = tmp_path / "out"
    env = {"TELEGRAM_BOT_TOKEN": "1:A", "TELEGRAM_CHAT_ID": "2"}
    first = deal_on(cfg, "CJU", "2026-12-19")
    assert run(["--out", str(out), "--limit", "1"], Sim(first, env=env).deps()) == 0

    def second(origin, dest, depart, ret):
        return ConnectionError("down") if depart == "2026-12-19" else first(origin, dest, depart, ret)

    sim = Sim(second, env=env, start=DAY1 + timedelta(hours=6))
    assert run(["--out", str(out), "--limit", "1"], sim.deps()) == 0
    assert validate(out).returncode == 0
    cju = load(out, "latest.json")["destinations"][0]
    assert cju["deal"] is not None and cju["deal"]["depart_date"] == "2026-12-19" and len(cju["combos"]) == 64
    assert load(out, "alerts.json")["alerts"][0]["status"] == "active" and sim.posts == []


def test_unselected_destinations_are_left_unchanged(cfg, tmp_path):
    out = tmp_path / "out"
    assert run(["--out", str(out), "--limit", "3"], Sim(normal_responder(cfg)).deps()) == 0
    before = {d["destination"]: d for d in load(out, "latest.json")["destinations"]}
    sim = Sim(normal_responder(cfg), start=DAY1 + timedelta(hours=6))
    assert run(["--out", str(out), "--destinations", "KIX"], sim.deps()) == 0
    after = {d["destination"]: d for d in load(out, "latest.json")["destinations"]}
    assert sum(d["stale"] for d in after.values()) == 0
    assert after["CJU"] == before["CJU"] and after["KIX"]["last_success_at"] > before["CJU"]["last_success_at"]
    assert load(out, "status.json")["last_run"]["failed_destinations"] == []
    assert validate(out).returncode == 0


def test_run_time_limit_skips_remaining_queries_and_saves(cfg, tmp_path):
    """실행 시간 상한(150분)을 넘으면 남은 조회를 생략하고 정상 저장한다."""
    out = tmp_path / "out"
    normal = normal_responder(cfg)
    seen = Counter()

    def responder(origin, dest, depart, ret):  # 3건 중 1건은 봇 확인 후 재시도에서 성공(조회당 약 34초)
        seen[(dest, depart, ret)] += 1
        n = sum(seen.values())
        return BOT_HTML if n % 3 == 0 and seen[(dest, depart, ret)] == 1 else normal(origin, dest, depart, ret)

    sim = Sim(responder)
    assert run(["--out", str(out)], sim.deps()) == 0
    status = load(out, "status.json")
    r = status["last_run"]
    assert r["aborted_reason"] == "실행 시간 상한 150분을 초과해 남은 조회를 생략함"
    assert 150 * 60 <= r["duration_seconds"] < 153 * 60
    assert r["result"] == "ok" and r["queries"]["skipped"] > 0 and r["baseline_queries"] == 0
    assert status["consecutive_failures"] == 0
    assert (out / "latest.json").exists() and validate(out).returncode == 0


def test_run_after_departure_period_does_nothing_and_is_not_a_failure(cfg, tmp_path):
    """출발 가능 기간이 끝난 뒤(12/30 이후): 조회·기준가 갱신·수집 중단 안내가 없고 종료 코드는 0."""
    out = tmp_path / "out"
    env = {"TELEGRAM_BOT_TOKEN": "1:A", "TELEGRAM_CHAT_ID": "2"}
    start = datetime(2026, 12, 29, 21, 0, 0, tzinfo=KST)
    assert run(["--out", str(out), "--limit", "2"], Sim(normal_responder(cfg), env=env, start=start).deps()) == 0
    latest_before = (out / "latest.json").read_text(encoding="utf-8")
    first_status = None
    for i in range(4):
        sim = Sim(normal_responder(cfg), env=env, start=datetime(2026, 12, 30, 8, 0, 0, tzinfo=KST) + timedelta(hours=7 * i))
        assert run(["--out", str(out), "--limit", "2"], sim.deps()) == 0
        assert sim.fetched == [] and sim.posts == []
        text = (out / "status.json").read_text(encoding="utf-8")
        first_status = first_status or text
        assert text == first_status  # 2회째부터는 파일을 변경하지 않는다
    status = load(out, "status.json")
    r = status["last_run"]
    assert r["result"] == "ok" and r["aborted_reason"] == "출발 가능 기간이 끝나 조회 대상이 없음"
    assert r["queries"]["planned"] == 0 and r["baseline_queries"] == 0
    assert status["state"] == "ok" and status["consecutive_failures"] == 0 and len(status["runs"]) == 2
    assert status["last_success_at"].startswith("2026-12-29")
    assert (out / "latest.json").read_text(encoding="utf-8") == latest_before
    assert validate(out).returncode == 0


def test_default_site_url_from_github_repository(cfg, tmp_path):
    from collector.main import default_site_url

    assert default_site_url({}) == ""
    assert default_site_url({"GITHUB_REPOSITORY": "Someone/flight-deals"}) == "https://someone.github.io/flight-deals/"
    assert default_site_url({"GITHUB_REPOSITORY": "someone/someone.github.io"}) == "https://someone.github.io/"
    out = tmp_path / "out"
    env = {"TELEGRAM_BOT_TOKEN": "1:A", "TELEGRAM_CHAT_ID": "2", "GITHUB_REPOSITORY": "someone/flight-deals"}
    sim = Sim(normal_responder(cfg, "CJU", 60000), env=env)
    assert run(["--out", str(out), "--limit", "1", "--max-queries", "6"], sim.deps()) == 0
    assert sim.posts[0][1]["text"].split("\n")[-1] == "사이트: https://someone.github.io/flight-deals/#dest=CJU"


def test_exception_still_saves_status(cfg, tmp_path, monkeypatch):
    out = tmp_path / "out"
    monkeypatch.setattr("collector.main.build_entries", lambda *a, **k: 1 / 0)
    sim = Sim(normal_responder(cfg))
    assert run(["--out", str(out), "--limit", "1", "--max-queries", "2"], sim.deps()) == 1
    status = load(out, "status.json")
    assert status["last_run"]["result"] == "failed" and "ZeroDivisionError" in status["last_run"]["aborted_reason"]
    assert status["last_run"]["errors"][-1]["kind"] == "other" and status["consecutive_failures"] == 1


@pytest.mark.parametrize(
    "ok,nores,failed,expected",
    [(10, 0, 0, "ok"), (0, 5, 0, "failed"), (5, 5, 0, "ok"), (4, 6, 0, "partial"), (5, 0, 5, "partial"), (4, 1, 5, "partial"), (4, 0, 5, "failed"), (0, 0, 8, "failed"), (0, 0, 0, "failed")],
)
def test_result_classification(cfg, ok, nores, failed, expected):
    s = RunState(cfg=cfg, client=None, now=None)
    s.succeeded, s.no_result, s.failed = ok, nores, failed
    s.attempted = ok + nores + failed
    assert classify(s) == expected


def test_retention_limits(cfg, tmp_path):
    """AC-21: 이력 400건, 실행 30건."""
    store = DataStore(tmp_path, tmp_path)
    d = cfg.destinations[0]
    points = [
        {"collected_at": (DAY1 + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M:%S+09:00"), "run_id": f"{i}", "price_krw": i}
        for i in range(450)
    ]
    store.save_history(d, points[::-1], cfg.keep_history)
    saved = load(tmp_path, f"history/{d.code}.json")["points"]
    assert len(saved) == 400 and saved[0]["price_krw"] == 50 and saved[-1]["price_krw"] == 449

    status = default_status("2026-11-19T08:00:00+09:00")

    class N:
        enabled = False

    for i in range(35):
        s = RunState(cfg=cfg, client=None, now=None)
        update_status(status, s, {"run_id": f"r{i}", "result": "ok", "finished_at": "t"}, N(), cfg, "t")
    assert len(status["runs"]) == 30 and status["runs"][0]["run_id"] == "r34" and status["runs"][0] == status["last_run"]


def test_errors_are_capped_at_50(cfg):
    s = RunState(cfg=cfg, client=None, now=None)
    for i in range(70):
        s.add_error("network", "x", "KIX")
    assert len(s.errors) == 50 and s.error_kinds["network"] == 70


def test_serpapi_month_counter_resets(cfg, tmp_path):
    out = tmp_path / "out"
    assert run(["--out", str(out), "--limit", "1", "--max-queries", "1"], Sim(normal_responder(cfg)).deps()) == 0
    doc = load(out, "status.json")
    doc["serpapi"] = {"month": "2026-11", "calls": 200}
    (out / "status.json").write_text(json.dumps(doc), encoding="utf-8")
    sim = Sim(normal_responder(cfg), start=datetime(2026, 12, 1, 8, 0, 0, tzinfo=KST))
    assert run(["--out", str(out), "--limit", "1", "--max-queries", "1"], sim.deps()) == 0
    assert load(out, "status.json")["serpapi"] == {"month": "2026-12", "calls": 0}
