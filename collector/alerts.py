"""알림 상태 관리(SPEC 4.1절). alerts 목록은 최신순이며 이 모듈의 함수가 직접 수정한다."""
from __future__ import annotations

from dataclasses import dataclass

from .config import Destination
from .hotels import links_only, stay_dates
from .judge import needs_realert


@dataclass
class Outcome:
    """목적지 1개의 이번 실행 결과. refreshed=False 이면 조회 실패(stale) 또는 미조회이다."""

    refreshed: bool
    deal: dict | None = None
    deal_carried: bool = False  # deal 이 이번 실행에서 조회하지 못한 조합의 이전 값이면 True


def last_sent_price(alerts: list[dict], code: str) -> int | None:
    """직전 발송 가격 L: sent=true 인 가장 최근 알림의 가격. 상태와 관계없다."""
    for a in alerts:
        if a["destination"] == code and a["notification"]["sent"]:
            return a["alerted_price_krw"]
    return None


def active_alert(alerts: list[dict], code: str) -> dict | None:
    for a in alerts:
        if a["destination"] == code and a["status"] == "active":
            return a
    return None


def _close(alert: dict, status: str, now_iso: str) -> None:
    alert.update(status=status, ended_at=now_iso, current_fare=None, current_checked_at=now_iso)


def _new_alert(dest: Destination, fare: dict, kind: str, previous: int | None, run_id: str, now_iso: str) -> dict:
    return {
        "id": f"{dest.code}-{run_id}",
        **dest.place(),
        "status": "active",
        "kind": kind,
        "created_at": now_iso,
        "ended_at": None,
        "alerted_price_krw": fare["price_krw"],
        "previous_alerted_price_krw": previous,
        "fare": fare,
        "current_fare": fare,
        "current_checked_at": now_iso,
        "notification": {"channel": "telegram", "sent": False, "sent_at": None, "attempts": 0, "error": None},
        "hotels": links_only(dest.hotel_query, fare),
    }


def _retry_unsent(alert: dict, dest: Destination, fare: dict, now_iso: str) -> None:
    """발송하지 못한 알림은 같은 레코드의 fare 를 갱신해 다시 발송한다."""
    alert.update(
        status="active",
        ended_at=None,
        alerted_price_krw=fare["price_krw"],
        fare=fare,
        current_fare=fare,
        current_checked_at=now_iso,
    )
    h = alert["hotels"]
    if (h["check_in"], h["check_out"]) != stay_dates(fare)[:2]:
        alert["hotels"] = links_only(dest.hotel_query, fare)


def update_alerts(
    alerts: list[dict],
    outcomes: dict[str, Outcome],
    dests: dict[str, Destination],
    run_id: str,
    now_iso: str,
    realert_drop_pct: int,
) -> list[dict]:
    """목적지별 결과를 alerts 에 반영하고, 이번 실행에서 발송할 알림 레코드 목록을 돌려준다."""
    to_send: list[dict] = []
    for code, out in outcomes.items():
        if not out.refreshed:
            continue  # 조회 실패 목적지는 상태를 유지한다
        dest = dests[code]
        active = active_alert(alerts, code)
        if out.deal is None:
            if active is not None:
                _close(active, "ended", now_iso)
            continue
        fare = out.deal
        if out.deal_carried:
            # 특가 조합을 이번 실행에서 조회하지 못했다: 상태를 유지하고, 미발송 알림만 다시 발송한다
            if active is not None and not active["notification"]["sent"]:
                _retry_unsent(active, dest, fare, now_iso)
                to_send.append(active)
            continue
        if active is not None and not active["notification"]["sent"]:
            _retry_unsent(active, dest, fare, now_iso)
            to_send.append(active)
            continue
        last = last_sent_price(alerts, code)
        if last is None:
            kind, create = "new", True
        elif needs_realert(fare["price_krw"], last, realert_drop_pct):
            kind, create = "realert", True
        else:
            kind, create = "", False
        if create:
            if active is not None:
                _close(active, "replaced", now_iso)
            existing = next((a for a in alerts if a["id"] == f"{code}-{run_id}"), None)
            if existing is not None:  # 같은 run_id 로 다시 실행한 경우 레코드를 재사용한다
                alerts.remove(existing)
            alert = _new_alert(dest, fare, kind, last, run_id, now_iso)
            alerts.insert(0, alert)
            to_send.append(alert)
            continue
        # 5% 미만 하락: 발송하지 않고 현재 가격만 갱신한다. ended 였다면 active 로 되돌린다.
        target = active or next((a for a in alerts if a["destination"] == code), None)
        if target is None:
            continue
        if not target["notification"]["sent"]:
            _retry_unsent(target, dest, fare, now_iso)
            to_send.append(target)
        else:
            target.update(status="active", ended_at=None, current_fare=fare, current_checked_at=now_iso)
    alerts.sort(key=lambda a: a["created_at"], reverse=True)
    return to_send


def trim_alerts(alerts: list[dict], keep: int) -> list[dict]:
    """최신순 keep 건만 남긴다. active 알림은 한도를 넘어도 유지한다."""
    out = []
    for i, a in enumerate(alerts):
        if i < keep or a["status"] == "active":
            out.append(a)
    while len(out) > keep and any(a["status"] != "active" for a in out):
        for i in range(len(out) - 1, -1, -1):
            if out[i]["status"] != "active":
                del out[i]
                break
    return out
