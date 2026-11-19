"""설정 파일(config/trip.yaml, config/destinations.yaml) 읽기와 날짜 조합 생성."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))


def iso_kst(dt: datetime) -> str:
    """스키마의 고정 형식(YYYY-MM-DDTHH:MM:SS+09:00)으로 변환한다."""
    return dt.astimezone(KST).strftime("%Y-%m-%dT%H:%M:%S+09:00")


def parse_iso(text: str) -> datetime:
    return datetime.fromisoformat(text)


def make_run_id(dt: datetime) -> str:
    return dt.astimezone(KST).strftime("%Y%m%dT%H%M%S")


@dataclass(frozen=True)
class Destination:
    code: str
    origin: str
    city_ko: str
    country_ko: str
    region: str
    hotel_query: str

    @property
    def is_domestic(self) -> bool:
        return self.region == "국내"

    def place(self) -> dict:
        return {
            "origin": self.origin,
            "destination": self.code,
            "city_ko": self.city_ko,
            "country_ko": self.country_ko,
            "region": self.region,
        }


@dataclass(frozen=True, order=True)
class Combo:
    depart: date
    nights: int

    @property
    def return_date(self) -> date:
        return self.depart + timedelta(days=self.nights)


@dataclass
class Config:
    adults: int
    depart_from: date
    depart_to: date
    return_by: date
    nights_min: int
    nights_max: int
    language: str
    currency: str
    max_stops: int
    max_duration_minutes: int
    representative: list[Combo]
    expand_top_n: int
    min_interval_seconds: float
    jitter_seconds: float
    retry_backoff_seconds: list[float]
    request_timeout_seconds: float
    abort_after_failures: int
    max_run_minutes: float
    max_no_result_ratio: float
    min_criteria: int
    own_drop_pct: int
    own_min_samples: int
    g60_percentile: int
    g60_min_points: int
    realert_drop_pct: int
    baseline_depart: date
    baseline_refresh_days: int
    baseline_max_queries: int
    failed_ratio: float
    stop_after_failed_runs: int
    hotel_max_items: int
    hotel_telegram_items: int
    serpapi_per_run: int
    serpapi_per_month: int
    keep_history: int
    keep_alerts: int
    keep_runs: int
    site_url: str
    destinations: list[Destination] = field(default_factory=list)

    def trip_dict(self) -> dict:
        return {
            "adults": self.adults,
            "depart_from": self.depart_from.isoformat(),
            "depart_to": self.depart_to.isoformat(),
            "return_by": self.return_by.isoformat(),
            "nights_min": self.nights_min,
            "nights_max": self.nights_max,
        }

    def nights_range(self) -> range:
        return range(self.nights_min, self.nights_max + 1)

    def all_combos(self, today: date | None = None) -> list[Combo]:
        """출발일 x 박수 조합. 귀국일이 return_by 이후이거나 출발일이 실행일 이전(당일 포함)이면 제외한다."""
        out = []
        d = self.depart_from
        while d <= self.depart_to:
            for n in self.nights_range():
                if d + timedelta(days=n) > self.return_by:
                    continue
                if today is not None and d <= today:
                    continue
                out.append(Combo(d, n))
            d += timedelta(days=1)
        return out

    def representative_combos(self, today: date | None = None) -> list[Combo]:
        """대표 조합 중 조회 가능한 것. 모두 지났으면 남은 전체 조합을 대표 조합으로 사용한다."""
        remaining = self.all_combos(today)
        valid = set(remaining)
        reps = [c for c in self.representative if c in valid]
        return reps or remaining


def _pct(ratio: float) -> int:
    return int(round(float(ratio) * 100))


def load_config(config_dir: Path | None = None) -> Config:
    config_dir = Path(config_dir) if config_dir else ROOT / "config"
    t = yaml.safe_load((config_dir / "trip.yaml").read_text(encoding="utf-8"))
    d = yaml.safe_load((config_dir / "destinations.yaml").read_text(encoding="utf-8"))
    trip, judge, pacing = t["trip"], t["judge"], t["pacing"]
    as_date = lambda v: v if isinstance(v, date) else date.fromisoformat(str(v))  # noqa: E731
    dests = [
        Destination(
            code=x["code"],
            origin=x["origin"],
            city_ko=x["city_ko"],
            country_ko=x["country_ko"],
            region=x["region"],
            hotel_query=x["hotel_query"],
        )
        for x in d["destinations"]
    ]
    codes = [x.code for x in dests]
    if len(codes) != len(set(codes)):
        raise ValueError("destinations.yaml 에 중복된 목적지 코드가 있습니다")
    return Config(
        adults=int(trip["adults"]),
        depart_from=as_date(trip["depart_from"]),
        depart_to=as_date(trip["depart_to"]),
        return_by=as_date(trip["return_by"]),
        nights_min=int(trip["nights_min"]),
        nights_max=int(trip["nights_max"]),
        language=trip.get("language", "ko"),
        currency=trip.get("currency", "KRW"),
        max_stops=int(t["filters"]["max_stops"]),
        max_duration_minutes=int(t["filters"]["max_duration_minutes"]),
        representative=[Combo(as_date(c["depart"]), int(c["nights"])) for c in t["sampling"]["representative_combos"]],
        expand_top_n=int(t["sampling"]["expand_top_n"]),
        min_interval_seconds=float(pacing["min_interval_seconds"]),
        jitter_seconds=float(pacing["jitter_seconds"]),
        retry_backoff_seconds=[float(x) for x in pacing["retry_backoff_seconds"]],
        request_timeout_seconds=float(pacing["request_timeout_seconds"]),
        abort_after_failures=int(pacing["abort_after_consecutive_query_failures"]),
        max_run_minutes=float(pacing.get("max_run_minutes", 150)),
        max_no_result_ratio=float(t["failure"].get("max_no_result_ratio", 0.5)),
        min_criteria=int(judge["min_criteria"]),
        own_drop_pct=_pct(judge["own_history"]["drop_ratio"]),
        own_min_samples=int(judge["own_history"]["min_samples"]),
        g60_percentile=int(judge["google_60d"]["percentile"]),
        g60_min_points=int(judge["google_60d"]["min_points"]),
        realert_drop_pct=_pct(judge["realert_drop_ratio"]),
        baseline_depart=as_date(t["baseline"]["depart_date"]),
        baseline_refresh_days=int(t["baseline"]["refresh_days"]),
        baseline_max_queries=int(t["baseline"]["max_queries_per_run"]),
        failed_ratio=float(t["failure"]["failed_run_success_ratio"]),
        stop_after_failed_runs=int(t["failure"]["stop_notice_after_consecutive_failed_runs"]),
        hotel_max_items=int(t["hotels"]["max_items"]),
        hotel_telegram_items=int(t["hotels"]["telegram_items"]),
        serpapi_per_run=int(t["hotels"]["max_serpapi_calls_per_run"]),
        serpapi_per_month=int(t["hotels"]["max_serpapi_calls_per_month"]),
        keep_history=int(t["retention"]["history_points_per_destination"]),
        keep_alerts=int(t["retention"]["alerts"]),
        keep_runs=int(t["retention"]["status_runs"]),
        site_url=str((t.get("notify") or {}).get("site_url") or ""),
        destinations=dests,
    )
