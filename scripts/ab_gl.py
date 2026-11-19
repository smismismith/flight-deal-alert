"""진단용: gl=kr 지정 여부에 따른 Google 오류 응답 비율 비교."""
import time, datetime, collections
from primp import Client
from collector import flights as F
from collector.config import load_config

cfg = load_config()
dests = ["KIX","NRT","FUK","TPE","HKG","DAD","BKK","CEB","GUM","SYD","LHR","CDG","LAX","SGN","MNL","KUL","SIN","HNL","DXB","DEL"]
stats = collections.defaultdict(collections.Counter)
sample = {}
for i, d in enumerate(dests * 2):
    dep = datetime.date(2026, 12, 17 + (i % 10)); ret = dep + datetime.timedelta(days=4)
    q = F.build_query(cfg, "ICN", d, dep, ret)
    for variant in ("none", "gl"):
        params = dict(q.params())
        if variant == "gl": params["gl"] = "kr"
        c = Client(impersonate="chrome_145", impersonate_os="macos", referer=True, cookie_store=True, timeout=30)
        try:
            html = c.get(F.FLIGHTS_URL, params=params).text
            try:
                page = F.parse_html(html); kind = "ok"
                p = min((f.price_krw for f in page.flights), default=None)
                sample.setdefault((d, dep), {})[variant] = p
            except F.BotCheckError: kind = "bot"
            except F.UnexpectedPageError: kind = "error_response"
            except Exception as e: kind = type(e).__name__
        except Exception as e:
            kind = "net:" + type(e).__name__
        stats[variant][kind] += 1
        print(i, d, variant, kind, flush=True)
        time.sleep(4)
print("RESULT", {k: dict(v) for k, v in stats.items()})
for k, v in list(sample.items())[:15]:
    print("PRICE", k[0], k[1], v)
