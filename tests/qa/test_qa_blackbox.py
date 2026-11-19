"""QA 블랙박스 테스트: collector.main.run() 을 모의 HTTP 로 실행하고 저장된 JSON 만 확인한다.

대상: AC-04, AC-05, AC-07, AC-08, AC-09, AC-11, AC-12, AC-20, AC-01(실행일이 여행 기간 안인 경우).
네트워크는 사용하지 않는다.
"""
import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from collector.config import KST
from collector.main import run
from conftest import BOT_HTML, ROOT, Sim, make_history, simple_html

DAY1 = datetime(2026, 11, 19, 8, 0, 0, tzinfo=KST)
ENV = {"TELEGRAM_BOT_TOKEN": "1:A", "TELEGRAM_CHAT_ID": "2"}
ONE = ["--destinations", "KIX", "--max-queries", "1"]  # 대표 조합 1번(12/17 출발 3박) 1건만 조회


def validate(path):
    return subprocess.run([sys.executable, str(ROOT / "schemas/validate.py"), str(path)], capture_output=True, text=True)


def load(path, name):
    return json.loads((Path(path) / name).read_text(encoding="utf-8"))


def kix(out):
    return next(d for d in load(out, "latest.json")["destinations"] if d["destination"] == "KIX")


def run_one(out, html, start=DAY1, env=None, args=ONE):
    sim = Sim(lambda *k: html, env=env, start=start)
    code = run(["--out", str(out), *args], sim.deps())
    return sim, code


def seed_baseline(out, price):
    out.mkdir(parents=True, exist_ok=True)
    doc = {"schema_version": 1, "updated_at": "2026-11-18T08:00:00+09:00", "entries": [{
        "origin": "ICN", "destination": "KIX", "nights": 3, "depart_date": "2027-03-09", "return_date": "2027-03-12",
        "price_krw": price, "airlines": ["에어서울"], "stops": 0, "search_url": "https://www.google.com/travel/flights",
        "collected_at": "2026-11-18T08:00:00+09:00"}]}
    (out / "baseline.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def seed_history(out, rep_prices):
    (out / "history").mkdir(parents=True, exist_ok=True)
    pts = []
    for i, p in enumerate(rep_prices):
        t = datetime(2026, 11, 10, 8, 0, 0, tzinfo=KST) + timedelta(hours=8 * i)
        pts.append({"collected_at": t.strftime("%Y-%m-%dT%H:%M:%S+09:00"), "run_id": t.strftime("%Y%m%dT%H%M%S"),
                    "price_krw": p, "rep_price_krw": p, "depart_date": "2026-12-17", "return_date": "2026-12-20",
                    "nights": 3, "airlines": ["에어서울"], "stops": 0, "combos_checked": 6})
    doc = {"schema_version": 1, "origin": "ICN", "destination": "KIX", "city_ko": "오사카", "country_ko": "일본",
           "region": "일본", "points": pts}
    (out / "history" / "KIX.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------- AC-07 / AC-08 / AC-09


@pytest.mark.parametrize("price,matched,level", [(300000, False, "typical"), (299999, True, "low"), (500001, False, "high")])
def test_ac07_a_google_low_boundary(tmp_path, price, matched, level):
    html = simple_html(price, low=300000, high=500000, history=make_history([400000] * 10 + [price]))
    run_one(tmp_path, html)
    j, ins = kix(tmp_path)["best"]["judgement"], kix(tmp_path)["best"]["insight"]
    assert ("google_low" in j["matched"]) is matched and "google_low" in j["evaluated"]
    assert ins["level"] == level
    assert "google_60d" not in j["evaluated"]  # 이력 10점(마지막 제외) < 30
    assert validate(tmp_path).returncode == 0


@pytest.mark.parametrize("price,matched", [(250000, True), (250001, False)])
def test_ac07_b_offseason_boundary(tmp_path, price, matched):
    seed_baseline(tmp_path, 250000)
    run_one(tmp_path, simple_html(price))  # Google 가격 정보 없음
    j = kix(tmp_path)["best"]["judgement"]
    assert j["evaluated"] == ["offseason"]  # AC-08: 가격 정보가 null 이면 a·d 는 평가하지 않는다
    assert ("offseason" in j["matched"]) is matched
    assert j["baseline_price_krw"] == 250000
    assert kix(tmp_path)["best"]["insight"] is None


@pytest.mark.parametrize("n,price,evaluated,matched", [
    (9, 340000, True, True),    # 중앙값 400,000 x 0.85 = 340,000 -> 해당
    (9, 340001, True, False),
    (8, 100000, False, False),  # 이력 8건이면 평가하지 않음
])
def test_ac07_c_own_history_boundary(tmp_path, n, price, evaluated, matched):
    seed_history(tmp_path, [400000] * n)
    run_one(tmp_path, simple_html(price))
    j = kix(tmp_path)["best"]["judgement"]
    assert ("own_history" in j["evaluated"]) is evaluated
    assert ("own_history" in j["matched"]) is matched
    assert j["own_samples"] == n


def test_ac09_c_excludes_current_run(tmp_path):
    """과거 8건 + 이번 실행 1건 = 9건이지만 이번 실행은 제외하므로 평가하지 않는다. 같은 가격으로 다시 실행하면 9건이 된다."""
    seed_history(tmp_path, [400000] * 8)
    run_one(tmp_path, simple_html(100000))
    assert "own_history" not in kix(tmp_path)["best"]["judgement"]["evaluated"]
    run_one(tmp_path, simple_html(100000), start=DAY1 + timedelta(hours=6))
    j = kix(tmp_path)["best"]["judgement"]
    assert j["own_samples"] == 9 and "own_history" in j["matched"]
    assert j["own_median_krw"] == 400000  # 8 x 400,000 + 100,000 의 중앙값


@pytest.mark.parametrize("past_points,price,evaluated,matched", [
    (30, 200000, True, True),    # P10 = ceil(3)-1 = 2번째(0부터) = 200,000
    (30, 200001, True, False),
    (29, 100000, False, False),  # 마지막 점 제외 후 29개이면 평가하지 않음
])
def test_ac07_d_google_60d_boundary(tmp_path, past_points, price, evaluated, matched):
    past = [190000, 195000, 200000] + [300000] * (past_points - 3)
    # 마지막 점(조회 당일)은 매우 낮은 값이지만 계산에서 제외되어야 한다(AC-09)
    html = simple_html(price, low=1, high=10**7, history=make_history(past + [1000]))
    run_one(tmp_path, html)
    best = kix(tmp_path)["best"]
    j = best["judgement"]
    assert ("google_60d" in j["evaluated"]) is evaluated
    assert ("google_60d" in j["matched"]) is matched
    if evaluated:
        assert best["insight"]["history_p10_krw"] == 200000
        assert best["insight"]["history_min_krw"] == 190000
    assert validate(tmp_path).returncode == 0


def test_ac08_single_criterion_is_not_deal_and_two_are(tmp_path):
    a = tmp_path / "a"
    run_one(a, simple_html(299999, low=300000, high=500000, history=make_history([400000] * 10 + [299999])), env=ENV)
    e = kix(a)
    assert e["best"]["judgement"]["matched"] == ["google_low"] and e["deal"] is None
    assert load(a, "alerts.json")["alerts"] == []
    b = tmp_path / "b"
    seed_baseline(b, 299999)
    sim, _ = run_one(b, simple_html(299999, low=300000, high=500000, history=make_history([400000] * 10 + [299999])), env=ENV)
    e = kix(b)
    assert e["best"]["judgement"]["matched"] == ["google_low", "offseason"] and e["deal"] is not None
    assert len(sim.posts) == 1 and load(b, "alerts.json")["alerts"][0]["notification"]["sent"] is True
    assert validate(b).returncode == 0


# ---------------------------------------------------------------- AC-11 / AC-12


def deal_html(p):
    return simple_html(p, low=p + 50000, high=p + 300000, history=make_history([p + 80000] * 60 + [p]))


@pytest.mark.parametrize("second,posts,expected", [
    (341050, 1, [("active", "realert", 341050), ("replaced", "new", 359000)]),
    (341051, 0, [("active", "new", 359000)]),
])
def test_ac11_realert_exact_five_percent(tmp_path, second, posts, expected):
    run_one(tmp_path, deal_html(359000), env=ENV)
    sim, _ = run_one(tmp_path, deal_html(second), env=ENV, start=DAY1 + timedelta(hours=6))
    alerts = load(tmp_path, "alerts.json")["alerts"]
    assert len(sim.posts) == posts
    assert [(a["status"], a["kind"], a["alerted_price_krw"]) for a in alerts] == expected
    assert alerts[0]["current_fare"]["price_krw"] == second  # 미발송이어도 현재 가격은 갱신한다(AC-12)
    assert validate(tmp_path).returncode == 0


def test_ac11_realert_integer_rounding(tmp_path):
    """L = 100,001원이면 기준은 95,000.95원. 95,001원은 미발송, 95,000원은 발송."""
    run_one(tmp_path, deal_html(100001), env=ENV)
    sim, _ = run_one(tmp_path, deal_html(95001), env=ENV, start=DAY1 + timedelta(hours=6))
    assert len(sim.posts) == 0
    sim, _ = run_one(tmp_path, deal_html(95000), env=ENV, start=DAY1 + timedelta(hours=12))
    assert len(sim.posts) == 1
    assert "(직전 알림 100,001원)" in sim.posts[0][1]["text"]


def test_ac12_deal_gone_then_back_and_stale(tmp_path):
    run_one(tmp_path, deal_html(359000), env=ENV)
    # 조회 실패(stale): 상태 유지
    sim, code = run_one(tmp_path, BOT_HTML, env=ENV, start=DAY1 + timedelta(hours=6))
    a = load(tmp_path, "alerts.json")["alerts"]
    assert code == 1 and [x["status"] for x in a] == ["active"] and kix(tmp_path)["stale"] is True
    assert kix(tmp_path)["deal"]["price_krw"] == 359000
    assert len(load(tmp_path, "history/KIX.json")["points"]) == 1  # 이력 점이 추가되지 않는다(AC-21)
    assert validate(tmp_path).returncode == 0
    # 특가 해제: ended
    run_one(tmp_path, simple_html(700000), env=ENV, start=DAY1 + timedelta(hours=12))
    a = load(tmp_path, "alerts.json")["alerts"]
    assert a[0]["status"] == "ended" and a[0]["current_fare"] is None and a[0]["ended_at"]
    # 다시 특가(5% 미만 하락): 발송 없이 active 로 되돌린다
    sim, _ = run_one(tmp_path, deal_html(350000), env=ENV, start=DAY1 + timedelta(hours=18))
    a = load(tmp_path, "alerts.json")["alerts"]
    assert len(sim.posts) == 0 and len(a) == 1 and a[0]["status"] == "active" and a[0]["ended_at"] is None
    assert validate(tmp_path).returncode == 0


# ---------------------------------------------------------------- AC-04 / AC-05


def test_ac04_ac05_bot_check_retry_and_spacing(tmp_path):
    seq = iter([BOT_HTML, BOT_HTML, simple_html(300000), BOT_HTML, simple_html(310000)])
    sim = Sim(lambda *k: next(seq), start=DAY1)
    code = run(["--out", str(tmp_path), "--destinations", "KIX", "--max-queries", "2"], sim.deps())
    q = load(tmp_path, "status.json")["last_run"]["queries"]
    assert code == 0 and load(tmp_path, "status.json")["last_run"]["result"] == "ok"
    assert (q["attempted"], q["succeeded"], q["failed"], q["bot_checks"], q["retries"]) == (2, 2, 0, 3, 3)
    assert [s for s in sim.time.sleeps if s in (20, 60)] == [20, 60, 20]
    gaps = [b - a for a, b in zip(sim.fetch_times, sim.fetch_times[1:])]
    assert len(sim.fetch_times) == 5 and min(gaps) >= 6  # 재시도 요청에도 간격 적용
    assert len(kix(tmp_path)["combos"]) == 2


def test_ac04_bot_check_three_times_is_failure(tmp_path):
    sim, code = run_one(tmp_path, BOT_HTML)
    run_rec = load(tmp_path, "status.json")["last_run"]
    assert code == 1 and run_rec["result"] == "failed"
    assert len(sim.fetched) == 3 and run_rec["queries"]["bot_checks"] == 3 and run_rec["queries"]["retries"] == 2
    assert run_rec["errors"][0]["kind"] == "bot_check" and run_rec["failed_destinations"] == ["KIX"]


# ---------------------------------------------------------------- AC-20: 실제 수집 결과의 스키마 검증


def test_ac20_real_output_conforms(request):
    """QA 실제 조회 결과 폴더(환경 변수 QA_LIVE_DIR)가 있으면 스키마·교차 규칙을 검증한다."""
    import os

    d = os.environ.get("QA_LIVE_DIR")
    if not d or not Path(d).is_dir():
        pytest.skip("QA_LIVE_DIR 미지정")
    r = validate(d)
    assert r.returncode == 0, r.stdout
    for dest in load(d, "latest.json")["destinations"]:
        for c in dest["combos"]:
            assert c["search_url"].startswith("https://www.google.com/travel/flights")
        if dest["best"]:
            assert dest["best"]["price_krw"] == min(c["price_krw"] for c in dest["combos"])
            assert dest["best"]["insight"]["history_count"] == len(dest["best"]["insight"]["history"])


# ---------------------------------------------------------------- 여행 기간 중 실행(AC-01 의 실행일 규칙이 수집 전체에 주는 영향)


def december_queries(day, args=()):
    sim = Sim(lambda *k: simple_html(300000), start=datetime(2026, 12, day, 8, 0, 0, tzinfo=KST))
    code = run(["--dry-run", "--destinations", "KIX", *args], sim.deps())
    return code, [(k[2], k[3]) for k in sim.fetched if k[2].startswith("2026-12")]


def test_run_on_dec28_queries_all_remaining_combos():
    code, q = december_queries(28)
    assert code == 0 and sorted(q) == [
        ("2026-12-29", "2027-01-01"), ("2026-12-29", "2027-01-02"), ("2026-12-29", "2027-01-03"),
        ("2026-12-30", "2027-01-02"), ("2026-12-30", "2027-01-03")]


def test_run_on_dec29_still_checks_dec30_departures():
    """12/29 실행: 12/30 출발 3박·4박 조합은 조건 안이다(AC-01 은 실행일 이전 출발만 제외)."""
    code, q = december_queries(29)
    assert sorted(q) == [("2026-12-30", "2027-01-02"), ("2026-12-30", "2027-01-03")]
    assert code == 0


def test_aborted_run_does_not_end_alert_of_unqueried_combo(tmp_path):
    """특가 조합(12/29 출발)을 이번 실행에서 조회하지 못했는데(상한) 알림이 ended 로 바뀌면 안 된다."""
    def first(o, d, dep, ret):
        return deal_html(359000) if dep == "2026-12-29" else simple_html(600000)
    sim = Sim(first, env=ENV, start=DAY1)
    run(["--out", str(tmp_path), "--destinations", "KIX", "--max-queries", "6"], sim.deps())
    assert load(tmp_path, "alerts.json")["alerts"][0]["status"] == "active"
    sim = Sim(first, env=ENV, start=DAY1 + timedelta(hours=6))
    run(["--out", str(tmp_path), "--destinations", "KIX", "--max-queries", "1"], sim.deps())  # 12/17 조합만 조회
    assert load(tmp_path, "alerts.json")["alerts"][0]["status"] == "active"
