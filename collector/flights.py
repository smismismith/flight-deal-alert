"""Google Flights 조회: 쿼리 생성, 요청 간격·재시도·봇 확인 감지, 자체 payload 파서."""
from __future__ import annotations

import json
import random
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Callable

from .config import KST, Config

FLIGHTS_URL = "https://www.google.com/travel/flights"
BOT_CHECK_MARKER = "Verifying your request"
_DS1_RE = re.compile(r"<script[^>]*class=\"ds:1\"[^>]*>(.*?)</script>", re.DOTALL)

# 조회 결과 분류(SPEC 2.1절 6항). other 는 ds:1 도 봇 확인 문구도 없는 응답이다.
OK, NO_RESULT, BOT_CHECK, NETWORK, PARSE, OTHER = "ok", "no_result", "bot_check", "network", "parse", "other"
RETRYABLE = {BOT_CHECK, NETWORK, OTHER}


class BotCheckError(Exception):
    pass


class PayloadError(Exception):
    """ds:1 스크립트는 있으나 JSON 으로 해석하지 못한 경우."""


class UnexpectedPageError(Exception):
    """ds:1 스크립트도 봇 확인 문구도 없는 응답."""


@dataclass
class FlightOption:
    price_krw: int
    airline_code: str | None
    airlines: list[str]
    stops: int
    duration_minutes: int | None
    depart_time: str | None
    arrive_time: str | None
    depart_date: str | None
    arrive_date: str | None


@dataclass
class RawInsight:
    """payload[5] 의 값. history 는 (KST 날짜, 가격) 목록이며 날짜 오름차순이다."""

    google_code: int | None
    current_price_krw: int | None
    usual_price_krw: int | None
    typical_low_krw: int | None
    typical_high_krw: int | None
    history: list[tuple[str, int]] = field(default_factory=list)


@dataclass
class ParsedPage:
    flights: list[FlightOption]
    insight: RawInsight | None


@dataclass
class QueryResult:
    status: str
    search_url: str
    flight: FlightOption | None = None
    insight: RawInsight | None = None
    message: str = ""
    attempts: int = 0


# ---------------------------------------------------------------- 파서


def _get(obj: Any, *path: int) -> Any:
    """중첩 배열을 안전하게 읽는다. 중간 값이 배열이 아니거나 인덱스가 없으면 None."""
    for i in path:
        if not isinstance(obj, list) or i >= len(obj) or i < -len(obj):
            return None
        obj = obj[i]
    return obj


def _int(v: Any) -> int | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v == int(v):
        return int(v)
    return None


def _time(v: Any) -> str | None:
    """[시, 분]. 뒤쪽 0 은 생략되고 null 은 0 이다. 배열이 아니면 None."""
    if not isinstance(v, list):
        return None
    h = _int(_get(v, 0)) or 0
    m = _int(_get(v, 1)) or 0
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return None
    return f"{h:02d}:{m:02d}"


def _date(v: Any) -> str | None:
    y, m, d = _int(_get(v, 0)), _int(_get(v, 1)), _int(_get(v, 2))
    try:
        return date(y, m, d).isoformat()  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def extract_payload(html: str) -> Any:
    """HTML 에서 ds:1 스크립트의 data 값을 추출한다.

    BotCheckError: ds:1 이 없고 봇 확인 문구가 있음. UnexpectedPageError: 둘 다 없음.
    PayloadError: ds:1 은 있으나 해석 실패.
    """
    m = _DS1_RE.search(html or "")
    if not m:
        if BOT_CHECK_MARKER in (html or ""):
            raise BotCheckError("봇 확인 페이지 응답")
        raise UnexpectedPageError("ds:1 스크립트가 없는 응답")
    js = m.group(1)
    # Google 이 일시적인 서버 오류를 반환한 경우(ErrorResponse). 같은 조회를 다시 요청하면 대개 성공하므로
    # 재시도 대상(other)으로 분류한다.
    if "errorHasStatus: true" in js or "flights.ErrorResponse" in js:
        raise UnexpectedPageError("Google 오류 응답(ErrorResponse)")
    try:
        return json.loads(js.split("data:", 1)[1].rsplit(",", 1)[0])
    except (IndexError, ValueError) as e:
        raise PayloadError(f"ds:1 JSON 해석 실패: {type(e).__name__}") from e


def _parse_flight(item: Any) -> FlightOption | None:
    flight = _get(item, 0)
    price = _int(_get(item, 1, 0, 1))
    if not isinstance(flight, list) or price is None or price <= 0:
        return None
    raw_legs = _get(flight, 2)
    if not isinstance(raw_legs, list) or not raw_legs:
        return None
    legs = [x if isinstance(x, list) else [] for x in raw_legs]
    duration = _int(_get(flight, 9))
    if duration is None:
        parts = [_int(_get(leg, 11)) for leg in legs]
        duration = sum(parts) if all(p is not None for p in parts) else None  # type: ignore[arg-type]
    names = _get(flight, 1)
    code = _get(flight, 0)
    return FlightOption(
        price_krw=price,
        airline_code=code if isinstance(code, str) and code else None,
        airlines=[n for n in names if isinstance(n, str) and n] if isinstance(names, list) else [],
        stops=len(legs) - 1,
        duration_minutes=duration if duration is None or duration >= 0 else None,
        depart_time=_time(_get(legs[0], 8)),
        arrive_time=_time(_get(legs[-1], 10)),
        depart_date=_date(_get(legs[0], 20)),
        arrive_date=_date(_get(legs[-1], 21)),
    )


def _parse_insight(raw: Any) -> RawInsight | None:
    if not isinstance(raw, list):
        return None
    points: dict[str, int] = {}
    for p in _get(raw, 10, 0) or []:
        ts, price = _get(p, 0), _int(_get(p, 1))
        if not isinstance(ts, (int, float)) or isinstance(ts, bool) or price is None or price < 0:
            continue
        try:
            day = datetime.fromtimestamp(ts / 1000, KST).date().isoformat()
        except (OverflowError, OSError, ValueError):
            continue
        points[day] = price
    pos = lambda v: v if v is not None and v >= 0 else None  # noqa: E731
    return RawInsight(
        google_code=_int(_get(raw, 0)),
        current_price_krw=pos(_int(_get(raw, 1, 1))),
        usual_price_krw=pos(_int(_get(raw, 2, 1))),
        typical_low_krw=pos(_int(_get(raw, 4, 1))),
        typical_high_krw=pos(_int(_get(raw, 5, 1))),
        history=sorted(points.items()),
    )


def parse_payload(payload: Any) -> ParsedPage:
    """payload 에서 가격이 있는 항공편(best + other)과 가격 정보를 추출한다. 예외를 내지 않는다."""
    flights: list[FlightOption] = []
    for section in (2, 3):
        items = _get(payload, section, 0)
        if not isinstance(items, list):
            continue
        for item in items:
            f = _parse_flight(item)
            if f is not None:
                flights.append(f)
    return ParsedPage(flights=flights, insight=_parse_insight(_get(payload, 5)))


def parse_html(html: str) -> ParsedPage:
    return parse_payload(extract_payload(html))


def cheapest(flights: list[FlightOption], max_stops: int, max_duration_minutes: int) -> FlightOption | None:
    """필터(경유 횟수, 가는 편 소요 시간)를 통과한 항공편 중 최저가. 소요 시간을 모르면 통과시킨다."""
    ok = [
        f
        for f in flights
        if f.stops <= max_stops and (f.duration_minutes is None or f.duration_minutes <= max_duration_minutes)
    ]
    return min(ok, key=lambda f: f.price_krw) if ok else None


# ---------------------------------------------------------------- 조회


def build_query(cfg: Config, origin: str, destination: str, depart: date, ret: date):
    from fast_flights import FlightQuery, Passengers, create_query

    return create_query(
        flights=[
            FlightQuery(date=depart.isoformat(), from_airport=origin, to_airport=destination),
            FlightQuery(date=ret.isoformat(), from_airport=destination, to_airport=origin),
        ],
        trip="round-trip",
        passengers=Passengers(adults=cfg.adults),
        language=cfg.language,
        currency=cfg.currency,
    )


def default_fetch(query, timeout: float) -> str:
    """fast_flights.fetch_flights_html 과 같은 요청에 시간 제한과 HTTP 상태 확인을 더한 것."""
    from primp import Client

    client = Client(
        impersonate="chrome_145", impersonate_os="macos", referer=True, cookie_store=True, timeout=timeout
    )
    res = client.get(FLIGHTS_URL, params=query.params())
    text = res.text
    status = getattr(res, "status_code", 200)
    if status >= 400 and BOT_CHECK_MARKER not in text:
        raise ConnectionError(f"HTTP {status}")
    return text


class FlightClient:
    """요청 간격과 재시도를 관리한다. fetch, sleep, clock, rng 를 주입해 네트워크 없이 테스트한다."""

    def __init__(
        self,
        cfg: Config,
        fetch: Callable[[Any, float], str] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        rng: Callable[[], float] = random.random,
        max_requests: int | None = None,
    ):
        self.cfg = cfg
        self._fetch = fetch or default_fetch
        self._sleep = sleep
        self._clock = clock
        self._rng = rng
        self.max_requests = max_requests
        self._last_start: float | None = None
        self.requests = 0
        self.bot_checks = 0
        self.retries = 0

    def has_budget(self) -> bool:
        return self.max_requests is None or self.requests < self.max_requests

    def _pace(self) -> None:
        if self._last_start is not None:
            gap = self.cfg.min_interval_seconds + self._rng() * self.cfg.jitter_seconds
            wait = self._last_start + gap - self._clock()
            if wait > 0:
                self._sleep(wait)
        self._last_start = self._clock()

    def _once(self, query) -> tuple[str, ParsedPage | None, str]:
        self._pace()
        self.requests += 1
        try:
            html = self._fetch(query, self.cfg.request_timeout_seconds)
        except Exception as e:  # 시간 초과·연결 오류·HTTP 오류
            name = type(e).__name__
            if "timeout" in name.lower() or "timed out" in str(e).lower():
                return NETWORK, None, f"응답 시간 초과({int(self.cfg.request_timeout_seconds)}초)"
            return NETWORK, None, f"네트워크 오류({name}: {str(e)[:120]})"
        try:
            return OK, parse_payload(extract_payload(html)), ""
        except BotCheckError:
            self.bot_checks += 1
            return BOT_CHECK, None, "봇 확인 페이지 응답"
        except PayloadError as e:
            return PARSE, None, str(e)
        except UnexpectedPageError as e:
            return OTHER, None, f"{e}(길이 {len(html or '')})"

    def search(self, origin: str, destination: str, depart: date, ret: date) -> QueryResult:
        """왕복 1건을 조회한다. 봇 확인·네트워크 오류는 설정한 대기 시간 후 재시도한다."""
        query = build_query(self.cfg, origin, destination, depart, ret)
        url = query.url()
        kind, page, msg = self._once(query)
        attempts = 1
        for backoff in self.cfg.retry_backoff_seconds:
            if kind not in RETRYABLE or not self.has_budget():
                break
            self._sleep(backoff)
            self.retries += 1
            attempts += 1
            kind, page, msg = self._once(query)
        if kind != OK or page is None:
            if attempts > 1:
                msg = f"{msg}(재시도 {attempts - 1}회 후 실패)"
            return QueryResult(status=kind, search_url=url, message=msg, attempts=attempts)
        best = cheapest(page.flights, self.cfg.max_stops, self.cfg.max_duration_minutes)
        if best is None:
            return QueryResult(status=NO_RESULT, search_url=url, insight=page.insight, attempts=attempts)
        return QueryResult(status=OK, search_url=url, flight=best, insight=page.insight, attempts=attempts)
