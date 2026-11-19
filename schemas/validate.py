"""데이터 폴더(data/ 또는 web/public/sample-data/)를 JSON Schema 와 교차 규칙으로 검증한다.

사용: uv run python schemas/validate.py [폴더]   (기본값: web/public/sample-data)
종료 코드: 오류가 없으면 0, 있으면 1.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent
FILES = ["index", "latest", "baseline", "alerts", "status"]


def load(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def schema_errors(name: str, doc) -> list[str]:
    schema = load(ROOT / f"{name}.schema.json")
    Draft202012Validator.check_schema(schema)
    v = Draft202012Validator(schema)
    return [f"/{'/'.join(map(str, e.absolute_path))}: {e.message[:200]}" for e in v.iter_errors(doc)]


def fare_rule_errors(where: str, f: dict) -> list[str]:
    errs = []
    j = f["judgement"]
    if not set(j["matched"]) <= set(j["evaluated"]):
        errs.append(f"{where}: matched 가 evaluated 의 부분집합이 아님")
    if j["matched_count"] != len(j["matched"]):
        errs.append(f"{where}: matched_count 불일치")
    if j["is_deal"] != (j["matched_count"] >= 2):
        errs.append(f"{where}: is_deal 불일치")
    ins = f["insight"]
    if ins and ins["typical_low_krw"] is not None and ins["typical_high_krw"] is not None:
        p = f["price_krw"]
        want = "low" if p < ins["typical_low_krw"] else "high" if p > ins["typical_high_krw"] else "typical"
        if ins["level"] != want:
            errs.append(f"{where}: level={ins['level']} 기대값={want}")
        if ("google_low" in j["matched"]) != (want == "low"):
            errs.append(f"{where}: google_low 판정 불일치")
    if j["baseline_price_krw"] is not None and ("offseason" in j["matched"]) != (f["price_krw"] <= j["baseline_price_krw"]):
        errs.append(f"{where}: offseason 판정 불일치")
    return errs


def main() -> int:
    d = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT.parent / "web/public/sample-data")
    errors: list[str] = []
    docs = {}
    for name in FILES:
        p = d / f"{name}.json"
        if not p.exists():
            errors.append(f"{p.name}: 파일 없음")
            continue
        docs[name] = load(p)
        errs = schema_errors(name, docs[name])
        print(f"{p.name}: {'OK' if not errs else f'{len(errs)}건 오류'}")
        errors += [f"{p.name}{e}" for e in errs]
    hist = sorted((d / "history").glob("*.json"))
    hist_bad = 0
    for p in hist:
        doc = load(p)
        errs = schema_errors("history", doc)
        if doc.get("destination") != p.stem:
            errs.append(": 파일 이름과 destination 불일치")
        ts = [x["collected_at"] for x in doc.get("points", [])]
        if ts != sorted(ts):
            errs.append(": points 가 시각 오름차순이 아님")
        hist_bad += bool(errs)
        errors += [f"history/{p.name}{e}" for e in errs]
    print(f"history/*.json: {len(hist)}개 중 {len(hist) - hist_bad}개 OK")

    if not errors and len(docs) == len(FILES):
        latest, alerts, index, status = docs["latest"], docs["alerts"], docs["index"], docs["status"]
        codes = [x["destination"] for x in latest["destinations"]]
        if len(codes) != len(set(codes)):
            errors.append("latest: destination 중복")
        if [x["destination"] for x in index["destinations"]] != codes:
            errors.append("index: 목적지 목록·순서가 latest 와 다름")
        hist_codes = {p.stem for p in hist}
        for x in index["destinations"]:
            if (x["history_file"] is not None) != (x["destination"] in hist_codes):
                errors.append(f"index: {x['destination']} history_file 과 실제 파일 유무 불일치")
        idx = {x["destination"]: x for x in index["destinations"]}
        active = {}
        for a in alerts["alerts"]:
            errors += fare_rule_errors(f"alerts {a['id']} fare", a["fare"])
            if a["status"] == "active":
                if a["destination"] in active:
                    errors.append(f"alerts: {a['destination']} active 알림이 2건 이상")
                active[a["destination"]] = a
                if a["current_fare"] is None:
                    errors.append(f"alerts {a['id']}: active 인데 current_fare 가 null")
            elif a["current_fare"] is not None or a["ended_at"] is None:
                errors.append(f"alerts {a['id']}: active 가 아니면 current_fare=null, ended_at 필요")
        for x in latest["destinations"]:
            c = x["destination"]
            for key in ("best", "deal"):
                if x[key]:
                    errors += fare_rule_errors(f"latest {c} {key}", x[key])
            if x["deal"] and not x["deal"]["judgement"]["is_deal"]:
                errors.append(f"latest {c}: deal 의 is_deal 이 false")
            if x["best"] and x["combos"] and x["best"]["price_krw"] != min(k["price_krw"] for k in x["combos"]):
                errors.append(f"latest {c}: best 가격이 combos 최저가와 다름")
            if (x["deal"] is not None) != (c in active):
                errors.append(f"latest {c}: deal 유무와 active 알림 유무 불일치")
            if idx[c]["is_deal"] != (x["deal"] is not None):
                errors.append(f"index {c}: is_deal 불일치")
            if idx[c]["best_price_krw"] != (x["best"]["price_krw"] if x["best"] else None):
                errors.append(f"index {c}: best_price_krw 불일치")
        if status["runs"] and status["runs"][0] != status["last_run"]:
            errors.append("status: runs[0] 과 last_run 이 다름")

    for e in errors:
        print("오류:", e)
    print(f"결과: {'통과' if not errors else f'실패({len(errors)}건)'} — {d}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
