"""호텔 조회(SPEC 2.3절). SERPAPI_KEY 가 있으면 SerpApi google_hotels, 없으면 검색 링크만 저장한다."""
from __future__ import annotations

from datetime import date
from typing import Callable
from urllib.parse import urlencode

from .config import Config
from .http import get_json

SERPAPI_URL = "https://serpapi.com/search.json"


def stay_dates(fare: dict) -> tuple[str, str, int]:
    """체크인 = 가는 편 도착일(없으면 출발일), 체크아웃 = 귀국일."""
    check_out = fare["return_date"]
    check_in = fare.get("arrive_date") or fare["depart_date"]
    nights = (date.fromisoformat(check_out) - date.fromisoformat(check_in)).days
    if nights < 1:
        check_in = fare["depart_date"]
        nights = max((date.fromisoformat(check_out) - date.fromisoformat(check_in)).days, 1)
    return check_in, check_out, nights


def build_links(query: str, check_in: str, check_out: str, nights: int) -> dict:
    google = urlencode(
        {"q": query, "checkin": check_in, "checkout": check_out, "hl": "ko", "gl": "kr", "curr": "KRW"}
    )
    agoda = urlencode(
        {"textToSearch": query, "checkIn": check_in, "los": nights, "rooms": 1, "adults": 1, "currency": "KRW"}
    )
    return {
        "google_hotels": f"https://www.google.com/travel/search?{google}",
        "agoda": f"https://www.agoda.com/ko-kr/search?{agoda}",
    }


def links_only(query: str, fare: dict) -> dict:
    check_in, check_out, nights = stay_dates(fare)
    return {
        "source": "links",
        "query": query,
        "check_in": check_in,
        "check_out": check_out,
        "nights": nights,
        "fetched_at": None,
        "links": build_links(query, check_in, check_out, nights),
        "items": [],
    }


def _item(prop: dict) -> dict | None:
    name = prop.get("name")
    if not isinstance(name, str) or not name.strip():
        return None

    def money(key: str) -> int | None:
        v = (prop.get(key) or {}).get("extracted_lowest") if isinstance(prop.get(key), dict) else None
        return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0 else None

    rating = prop.get("overall_rating")
    if isinstance(rating, bool) or not isinstance(rating, (int, float)) or not 0 <= rating <= 5:
        rating = None
    deal = prop.get("deal") or prop.get("deal_description")
    link = prop.get("link")
    return {
        "name": name.strip(),
        "rate_per_night_krw": money("rate_per_night"),
        "total_rate_krw": money("total_rate"),
        "rating": rating,
        "deal": deal if isinstance(deal, str) and deal else None,
        "link": link if isinstance(link, str) and link.startswith("https://") else None,
    }


class HotelFinder:
    """SerpApi 호출 한도(실행당·월)를 관리한다. serpapi_state 는 status.json 의 serpapi 값이며 호출할 때마다 갱신한다."""

    def __init__(
        self,
        cfg: Config,
        api_key: str | None,
        serpapi_state: dict,
        http_get: Callable[[str, dict, float], dict] = get_json,
    ):
        self.cfg = cfg
        self.api_key = api_key or None
        self.state = serpapi_state
        self._get = http_get
        self.calls_this_run = 0
        self.errors: list[str] = []

    @property
    def enabled(self) -> bool:
        return self.api_key is not None

    def _can_call(self) -> bool:
        return (
            self.calls_this_run < self.cfg.serpapi_per_run and self.state["calls"] < self.cfg.serpapi_per_month
        )

    def _call(self, query: str, check_in: str, check_out: str, special_offers: bool) -> list[dict]:
        params = {
            "engine": "google_hotels",
            "q": query,
            "check_in_date": check_in,
            "check_out_date": check_out,
            "adults": 1,
            "currency": "KRW",
            "gl": "kr",
            "hl": "ko",
            "sort_by": 3,
            "api_key": self.api_key,
        }
        if special_offers:
            params["special_offers"] = "true"
        self.calls_this_run += 1
        self.state["calls"] += 1
        data = self._get(SERPAPI_URL, params, 30)
        if data.get("error") and not data.get("properties"):
            # SerpApi 는 결과가 0건일 때도 error 문구를 준다. 0건으로 처리하고 문구만 남긴다.
            if "hasn't returned any results" in str(data["error"]):
                return []
            raise RuntimeError(str(data["error"])[:160])
        props = data.get("properties")
        return [p for p in props if isinstance(p, dict)] if isinstance(props, list) else []

    def lookup(self, query: str, fare: dict, now_iso: str) -> dict:
        """알림 1건의 호텔 정보. 키 없음·한도 초과·오류이면 source=links 로 돌려준다."""
        result = links_only(query, fare)
        if not self.enabled:
            return result
        if not self._can_call():
            self.errors.append("SerpApi 호출 한도 초과로 검색 링크만 저장")
            return result
        try:
            props = self._call(query, result["check_in"], result["check_out"], special_offers=True)
            if not props:
                if not self._can_call():
                    self.errors.append("SerpApi 호출 한도 초과로 검색 링크만 저장")
                    return result
                props = self._call(query, result["check_in"], result["check_out"], special_offers=False)
        except Exception as e:
            self.errors.append(f"SerpApi 호출 오류: {type(e).__name__}: {str(e)[:160]}".replace(self.api_key, "***"))
            return result
        items = [x for x in (_item(p) for p in props) if x is not None]
        items.sort(key=lambda x: (x["rate_per_night_krw"] is None, x["rate_per_night_krw"] or 0))
        result.update(source="serpapi", fetched_at=now_iso, items=items[: self.cfg.hotel_max_items])
        return result
