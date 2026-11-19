"""진단용: ds:1 스크립트의 앞뒤 일부와 해석 결과를 출력한다."""
import re, sys, time
from collector import flights as F
from fast_flights import FlightQuery, Passengers, create_query, fetch_flights_html

for dest, out, back in [("KIX","2026-12-17","2026-12-20"),("FUK","2026-12-18","2026-12-23"),("KIX","2026-12-21","2026-12-25"),("DAD","2026-12-21","2026-12-25"),("CJU","2026-12-23","2026-12-30"),("KIX","2026-12-27","2026-12-31")]:
    o = "GMP" if dest == "CJU" else "ICN"
    q = create_query(flights=[FlightQuery(date=out, from_airport=o, to_airport=dest), FlightQuery(date=back, from_airport=dest, to_airport=o)],
                     trip="round-trip", passengers=Passengers(adults=1), language="ko", currency="KRW")
    html = fetch_flights_html(q)
    m = F._DS1_RE.search(html)
    js = m.group(1) if m else ""
    try:
        F.extract_payload(html); state = "OK"
    except Exception as e:
        state = f"{type(e).__name__}: {e}"
    print(f"== {dest} {out} len={len(html)} ds1={len(js)} {state}")
    print("   head:", js[:160].replace("\n", " "))
    print("   tail:", js[-260:].replace("\n", " "))
    print("   all ds keys:", sorted(set(re.findall(r'class="(ds:\d+)"', html))))
    time.sleep(6)
