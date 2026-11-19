"""저렴함 판정(SPEC 3장). 비교는 정수 연산으로 한다."""
from __future__ import annotations

from .config import Combo, Config, Destination
from .flights import QueryResult, RawInsight

GOOGLE_LOW, OFFSEASON, OWN_HISTORY, GOOGLE_60D = "google_low", "offseason", "own_history", "google_60d"
CRITERIA = [GOOGLE_LOW, OFFSEASON, OWN_HISTORY, GOOGLE_60D]


def pct(price: int, ref: int | None) -> float | None:
    """(가격 - 비교값) / 비교값 * 100, 소수 첫째 자리. 음수이면 비교값보다 저렴하다."""
    if not ref:
        return None
    return round((price - ref) / ref * 100, 1)


def median_int(values: list[int]) -> int | None:
    """중앙값(원 단위 정수). 개수가 짝수이면 가운데 두 값의 평균에서 소수점 이하를 버린다."""
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) // 2


def level_of(price: int, low: int | None, high: int | None) -> str | None:
    if low is None or high is None:
        return None
    return "low" if price < low else "high" if price > high else "typical"


def percentile_nearest_rank(values: list[int], percentile: int) -> int:
    """오름차순 정렬 후 ceil(percentile/100 * n) - 1 번째(0부터) 값."""
    s = sorted(values)
    idx = max((percentile * len(s) + 99) // 100 - 1, 0)
    return s[idx]


def build_insight(raw: RawInsight | None, price: int, cfg: Config) -> dict | None:
    """Google 가격 정보를 스키마의 insight 형식으로 만든다. 이력의 마지막 점(조회 당일 값)은 통계에서 제외한다."""
    if raw is None:
        return None
    past = [p for _, p in raw.history[:-1]]
    return {
        "google_code": raw.google_code,
        "current_price_krw": raw.current_price_krw,
        "usual_price_krw": raw.usual_price_krw,
        "typical_low_krw": raw.typical_low_krw,
        "typical_high_krw": raw.typical_high_krw,
        "level": level_of(price, raw.typical_low_krw, raw.typical_high_krw),
        "history_min_krw": min(past) if past else None,
        "history_p10_krw": percentile_nearest_rank(past, cfg.g60_percentile) if len(past) >= cfg.g60_min_points else None,
        "history_count": len(raw.history),
        "history": [{"date": d, "price_krw": p} for d, p in raw.history],
    }


def judge(
    price: int,
    insight: dict | None,
    baseline_price: int | None,
    own_rep_prices: list[int],
    cfg: Config,
) -> dict:
    """기준 a~d 를 평가한다. own_rep_prices 는 이번 실행을 제외한 과거 rep_price_krw(null 제외)이다."""
    evaluated: list[str] = []
    matched: list[str] = []

    low = insight["typical_low_krw"] if insight else None
    high = insight["typical_high_krw"] if insight else None
    if low is not None and high is not None:
        evaluated.append(GOOGLE_LOW)
        if price < low:
            matched.append(GOOGLE_LOW)

    if baseline_price is not None:
        evaluated.append(OFFSEASON)
        if price <= baseline_price:
            matched.append(OFFSEASON)

    samples = len(own_rep_prices)
    median = None
    if samples >= cfg.own_min_samples:
        median = median_int(own_rep_prices)
        evaluated.append(OWN_HISTORY)
        if price * 100 <= median * (100 - cfg.own_drop_pct):
            matched.append(OWN_HISTORY)

    p10 = insight["history_p10_krw"] if insight else None
    if p10 is not None:
        evaluated.append(GOOGLE_60D)
        if price <= p10:
            matched.append(GOOGLE_60D)

    return {
        "evaluated": evaluated,
        "matched": matched,
        "matched_count": len(matched),
        "is_deal": len(matched) >= cfg.min_criteria,
        "baseline_price_krw": baseline_price,
        "pct_vs_baseline": pct(price, baseline_price),
        "own_median_krw": median,
        "own_samples": samples,
        "pct_vs_own_median": pct(price, median),
        "pct_vs_typical_low": pct(price, low) if GOOGLE_LOW in evaluated else None,
        "pct_vs_60d_min": pct(price, insight["history_min_krw"]) if insight else None,
    }


def needs_realert(price: int, last_alerted: int, drop_pct: int) -> bool:
    """직전 발송 가격보다 drop_pct% 이상 낮으면 True (P x 100 <= L x (100 - drop_pct))."""
    return price * 100 <= last_alerted * (100 - drop_pct)


def build_fare(
    dest: Destination,
    combo: Combo,
    result: QueryResult,
    collected_at: str,
    is_representative: bool,
    baseline_price: int | None,
    own_rep_prices: list[int],
    cfg: Config,
) -> dict:
    """조회 결과 1건을 스키마의 fare 기록으로 만든다(판정 포함)."""
    f = result.flight
    assert f is not None
    insight = build_insight(result.insight, f.price_krw, cfg)
    return {
        **dest.place(),
        "depart_date": combo.depart.isoformat(),
        "return_date": combo.return_date.isoformat(),
        "nights": combo.nights,
        "is_representative": is_representative,
        "price_krw": f.price_krw,
        "airline_code": f.airline_code,
        "airlines": list(f.airlines),
        "stops": f.stops,
        "duration_minutes": f.duration_minutes,
        "depart_time": f.depart_time,
        "arrive_time": f.arrive_time,
        "arrive_date": f.arrive_date,
        "search_url": result.search_url,
        "insight": insight,
        "judgement": judge(f.price_krw, insight, baseline_price, own_rep_prices, cfg),
        "collected_at": collected_at,
    }


def to_combo(fare: dict) -> dict:
    """히트맵용 축약 기록."""
    return {
        "depart_date": fare["depart_date"],
        "return_date": fare["return_date"],
        "nights": fare["nights"],
        "is_representative": fare["is_representative"],
        "price_krw": fare["price_krw"],
        "airlines": fare["airlines"],
        "stops": fare["stops"],
        "level": fare["insight"]["level"] if fare["insight"] else None,
        "matched": fare["judgement"]["matched"],
        "is_deal": fare["judgement"]["is_deal"],
        "search_url": fare["search_url"],
        "collected_at": fare["collected_at"],
    }


def pick_best_and_deal(fares: list[dict]) -> tuple[dict | None, dict | None]:
    """best = 최저가 기록, deal = is_deal 인 기록 중 최저가."""
    if not fares:
        return None, None
    key = lambda f: (f["price_krw"], f["depart_date"], f["nights"])  # noqa: E731
    best = min(fares, key=key)
    deals = [f for f in fares if f["judgement"]["is_deal"]]
    return best, (min(deals, key=key) if deals else None)
