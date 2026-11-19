"""백엔드 검토용: 수집기의 실제 실행 코드(collector.main.run)로 경계 상황 데이터를 만든다. 네트워크 미사용.

사용: uv run python tests/qa/backend_review_gen.py <출력 폴더>
"""
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from collector.config import KST, load_config  # noqa: E402
from collector.main import run  # noqa: E402
from conftest import BOT_HTML, Sim, make_history, make_html, make_insight, make_item, make_payload, simple_html  # noqa: E402

cfg = load_config()
order = {d.code: i for i, d in enumerate(cfg.destinations)}
out_root = Path(sys.argv[1])
D1 = datetime(2026, 11, 18, 21, 0, 0, tzinfo=KST)
D2 = datetime(2026, 11, 19, 8, 0, 0, tzinfo=KST)


def price(dest, depart, ret):
    base = 150000 + order[dest] * 20000
    if depart.startswith("2027-03"):
        return base - 30000
    return base + int(depart[-2:]) * 100 + int(ret[-2:]) * 10


def normal(deal_dest=None, deal_price=None, special=None):
    def responder(origin, dest, depart, ret):
        if special:
            r = special(origin, dest, depart, ret)
            if r is not None:
                return r
        p = price(dest, depart, ret)
        if dest == deal_dest and not depart.startswith("2027-03"):
            p = deal_price
            return simple_html(p, low=p + 50000, high=p + 300000, history=make_history([p + 80000] * 60 + [p]))
        return simple_html(p, low=p - 20000, high=p + 200000, history=make_history([p - 10000] * 60 + [p]))
    return responder


def go(name, argv, sim):
    code = run(argv, sim.deps())
    print(f"[{name}] exit={code} :: {sim.lines[0]} :: {sim.lines[1]}")
    return code


# s1: 정상 1회, 토큰 없음, 특가 1건(JFK)
s1 = out_root / "s1" / "data"
go("s1", ["--out", str(s1)], Sim(normal("JFK", 900000), start=D1))

# s2: 첫 실행에서 전부 봇 확인(Actions IP 차단 상황)
s2 = out_root / "s2" / "data"
go("s2", ["--out", str(s2)], Sim(lambda *a: BOT_HTML, start=D2))

# s3: 1차 정상 -> 2차 부분 실패 + 경계 값
s3 = out_root / "s3" / "data"
shutil.copytree(s1, s3)


def special3(origin, dest, depart, ret):
    if depart.startswith("2027-03"):
        return None
    if dest == "KIX":
        return BOT_HTML  # 전부 실패 -> 이전 값 유지
    if dest == "NRT":
        return make_html(make_payload([], insight=None))  # 결과 없음
    if dest == "FUK":
        return simple_html(price(dest, depart, ret))  # insight 없음
    if dest == "CTS":
        p = price(dest, depart, ret)
        return make_html(make_payload([make_item(p)], insight=[None, None, None, None, None, None, None, None, None, None, None]))
    if dest == "HND":
        p = price(dest, depart, ret)
        return make_html(make_payload([make_item(p, names=(), code=None, duration=None)], insight=make_insight(p, p - 1000, p + 1000, history=[])))
    return None


go("s3", ["--out", str(s3)], Sim(normal(None, None, special3), start=D2))

# s4: 토큰 + SerpApi, 특가 발송, 호텔 항목 경계 값
s4 = out_root / "s4" / "data"
sim4 = Sim(normal("DAD", 120000), env={"TELEGRAM_BOT_TOKEN": "x:y", "TELEGRAM_CHAT_ID": "1", "SERPAPI_KEY": "k"}, start=D2)
sim4.get_response = {"properties": [
    {"name": "호텔 A", "rate_per_night": {"extracted_lowest": 81000}, "total_rate": {"extracted_lowest": 324000}, "overall_rating": 4.3, "link": "https://example.com/a", "deal": "평소보다 23% 저렴"},
    {"name": "호텔 B(요금 없음)", "overall_rating": 3, "link": "http://example.com/b"},
    {"name": "호텔 C", "rate_per_night": {"extracted_lowest": 55000.0}},
]}
go("s4", ["--out", str(s4)], sim4)

# s5: 1차 정상 -> 2차 조회 상한 20건(대부분 미조회)
s5 = out_root / "s5" / "data"
shutil.copytree(s1, s5)
go("s5", ["--out", str(s5), "--max-queries", "20"], Sim(normal("JFK", 900000), start=D2))

# s6: 1차 정상 -> 2차 --destinations CJU 만
s6 = out_root / "s6" / "data"
shutil.copytree(s1, s6)
go("s6", ["--out", str(s6), "--destinations", "CJU"], Sim(normal("JFK", 900000), start=D2))

for s in ["s1", "s2", "s3", "s4", "s5", "s6"]:
    d = out_root / s / "data"
    latest = json.loads((d / "latest.json").read_text())
    st = json.loads((d / "status.json").read_text())
    n_stale = sum(1 for e in latest["destinations"] if e["stale"])
    n_null = sum(1 for e in latest["destinations"] if e["best"] is None)
    print(s, "state", st["state"], "result", st["last_run"]["result"], "stale", n_stale, "best=null", n_null,
          "failed_dest", len(st["last_run"]["failed_destinations"]), "queries", st["last_run"]["queries"], "aborted", st["last_run"]["aborted_reason"])
