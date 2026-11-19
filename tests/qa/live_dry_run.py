"""QA 실제 조회 1회(AC-24). pytest 수집 대상이 아니다(파일 이름이 test_ 로 시작하지 않음).

사용: uv run python tests/qa/live_dry_run.py <출력 폴더>
- Google Flights 요청은 최대 10건으로 제한한다(초과 시 예외).
- 환경 변수는 전달하지 않는다(텔레그램·SerpApi 호출 없음).
- 요청 시작 시각과 응답 길이를 <출력 폴더>/../live_requests.json 에 기록한다.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from collector import flights as fl  # noqa: E402
from collector.main import Deps, run  # noqa: E402

HARD_CAP = 10
log: list[dict] = []


def fetch(query, timeout):
    if len(log) >= HARD_CAP:
        raise RuntimeError("QA 요청 상한 초과")
    rec = {"start": time.time(), "url": query.url()}
    log.append(rec)
    html = fl.default_fetch(query, timeout)
    rec["length"] = len(html)
    rec["has_ds1"] = 'class="ds:1"' in html
    rec["bot_check"] = fl.BOT_CHECK_MARKER in html
    return html


def forbidden(*a, **k):
    raise AssertionError("외부 HTTP 호출 금지(텔레그램·SerpApi)")


out = Path(sys.argv[1])
code = run(
    ["--dry-run", "--destinations", "KIX,CJU", "--max-queries", "4", "--max-requests", "10",
     "--out", str(out), "--data", str(out.parent / "no-such-data")],
    Deps(fetch=fetch, env={}, http_get=forbidden, http_post=forbidden),
)
gaps = [round(b["start"] - a["start"], 2) for a, b in zip(log, log[1:])]
(out.parent / "live_requests.json").write_text(json.dumps({"exit_code": code, "requests": log, "gaps": gaps}, indent=1))
print("exit_code", code, "requests", len(log), "gaps", gaps)
print([(r.get("length"), r.get("has_ds1"), r.get("bot_check")) for r in log])
