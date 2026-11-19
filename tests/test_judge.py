"""AC-07, AC-08, AC-09, AC-11(계산식): 판정 기준 경계값."""
from collector.flights import RawInsight
from collector.judge import (
    build_insight, judge, level_of, median_int, needs_realert, percentile_nearest_rank, pct,
)


def insight(price, low=None, high=None, history=()):
    return RawInsight(3, price, price, low, high, list(history))


def hist(prices):
    return [(f"2026-{9 + i // 30:02d}-{1 + i % 30:02d}", p) for i, p in enumerate(prices)]


def run(cfg, price, raw=None, baseline=None, own=()):
    ins = build_insight(raw, price, cfg)
    return judge(price, ins, baseline, list(own), cfg), ins


# ---- 기준 a: google_low
def test_google_low_boundary(cfg):
    j, ins = run(cfg, 290000, insight(290000, 290000, 445000))
    assert "google_low" in j["evaluated"] and "google_low" not in j["matched"]
    assert ins["level"] == "typical"
    j, ins = run(cfg, 289999, insight(289999, 290000, 445000))
    assert "google_low" in j["matched"] and ins["level"] == "low"
    assert j["pct_vs_typical_low"] == -0.0 or j["pct_vs_typical_low"] == 0.0


def test_level_high_and_typical():
    assert level_of(445000, 290000, 445000) == "typical"
    assert level_of(445001, 290000, 445000) == "high"
    assert level_of(100, None, 445000) is None


def test_google_low_not_evaluated_without_range(cfg):
    j, ins = run(cfg, 100000, insight(100000, 290000, None))
    assert "google_low" not in j["evaluated"] and ins["level"] is None and j["pct_vs_typical_low"] is None


# ---- 기준 b: offseason
def test_offseason_boundary(cfg):
    j, _ = run(cfg, 224000, baseline=224000)
    assert j["matched"] == ["offseason"] and j["pct_vs_baseline"] == 0.0
    j, _ = run(cfg, 224001, baseline=224000)
    assert j["evaluated"] == ["offseason"] and j["matched"] == []
    j, _ = run(cfg, 224000)
    assert j["evaluated"] == [] and j["baseline_price_krw"] is None and j["pct_vs_baseline"] is None


# ---- 기준 c: own_history
def test_own_history_boundary(cfg):
    own = [400000] * 9
    j, _ = run(cfg, 340000, own=own)  # 정확히 중앙값 x 0.85
    assert j["matched"] == ["own_history"]
    assert (j["own_median_krw"], j["own_samples"], j["pct_vs_own_median"]) == (400000, 9, -15.0)
    j, _ = run(cfg, 340001, own=own)
    assert j["evaluated"] == ["own_history"] and j["matched"] == []


def test_own_history_needs_nine_samples(cfg):
    j, _ = run(cfg, 1, own=[400000] * 8)
    assert j["evaluated"] == [] and j["own_median_krw"] is None and j["own_samples"] == 8
    assert j["pct_vs_own_median"] is None


def test_own_history_uses_median_not_mean(cfg):
    own = [100000] * 4 + [400000] * 5  # 중앙값 400,000 / 평균 약 266,667
    j, _ = run(cfg, 340000, own=own)
    assert j["own_median_krw"] == 400000 and "own_history" in j["matched"]
    assert median_int([1, 2, 3, 10]) == 2 and median_int([5]) == 5 and median_int([]) is None


# ---- 기준 d: google_60d
def test_google_60d_boundary_and_last_point_excluded(cfg):
    past = list(range(300000, 360000, 1000))  # 60개: 300,000 ~ 359,000
    raw = insight(305000, history=hist(past + [100]))  # 마지막 점(100)은 계산에서 제외
    j, ins = run(cfg, 305000, raw)
    # n=60 -> ceil(6.0)-1 = 5번째(0부터) = 305,000
    assert ins["history_p10_krw"] == 305000 and ins["history_min_krw"] == 300000 and ins["history_count"] == 61
    assert j["matched"] == ["google_60d"] and j["pct_vs_60d_min"] == 1.7
    j, _ = run(cfg, 305001, raw)
    assert j["evaluated"] == ["google_60d"] and j["matched"] == []


def test_google_60d_needs_30_points_after_excluding_last(cfg):
    j, ins = run(cfg, 1, insight(1, history=hist([500000] * 29 + [1])))
    assert "google_60d" not in j["evaluated"] and ins["history_p10_krw"] is None
    assert ins["history_min_krw"] == 500000
    j, ins = run(cfg, 1, insight(1, history=hist([500000] * 30 + [1])))
    assert j["matched"] == ["google_60d"] and ins["history_p10_krw"] == 500000


def test_percentile_nearest_rank():
    assert percentile_nearest_rank(list(range(1, 31)), 10) == 3    # ceil(3.0)-1 = 2
    assert percentile_nearest_rank(list(range(1, 32)), 10) == 4    # ceil(3.1)-1 = 3
    assert percentile_nearest_rank([7], 10) == 7


# ---- 조합
def test_deal_requires_two_criteria(cfg):
    raw = insight(280000, 290000, 445000)
    j, _ = run(cfg, 280000, raw)
    assert j["matched"] == ["google_low"] and j["is_deal"] is False
    j, _ = run(cfg, 280000, raw, baseline=280000)
    assert j["matched"] == ["google_low", "offseason"] and j["matched_count"] == 2 and j["is_deal"] is True
    assert set(j["matched"]) <= set(j["evaluated"])


def test_a_plus_d_is_deal_and_all_four(cfg):
    raw = insight(250000, 290000, 445000, hist([400000] * 60 + [250000]))
    j, _ = run(cfg, 250000, raw)
    assert j["matched"] == ["google_low", "google_60d"] and j["is_deal"]
    j, _ = run(cfg, 250000, raw, baseline=260000, own=[400000] * 10)
    assert j["matched_count"] == 4 and j["evaluated"] == ["google_low", "offseason", "own_history", "google_60d"]


def test_no_insight_means_a_and_d_not_evaluated(cfg):
    j, ins = run(cfg, 100000, None, baseline=100000, own=[400000] * 9)
    assert ins is None
    assert j["evaluated"] == ["offseason", "own_history"] and j["is_deal"]
    assert j["pct_vs_typical_low"] is None and j["pct_vs_60d_min"] is None


def test_sample_examples_from_spec(cfg):
    """SPEC 3.3절: DAD 338,000원(3개 해당), FUK 219,000원(2개 해당)."""
    raw = insight(338000, 365000, 560000, hist([381600] * 6 + [375500] + [430000] * 53 + [338000]))
    j, _ = run(cfg, 338000, raw, baseline=299700, own=[423000] * 42)
    assert j["matched"] == ["google_low", "own_history", "google_60d"]
    assert (j["pct_vs_baseline"], j["pct_vs_own_median"], j["pct_vs_typical_low"], j["pct_vs_60d_min"]) == (12.8, -20.1, -7.4, -10.0)
    raw = insight(219000, 230000, 330000, hist([200000] * 60 + [219000]))
    j, _ = run(cfg, 219000, raw, baseline=224000, own=[255300] * 42)
    assert j["matched"] == ["google_low", "offseason"] and j["pct_vs_own_median"] == -14.2


def test_pct_and_realert_rule(cfg):
    assert pct(90, 100) == -10.0 and pct(100, None) is None and pct(100, 0) is None
    assert needs_realert(341050, 359000, cfg.realert_drop_pct) is True    # 정확히 5% 낮음
    assert needs_realert(341100, 359000, cfg.realert_drop_pct) is False
    assert needs_realert(341051, 359000, cfg.realert_drop_pct) is False
