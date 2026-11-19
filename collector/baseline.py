"""비성수기 기준가(SPEC 3.2절): 3월 평일 출발 날짜로 노선·박수별 가격을 조회해 주 1회 갱신한다."""
from __future__ import annotations

from datetime import timedelta

from . import flights as fl
from .config import Destination, iso_kst, parse_iso


def last_checked(entry: dict) -> str:
    """마지막으로 응답(가격 또는 결과 없음)을 받은 시각."""
    return entry.get("checked_at") or entry["collected_at"]


def refresh_targets(cfg, dests: list[Destination], entries: list[dict], now) -> list[tuple[Destination, int]]:
    """갱신 대상(항목이 없거나 마지막 응답 시각이 refresh_days 를 초과). 오래된 순서로 실행당 상한까지."""
    by_key = {(e["origin"], e["destination"], e["nights"]): e for e in entries}
    limit = timedelta(days=cfg.baseline_refresh_days)
    due: list[tuple[str, int, Destination, int]] = []
    for i, d in enumerate(dests):
        for n in cfg.nights_range():
            e = by_key.get((d.origin, d.code, n))
            if e is None:
                due.append(("", i, d, n))  # 항목이 없으면 가장 먼저 조회한다
            elif now - parse_iso(last_checked(e)) > limit:
                due.append((last_checked(e), i, d, n))
    due.sort(key=lambda x: (x[0], x[1], x[3]))
    return [(d, n) for _, _, d, n in due[: cfg.baseline_max_queries]]


def refresh_baseline(state, dests: list[Destination], entries: list[dict]) -> bool:
    """entries 를 직접 갱신한다. 변경 여부를 돌려준다.

    - 조회 실패: 기존 값을 유지하고 다음 실행에서 다시 조회한다.
    - 결과 없음: 기존 값이 있으면 유지하고 checked_at 만 기록한다. 없으면 price_krw=null 항목을 만든다.
      두 경우 모두 refresh_days 동안 다시 조회하지 않는다.
    """
    cfg = state.cfg
    changed = False
    depart = cfg.baseline_depart
    for d, nights in refresh_targets(cfg, dests, entries, state.now()):
        if not state.can_query():
            break
        ret = depart + timedelta(days=nights)
        res = state.search(d.origin, d.code, depart, ret, is_baseline=True)
        key = (d.origin, d.code, nights)
        if res.status == fl.NO_RESULT or (res.status == fl.OK and res.flight is None):
            now_iso = iso_kst(state.now())
            old = next((e for e in entries if (e["origin"], e["destination"], e["nights"]) == key), None)
            if old is not None:
                old["checked_at"] = now_iso
            else:
                entries.append({
                    "origin": d.origin, "destination": d.code, "nights": nights,
                    "depart_date": depart.isoformat(), "return_date": ret.isoformat(),
                    "price_krw": None, "airlines": [], "stops": None,
                    "search_url": res.search_url, "collected_at": now_iso,
                })
            changed = True
            continue
        if res.status != fl.OK:
            continue
        new = {
            "origin": d.origin,
            "destination": d.code,
            "nights": nights,
            "depart_date": depart.isoformat(),
            "return_date": ret.isoformat(),
            "price_krw": res.flight.price_krw,
            "airlines": list(res.flight.airlines),
            "stops": res.flight.stops,
            "search_url": res.search_url,
            "collected_at": iso_kst(state.now()),
        }
        entries[:] = [e for e in entries if (e["origin"], e["destination"], e["nights"]) != key] + [new]
        changed = True
    return changed
