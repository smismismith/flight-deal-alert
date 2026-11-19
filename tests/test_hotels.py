"""AC-15: 호텔 조회(모의 HTTP)."""
import dataclasses

from collector.hotels import HotelFinder, build_links, links_only, stay_dates

FARE = {"depart_date": "2026-12-21", "arrive_date": "2026-12-22", "return_date": "2026-12-25"}
NOW = "2026-11-19T09:00:00+09:00"


def prop(name, night, total=None, rating=4.2, **extra):
    return {
        "name": name,
        "rate_per_night": {"lowest": f"₩{night}", "extracted_lowest": night},
        "total_rate": {"extracted_lowest": total or night * 3},
        "overall_rating": rating,
        "link": f"https://hotel.example/{name}",
        **extra,
    }


class Api:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, params, timeout):
        self.calls.append((url, dict(params)))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def finder(cfg, api, key="KEY123", calls=0):
    state = {"month": "2026-11", "calls": calls}
    return HotelFinder(cfg, key, state, api), state


def test_stay_dates_use_arrival_date():
    assert stay_dates(FARE) == ("2026-12-22", "2026-12-25", 3)
    assert stay_dates({**FARE, "arrive_date": None}) == ("2026-12-21", "2026-12-25", 4)
    assert stay_dates({**FARE, "arrive_date": "2026-12-25"}) == ("2026-12-21", "2026-12-25", 4)


def test_links_format():
    links = build_links("다낭 호텔", "2026-12-21", "2026-12-25", 4)
    assert links == {
        "google_hotels": "https://www.google.com/travel/search?q=%EB%8B%A4%EB%82%AD+%ED%98%B8%ED%85%94&checkin=2026-12-21&checkout=2026-12-25&hl=ko&gl=kr&curr=KRW",
        "agoda": "https://www.agoda.com/ko-kr/search?textToSearch=%EB%8B%A4%EB%82%AD+%ED%98%B8%ED%85%94&checkIn=2026-12-21&los=4&rooms=1&adults=1&currency=KRW",
    }


def test_no_key_means_links_only_and_no_call(cfg):
    api = Api()
    f, state = finder(cfg, api, key=None)
    h = f.lookup("다낭 호텔", FARE, NOW)
    assert h == links_only("다낭 호텔", FARE)
    assert h["source"] == "links" and h["items"] == [] and h["fetched_at"] is None
    assert api.calls == [] and state["calls"] == 0 and not f.enabled
    f, _ = finder(cfg, api, key="")
    assert not f.enabled


def test_serpapi_params_and_top_five_sorted(cfg):
    props = [prop(f"H{i}", night) for i, night in enumerate([90000, 30000, 70000, 50000, 110000, 40000, 60000])]
    props[1]["deal"] = "평소보다 21% 저렴"
    props[5]["deal_description"] = "특가"
    api = Api({"properties": props})
    f, state = finder(cfg, api)
    h = f.lookup("다낭 호텔", FARE, NOW)
    url, params = api.calls[0]
    assert url == "https://serpapi.com/search.json"
    assert params == {
        "engine": "google_hotels", "q": "다낭 호텔", "check_in_date": "2026-12-22", "check_out_date": "2026-12-25",
        "adults": 1, "currency": "KRW", "gl": "kr", "hl": "ko", "sort_by": 3, "special_offers": "true", "api_key": "KEY123",
    }
    assert h["source"] == "serpapi" and h["fetched_at"] == NOW
    assert [x["rate_per_night_krw"] for x in h["items"]] == [30000, 40000, 50000, 60000, 70000]
    assert h["items"][0] == {
        "name": "H1", "rate_per_night_krw": 30000, "total_rate_krw": 90000, "rating": 4.2,
        "deal": "평소보다 21% 저렴", "link": "https://hotel.example/H1",
    }
    assert h["items"][1]["deal"] == "특가" and h["items"][2]["deal"] is None
    assert h["links"]["google_hotels"].startswith("https://") and h["links"]["agoda"].startswith("https://")
    assert (f.calls_this_run, state["calls"]) == (1, 1)


def test_zero_results_retries_once_without_filter(cfg):
    api = Api({"properties": []}, {"properties": [prop("A", 50000)]})
    f, state = finder(cfg, api)
    h = f.lookup("q", FARE, NOW)
    assert len(api.calls) == 2
    assert "special_offers" in api.calls[0][1] and "special_offers" not in api.calls[1][1]
    assert h["source"] == "serpapi" and len(h["items"]) == 1 and state["calls"] == 2
    api = Api({"error": "Google Hotels hasn't returned any results for this query."}, {"properties": []})
    f, _ = finder(cfg, api)
    h = f.lookup("q", FARE, NOW)
    assert len(api.calls) == 2 and h["source"] == "serpapi" and h["items"] == []


def test_error_falls_back_to_links_without_leaking_key(cfg):
    api = Api(RuntimeError("401 for api_key=KEY123"))
    f, _ = finder(cfg, api)
    h = f.lookup("q", FARE, NOW)
    assert h["source"] == "links" and h["items"] == []
    assert len(f.errors) == 1 and "KEY123" not in f.errors[0]
    api = Api({"error": "Invalid API key."})
    f, _ = finder(cfg, api)
    assert f.lookup("q", FARE, NOW)["source"] == "links" and f.errors


def test_per_run_and_monthly_limits(cfg):
    api = Api(*[{"properties": [prop("A", 1)]} for _ in range(10)])
    f, state = finder(cfg, api)
    sources = [f.lookup("q", FARE, NOW)["source"] for _ in range(6)]
    assert sources == ["serpapi"] * 4 + ["links"] * 2 and len(api.calls) == cfg.serpapi_per_run
    api = Api({"properties": [prop("A", 1)]})
    f, state = finder(cfg, api, calls=cfg.serpapi_per_month)
    assert f.lookup("q", FARE, NOW)["source"] == "links" and api.calls == [] and f.errors


def test_bad_property_values_are_normalised(cfg):
    props = [
        {"name": ""}, "junk", {"name": "NoPrice", "overall_rating": 9, "link": "http://insecure"},
        prop("Ok", 10000, rating=None),
    ]
    api = Api({"properties": props})
    f, _ = finder(dataclasses.replace(cfg, hotel_max_items=5), api)
    items = f.lookup("q", FARE, NOW)["items"]
    assert [x["name"] for x in items] == ["Ok", "NoPrice"]
    assert items[1] == {"name": "NoPrice", "rate_per_night_krw": None, "total_rate_krw": None, "rating": None, "deal": None, "link": None}
