"""AC-02, AC-03, AC-06: 자체 payload 파서."""
import copy
import json
import random

import pytest

from collector import flights as fl
from conftest import FIXTURES, make_insight, make_item, make_leg, make_payload, make_html


def read(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "name,price,low,high",
    [("ICNKIX", 356100, 290000, 445000), ("GMPCJU", 107400, 65000, 160000)],
)
def test_fixture_pages(name, price, low, high, cfg):
    page = fl.parse_html(read(f"page_{name}.html"))
    assert len(page.flights) >= 1
    best = fl.cheapest(page.flights, cfg.max_stops, cfg.max_duration_minutes)
    assert best.price_krw == price
    assert best.stops == 0 and best.airlines and best.airline_code
    assert best.depart_time and best.arrive_time and best.depart_date and best.arrive_date
    ins = page.insight
    assert (ins.typical_low_krw, ins.typical_high_krw) == (low, high)
    assert len(ins.history) == 61
    assert ins.history == sorted(ins.history)
    assert ins.history[-1] == ("2026-11-19", price)  # 마지막 점은 조회 당일의 현재가
    assert ins.current_price_krw == price


def test_html_and_payload_fixture_agree():
    for name in ("ICNKIX", "GMPCJU"):
        a = fl.parse_html(read(f"page_{name}.html"))
        b = fl.parse_payload(json.loads(read(f"payload_{name}.json")))
        assert a == b


def test_bot_check_page_is_detected():
    with pytest.raises(fl.BotCheckError):
        fl.extract_payload(read("page_verify.html"))


def test_page_without_ds1_and_without_marker():
    with pytest.raises(fl.UnexpectedPageError):
        fl.extract_payload("<html><body>동의 페이지</body></html>")


def test_broken_json_is_payload_error():
    with pytest.raises(fl.PayloadError):
        fl.extract_payload("<script class=\"ds:1\">AF_initDataCallback({data:[[1,2,, sideChannel: {}});</script>")
    with pytest.raises(fl.PayloadError):
        fl.extract_payload("<script class=\"ds:1\">nothing here</script>")


def _mutate(node, rng, depth=0):
    """임의 위치의 값을 null 로 바꾸거나 배열을 잘라낸다."""
    if not isinstance(node, list) or not node:
        return node
    i = rng.randrange(len(node))
    roll = rng.random()
    if roll < 0.25 or depth > 12:
        node[i] = None
    elif roll < 0.45:
        del node[i:]
    elif roll < 0.55:
        node[i] = rng.choice(["x", 0, -1, 1.5, {}, [], True])
    else:
        _mutate(node[i], rng, depth + 1)
    return node


@pytest.mark.parametrize("name", ["ICNKIX", "GMPCJU"])
def test_malformed_payloads_never_raise(name, cfg):
    original = json.loads(read(f"payload_{name}.json"))
    rng = random.Random(20261119)
    for _ in range(400):
        p = copy.deepcopy(original)
        for _ in range(rng.randint(1, 6)):
            _mutate(p, rng)
        page = fl.parse_payload(p)
        for f in page.flights:
            assert isinstance(f.price_krw, int) and f.price_krw > 0
            assert f.stops >= 0
        fl.cheapest(page.flights, cfg.max_stops, cfg.max_duration_minutes)


@pytest.mark.parametrize("payload", [None, [], {}, "text", 3, [None] * 10, [None, None, None, None, None, None]])
def test_degenerate_payloads(payload):
    page = fl.parse_payload(payload)
    assert page.flights == [] and page.insight is None


def test_flights_without_price_are_excluded():
    payload = make_payload([make_item(None), make_item(200000)], other=[make_item(150000), [None, None]])
    page = fl.parse_payload(payload)
    assert [f.price_krw for f in page.flights] == [200000, 150000]
    payload[2][0][1][1] = None  # 가격 배열 자체가 없음
    assert [f.price_krw for f in fl.parse_payload(payload).flights] == [150000]


def test_missing_sections_and_missing_insight():
    payload = make_payload([make_item(100000)])
    payload[3] = None
    page = fl.parse_payload(payload)
    assert len(page.flights) == 1 and page.insight is None
    assert fl.parse_payload(payload[:3]).flights[0].price_krw == 100000


def test_time_and_duration_details():
    two_legs = [make_leg("ICN", "NRT", dep=(None, 5), arr=(9, 30), minutes=140), make_leg("NRT", "HNL", dep=(11,), arr=(23, 5), minutes=420, day=(2026, 12, 18))]
    item = make_item(900000, legs=two_legs, duration=None)
    item[0] = item[0][:9]  # flight[9] 없음 -> 구간 합계를 사용
    f = fl.parse_payload(make_payload([item])).flights[0]
    assert (f.stops, f.duration_minutes) == (1, 560)
    assert (f.depart_time, f.arrive_time) == ("00:05", "23:05")
    assert (f.depart_date, f.arrive_date) == ("2026-12-17", "2026-12-18")
    f2 = fl.parse_payload(make_payload([make_item(1, duration=777)])).flights[0]
    assert f2.duration_minutes == 777 and f2.arrive_time == "17:00"


def test_filter_excludes_two_stops_and_long_flights(cfg):
    legs3 = [make_leg(), make_leg(), make_leg()]
    payload = make_payload(
        [
            make_item(100000, legs=legs3),                 # 경유 2회
            make_item(110000, duration=1501),              # 1,500분 초과
            make_item(120000, legs=[make_leg(), make_leg()], duration=1500),  # 경유 1회, 1,500분
            make_item(130000),
        ]
    )
    page = fl.parse_payload(payload)
    assert len(page.flights) == 4
    assert fl.cheapest(page.flights, cfg.max_stops, cfg.max_duration_minutes).price_krw == 120000
    unknown = make_item(90000, duration=None)
    unknown[0][2][0][11] = None  # 소요 시간을 알 수 없으면 통과
    page = fl.parse_payload(make_payload([unknown, make_item(130000)]))
    assert fl.cheapest(page.flights, 1, 1500).price_krw == 90000
    assert fl.cheapest(fl.parse_payload(make_payload([make_item(1, legs=legs3)])).flights, 1, 1500) is None


def test_insight_partial_values():
    ins = make_insight(300000, 250000, 400000)
    ins[4] = None
    ins[10] = None
    got = fl.parse_payload(make_payload([make_item(300000)], insight=ins)).insight
    assert got.typical_low_krw is None and got.typical_high_krw == 400000 and got.history == []
    assert fl.parse_payload(make_payload([], insight=[7])).insight.google_code == 7
    assert fl.parse_html(make_html(make_payload([make_item(5)]))).flights[0].price_krw == 5


def test_google_error_response_is_retryable_not_parse_error():
    """Google 의 일시 오류 응답(ErrorResponse)은 해석 오류가 아니라 재시도 대상으로 분류한다."""
    import pytest
    from collector import flights as F

    html = (
        '<html><script class="ds:1" nonce="x">AF_initDataCallback({key: \'ds:1\',  data:[13,null,'
        '[["type.googleapis.com/travel.frontend.flights.ErrorResponse",[[null,[[1,2,3]],0,"a","b"],0]]]],'
        "errorHasStatus: true,});</script></html>"
    )
    with pytest.raises(F.UnexpectedPageError):
        F.extract_payload(html)
    assert F.OTHER in F.RETRYABLE
