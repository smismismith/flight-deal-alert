"""data/*.json 읽기·쓰기(SPEC 6장). 파일은 임시 파일에 쓴 뒤 이름을 바꾼다."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .config import Config, Destination

SCHEMA_VERSION = 1


def read_json(path: Path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path: Path, doc) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def default_status(now_iso: str) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "updated_at": now_iso,
        "state": "ok",
        "consecutive_failures": 0,
        "stop_notice_sent": False,
        "last_success_at": None,
        "serpapi": {"month": now_iso[:7], "calls": 0},
        "last_run": None,
        "runs": [],
    }


class DataStore:
    """read_dir 에서 이전 상태를 읽고 write_dir 에 저장한다. write_dir 이 None 이면 저장하지 않는다."""

    def __init__(self, read_dir: Path, write_dir: Path | None):
        self.read_dir = Path(read_dir)
        self.write_dir = Path(write_dir) if write_dir else None
        self.baseline_updated_at: str | None = None

    # ---- 읽기
    def load_latest(self) -> dict[str, dict]:
        doc = read_json(self.read_dir / "latest.json", {})
        return {d["destination"]: d for d in doc.get("destinations", []) if isinstance(d, dict) and "destination" in d}

    def load_alerts(self) -> list[dict]:
        return list(read_json(self.read_dir / "alerts.json", {}).get("alerts", []))

    def load_baseline(self) -> list[dict]:
        doc = read_json(self.read_dir / "baseline.json", {})
        self.baseline_updated_at = doc.get("updated_at")
        return list(doc.get("entries", []))

    def load_status(self, now_iso: str) -> dict:
        doc = read_json(self.read_dir / "status.json", None)
        if not isinstance(doc, dict) or "runs" not in doc:
            return default_status(now_iso)
        return doc

    def load_history(self, code: str) -> list[dict]:
        return list(read_json(self.read_dir / "history" / f"{code}.json", {}).get("points", []))

    # ---- 쓰기
    def _write(self, name: str, doc) -> None:
        if self.write_dir is not None:
            write_json(self.write_dir / name, doc)

    def save_status(self, status: dict) -> None:
        self._write("status.json", status)

    def save_baseline(self, entries: list[dict], now_iso: str, previous_updated_at: str | None = None) -> None:
        self._write(
            "baseline.json",
            {"schema_version": SCHEMA_VERSION, "updated_at": previous_updated_at or now_iso, "entries": entries},
        )

    def save_alerts(self, alerts: list[dict], now_iso: str) -> None:
        self._write("alerts.json", {"schema_version": SCHEMA_VERSION, "updated_at": now_iso, "alerts": alerts})

    def save_history(self, dest: Destination, points: list[dict], keep: int) -> None:
        points = sorted(points, key=lambda p: p["collected_at"])[-keep:]
        self._write(
            f"history/{dest.code}.json",
            {"schema_version": SCHEMA_VERSION, **dest.place(), "points": points},
        )

    def save_latest_and_index(
        self, cfg: Config, entries: list[dict], history_codes: set[str], run_id: str, now_iso: str
    ) -> None:
        self._write(
            "latest.json",
            {
                "schema_version": SCHEMA_VERSION,
                "generated_at": now_iso,
                "run_id": run_id,
                "trip": cfg.trip_dict(),
                "destinations": entries,
            },
        )
        self._write(
            "index.json",
            {
                "schema_version": SCHEMA_VERSION,
                "generated_at": now_iso,
                "run_id": run_id,
                "is_sample": False,
                "destinations": [
                    {
                        "destination": e["destination"],
                        "origin": e["origin"],
                        "city_ko": e["city_ko"],
                        "country_ko": e["country_ko"],
                        "region": e["region"],
                        "is_domestic": e["is_domestic"],
                        "best_price_krw": e["best"]["price_krw"] if e["best"] else None,
                        "is_deal": e["deal"] is not None,
                        "history_file": f"history/{e['destination']}.json" if e["destination"] in history_codes else None,
                    }
                    for e in entries
                ],
            },
        )


def empty_entry(dest: Destination, stale: bool) -> dict:
    return {
        **dest.place(),
        "is_domestic": dest.is_domestic,
        "expanded": False,
        "stale": stale,
        "last_success_at": None,
        "best": None,
        "deal": None,
        "combos": [],
    }


def history_point(run_id: str, best: dict, rep_price: int | None, combos_checked: int) -> dict:
    return {
        "collected_at": best["collected_at"],
        "run_id": run_id,
        "price_krw": best["price_krw"],
        "rep_price_krw": rep_price,
        "depart_date": best["depart_date"],
        "return_date": best["return_date"],
        "nights": best["nights"],
        "airlines": best["airlines"],
        "stops": best["stops"],
        "combos_checked": combos_checked,
    }
