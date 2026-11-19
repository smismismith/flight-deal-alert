"""테스트 공용 도구: 가짜 시계, 가짜 Google Flights 응답, 모의 실행 환경. 실제 네트워크는 사용하지 않는다."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from collector.config import KST, load_config
from collector.main import Deps

FIXTURES = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def cfg():
    return load_config()


class FakeTime:
    """sleep 호출만큼 시각이 이동하는 시계."""

    def __init__(self, start: datetime | None = None):
        self.t = 0.0
        self.start = start or datetime(2026, 11, 19, 8, 0, 0, tzinfo=KST)
        self.sleeps: list[float] = []

    def sleep(self, s: float) -> None:
        self.sleeps.append(s)
        self.t += s

    def clock(self) -> float:
        return self.t

    def now(self) -> datetime:
        return self.start + timedelta(seconds=int(self.t))


def ts_ms(day: datetime) -> int:
    return int(day.timestamp() * 1000)


def make_history(prices: list[int], last_day: datetime | None = None) -> list[list[int]]:
    """마지막 점이 last_day(KST 자정)인 일별 가격 이력."""
    last_day = last_day or datetime(2026, 11, 19, tzinfo=KST)
    n = len(prices)
    return [[ts_ms(last_day - timedelta(days=n - 1 - i)), p] for i, p in enumerate(prices)]


def make_leg(frm="ICN", to="KIX", dep=(15, 20), arr=(17,), minutes=100, day=(2026, 12, 17)):
    leg = [None] * 22
    leg[3], leg[6], leg[8], leg[10], leg[11], leg[20], leg[21] = frm, to, list(dep), list(arr), minutes, list(day), list(day)
    return leg


def make_item(price, code="RS", names=("에어서울",), legs=None, duration=100):
    legs = legs or [make_leg()]
    flight = [code, list(names), legs, "ICN", [2026, 12, 17], [15, 20], "KIX", [2026, 12, 17], [17], duration]
    return [flight, [[None, price] if price is not None else [], "token"]]


def make_insight(current, low, high, history=None, code=3):
    if history is None:
        history = make_history([current + 50000] * 60 + [current])
    return [code, [None, current], [None, current], [None, 0], [None, low], [None, high], 1, None, None, None, [history]]


def make_payload(items, other=None, insight=None):
    return [None, None, [items], [other or []], None, insight]


def make_html(payload) -> str:
    return (
        "<html><body><script class=\"ds:1\">AF_initDataCallback({key: 'ds:1', hash: '9', data:"
        + json.dumps(payload, ensure_ascii=False)
        + ", sideChannel: {}});</script></body></html>"
    )


def simple_html(price, low=None, high=None, history=None, **item_kw) -> str:
    insight = make_insight(price, low, high, history) if low is not None else None
    return make_html(make_payload([make_item(price, **item_kw)], insight=insight))


BOT_HTML = (FIXTURES / "page_verify.html").read_text(encoding="utf-8")


def query_key(query) -> tuple[str, str, str, str]:
    a, b = query.flight_data[0], query.flight_data[1]
    return a.from_airport.airport, a.to_airport.airport, a.date, b.date


class Sim:
    """모의 실행 환경. responder(origin, dest, depart, ret) 가 HTML 문자열을 돌려주거나 예외를 낸다."""

    def __init__(self, responder, env=None, start=None):
        self.time = FakeTime(start)
        self.responder = responder
        self.fetched: list[tuple[str, str, str, str]] = []
        self.fetch_times: list[float] = []
        self.posts: list[tuple[str, dict]] = []
        self.gets: list[tuple[str, dict]] = []
        self.post_response = {"ok": True}
        self.get_response = {"properties": []}
        self.lines: list[str] = []
        self.env = dict(env or {})

    def fetch(self, query, timeout):
        key = query_key(query)
        self.fetched.append(key)
        self.fetch_times.append(self.time.t)
        out = self.responder(*key)
        if isinstance(out, Exception):
            raise out
        return out

    def http_post(self, url, payload, timeout):
        self.posts.append((url, payload))
        if isinstance(self.post_response, Exception):
            raise self.post_response
        return self.post_response

    def http_get(self, url, params, timeout):
        self.gets.append((url, params))
        if isinstance(self.get_response, Exception):
            raise self.get_response
        return self.get_response

    def deps(self) -> Deps:
        return Deps(
            fetch=self.fetch,
            sleep=self.time.sleep,
            clock=self.time.clock,
            rng=lambda: 0.5,
            now=self.time.now,
            http_get=self.http_get,
            http_post=self.http_post,
            env=self.env,
            out=self.lines.append,
        )
