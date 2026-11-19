"""AC-04, AC-05: 요청 간격, 봇 확인 감지, 재시도."""
from datetime import date

from collector import flights as fl
from conftest import BOT_HTML, FakeTime, make_html, make_payload, simple_html

D1, D2 = date(2026, 12, 17), date(2026, 12, 20)


def client_with(cfg, responses, **kw):
    t = FakeTime()
    seq = list(responses)
    starts = []

    def fetch(query, timeout):
        starts.append(t.t)
        assert timeout == 30
        out = seq.pop(0)
        if isinstance(out, Exception):
            raise out
        return out

    return fl.FlightClient(cfg, fetch, t.sleep, t.clock, kw.pop("rng", lambda: 0.0), **kw), t, starts


def test_success_returns_cheapest_and_url(cfg):
    c, t, _ = client_with(cfg, [simple_html(250000, 200000, 300000)])
    r = c.search("ICN", "KIX", D1, D2)
    assert r.status == fl.OK and r.flight.price_krw == 250000 and r.attempts == 1
    assert r.search_url.startswith("https://www.google.com/travel/flights/search?tfs=")
    assert "hl=ko" in r.search_url and "curr=KRW" in r.search_url
    assert (c.requests, c.bot_checks, c.retries) == (1, 0, 0)
    assert t.sleeps == []


def test_bot_check_then_success(cfg):
    c, t, _ = client_with(cfg, [BOT_HTML, simple_html(250000)])
    r = c.search("ICN", "KIX", D1, D2)
    assert r.status == fl.OK and r.attempts == 2
    assert (c.bot_checks, c.retries, c.requests) == (1, 1, 2)
    assert t.sleeps[0] == 20


def test_bot_check_backoff_20_then_60_then_fail(cfg):
    c, t, starts = client_with(cfg, [BOT_HTML, BOT_HTML, BOT_HTML])
    r = c.search("ICN", "KIX", D1, D2)
    assert r.status == fl.BOT_CHECK and r.attempts == 3
    assert "재시도 2회 후 실패" in r.message
    assert [s for s in t.sleeps if s >= 20] == [20, 60]
    assert (c.bot_checks, c.retries, c.requests) == (3, 2, 3)
    assert starts == [0, 20, 80]


def test_network_error_is_retried_and_timeout_message(cfg):
    c, _, _ = client_with(cfg, [TimeoutError("timed out"), ConnectionError("reset"), simple_html(1000)])
    assert c.search("ICN", "KIX", D1, D2).status == fl.OK
    assert c.retries == 2 and c.bot_checks == 0
    c, _, _ = client_with(cfg, [TimeoutError("timed out")] * 3)
    r = c.search("ICN", "KIX", D1, D2)
    assert r.status == fl.NETWORK and "시간 초과(30초)" in r.message


def test_parse_error_is_not_retried(cfg):
    c, t, _ = client_with(cfg, ['<script class="ds:1">data:[[[, x</script>'])
    r = c.search("ICN", "KIX", D1, D2)
    assert r.status == fl.PARSE and c.retries == 0 and c.requests == 1 and t.sleeps == []


def test_no_result_when_nothing_passes_filter(cfg):
    c, _, _ = client_with(cfg, [make_html(make_payload([]))])
    r = c.search("ICN", "KIX", D1, D2)
    assert r.status == fl.NO_RESULT and r.flight is None


def test_spacing_between_request_starts_is_at_least_min_interval(cfg):
    pages = [simple_html(1000)] * 3 + [BOT_HTML, simple_html(1000)] + [simple_html(1000)]
    c, t, starts = client_with(cfg, pages, rng=lambda: 0.25)
    for _ in range(5):
        c.search("ICN", "KIX", D1, D2)
    assert len(starts) == 6
    gaps = [b - a for a, b in zip(starts, starts[1:])]
    assert all(g >= cfg.min_interval_seconds for g in gaps)
    assert gaps[0] == 6 + 0.25 * cfg.jitter_seconds
    assert gaps[3] == 20  # 재시도 대기는 간격 조건을 이미 만족한다


def test_request_budget_stops_retries(cfg):
    c, _, _ = client_with(cfg, [BOT_HTML, BOT_HTML], max_requests=2)
    r = c.search("ICN", "KIX", D1, D2)
    assert r.status == fl.BOT_CHECK and c.requests == 2 and not c.has_budget()
