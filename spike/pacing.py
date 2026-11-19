"""조회 간격별 봇 확인 페이지 발생 빈도 측정."""
import sys, time, json
from fast_flights import FlightQuery, Passengers, create_query, fetch_flights_html

gap = float(sys.argv[1]); dests = sys.argv[2].split(",")
ok = 0
for i, d in enumerate(dests):
    q = create_query(flights=[FlightQuery(date="2026-12-22", from_airport="ICN", to_airport=d), FlightQuery(date="2026-12-28", from_airport=d, to_airport="ICN")],
                     trip="round-trip", passengers=Passengers(adults=1), language="ko", currency="KRW")
    t = time.time()
    try:
        html = fetch_flights_html(q)
        state = "VERIFY" if "Verifying your request" in html[:200000] and len(html) < 300000 else ("OK" if "ds:1" in html else "OTHER")
    except Exception as e:
        html, state = "", f"ERR {type(e).__name__}"
    ok += state == "OK"
    print(f"{i:2d} {d} {state} len={len(html)} {time.time()-t:.1f}s", flush=True)
    time.sleep(gap)
print(f"gap={gap}s OK {ok}/{len(dests)}")
