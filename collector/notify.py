"""텔레그램 알림(SPEC 4.2절, 5장). 발송은 주입한 http_post 로만 한다."""
from __future__ import annotations

from collections import Counter
from datetime import date
from html import escape
from typing import Callable

from .config import Config
from .http import post_json
from .judge import GOOGLE_60D, GOOGLE_LOW, OFFSEASON, OWN_HISTORY

WEEKDAYS = "월화수목금토일"
ORIGIN_NAMES = {"ICN": "인천", "GMP": "김포"}
ERROR_KIND_LABELS = {
    "bot_check": "봇 확인 페이지 응답",
    "network": "네트워크 오류",
    "parse": "응답 해석 오류",
    "hotel": "호텔 조회 오류",
    "telegram": "텔레그램 발송 오류",
    "other": "기타 오류",
}
RESUME_TEXT = "[수집 재개] 항공권 수집이 다시 정상 처리되었습니다."


def won(v: int) -> str:
    return f"{v:,}원"


def _md(d: str) -> str:
    x = date.fromisoformat(d)
    return f"{x.month}/{x.day}"


def _md_w(d: str) -> str:
    x = date.fromisoformat(d)
    return f"{x.month}/{x.day}({WEEKDAYS[x.weekday()]})"


def _duration(minutes: int | None) -> str | None:
    if minutes is None:
        return None
    h, m = divmod(minutes, 60)
    return f"{h}시간 {m}분" if h and m else f"{h}시간" if h else f"{m}분"


def _signed(p: float) -> str:
    return f"{p:+.1f}%"


def reason_lines(fare: dict) -> list[str]:
    """해당한 기준의 문구(SPEC 7장 표)."""
    j, ins = fare["judgement"], fare["insight"] or {}
    out = []
    for c in j["matched"]:
        if c == GOOGLE_LOW:
            out.append(f"Google 평소 가격 하한({won(ins['typical_low_krw'])})보다 {abs(j['pct_vs_typical_low'])}% 저렴")
        elif c == OFFSEASON:
            out.append(f"비성수기 기준가({won(j['baseline_price_krw'])}) 이하({_signed(j['pct_vs_baseline'])})")
        elif c == OWN_HISTORY:
            out.append(f"수집 이력 중앙값({won(j['own_median_krw'])})보다 {abs(j['pct_vs_own_median'])}% 저렴")
        elif c == GOOGLE_60D:
            tail = f"(60일 최저가 대비 {_signed(j['pct_vs_60d_min'])})" if j["pct_vs_60d_min"] is not None else ""
            out.append(f"최근 60일 가격 하위 10% 이하{tail}")
    return out


def format_alert(alert: dict, cfg: Config) -> str:
    """알림 1건의 메시지(parse_mode=HTML). 데이터 값은 모두 HTML 이스케이프한다."""
    f = alert["fare"]
    e = escape
    tag = "[특가·추가 인하]" if alert["kind"] == "realert" else "[특가]"
    head = f"{tag} {e(f['city_ko'])}({e(f['country_ko'])}) {won(f['price_krw'])}"
    if alert["kind"] == "realert" and alert.get("previous_alerted_price_krw") is not None:
        head += f" (직전 알림 {won(alert['previous_alerted_price_krw'])})"
    origin = f"{ORIGIN_NAMES.get(f['origin'], f['origin'])}({f['origin']})"
    lines = [
        f"<b>{head}</b>",
        f"{_md_w(f['depart_date'])} ~ {_md_w(f['return_date'])} · {f['nights']}박 · {e(origin)} 출발",
    ]
    flight = [e(", ".join(f["airlines"]) or f["airline_code"] or "항공사 정보 없음")]
    flight.append("직항" if f["stops"] == 0 else f"경유 {f['stops']}회")
    if _duration(f["duration_minutes"]):
        flight.append(_duration(f["duration_minutes"]))
    lines.append(" · ".join(flight))

    j = f["judgement"]
    lines.append(f"판정 근거({j['matched_count']}개)")
    lines += [f"- {e(x)}" for x in reason_lines(f)]
    if OFFSEASON not in j["matched"] and j["baseline_price_krw"] is not None and j["pct_vs_baseline"] is not None:
        lines.append(f"비성수기 기준가({won(j['baseline_price_krw'])}) 대비 {_signed(j['pct_vs_baseline'])}")
    lines.append(f'항공권 검색: <a href="{e(f["search_url"], quote=True)}">Google Flights</a>')

    h = alert["hotels"]
    if h["source"] == "serpapi" and h["items"]:
        lines.append(f"호텔({_md(h['check_in'])}~{_md(h['check_out'])}, 1박 요금)")
        for i, item in enumerate(h["items"][: cfg.hotel_telegram_items], 1):
            parts = [e(item["name"])]
            if item["rate_per_night_krw"] is not None:
                parts[0] += f" {won(item['rate_per_night_krw'])}"
            if item["rating"] is not None:
                parts.append(f"평점 {item['rating']}")
            if item["deal"]:
                parts.append(e(item["deal"]))
            lines.append(f"{i}. " + " · ".join(parts))
    lines.append(
        f'호텔 검색: <a href="{e(h["links"]["google_hotels"], quote=True)}">Google Hotels</a>'
        f' · <a href="{e(h["links"]["agoda"], quote=True)}">아고다</a>'
    )
    if cfg.site_url:
        lines.append(f"사이트: {e(cfg.site_url.split('#')[0])}#dest={e(f['destination'])}")
    return "\n".join(lines)


def main_cause(error_kinds: Counter) -> str:
    if not error_kinds:
        return "확인되지 않음"
    kind = error_kinds.most_common(1)[0][0]
    return ERROR_KIND_LABELS.get(kind, kind)


def format_stop_notice(threshold: int, last_success_at: str | None, error_kinds: Counter) -> str:
    last = last_success_at[:16].replace("T", " ") if last_success_at else "없음"
    return (
        f"[수집 중단] 항공권 수집이 {threshold}회 연속 실패했습니다. 마지막 성공: {last}. "
        f"주요 원인: {main_cause(error_kinds)}. 다음 실행부터 정상 수집되면 재개 안내를 발송합니다."
    )


class TelegramNotifier:
    """sendMessage 호출. 토큰·chat id 가 없거나 dry_run 이면 요청하지 않는다."""

    def __init__(
        self,
        token: str | None,
        chat_id: str | None,
        http_post: Callable[[str, dict, float], dict] = post_json,
        dry_run: bool = False,
    ):
        self.token = token or None
        self.chat_id = chat_id or None
        self._post = http_post
        self.dry_run = dry_run

    @property
    def configured(self) -> bool:
        return self.token is not None and self.chat_id is not None

    @property
    def enabled(self) -> bool:
        return self.configured and not self.dry_run

    def skip_reason(self) -> str | None:
        if self.dry_run:
            return "dry-run 실행이므로 발송하지 않음"
        if not self.configured:
            return "TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID 가 설정되지 않음"
        return None

    def send(self, text: str, html: bool = True) -> tuple[bool, str | None]:
        """(성공 여부, 오류 사유). 사유에는 토큰을 포함하지 않는다."""
        reason = self.skip_reason()
        if reason:
            return False, reason
        payload = {"chat_id": self.chat_id, "text": text, "disable_web_page_preview": True}
        if html:
            payload["parse_mode"] = "HTML"
        try:
            res = self._post(f"https://api.telegram.org/bot{self.token}/sendMessage", payload, 30)
        except Exception as e:
            return False, f"{type(e).__name__}: {str(e)[:200]}".replace(self.token, "***")
        if not isinstance(res, dict) or not res.get("ok"):
            desc = str((res or {}).get("description", "ok=false 응답"))[:200] if isinstance(res, dict) else "응답 형식 오류"
            return False, desc.replace(self.token, "***")
        return True, None
