"""Fetch 15-min GeckoTerminal candles from graduation for every tracked Solana coin (one call each)."""
import json, time, urllib.request, datetime as dt, os, sys
D = os.path.dirname(os.path.abspath(__file__))
t = json.load(open(sys.argv[1] if len(sys.argv) > 1 else f"{D}/track.json"))
b = json.load(open(sys.argv[2] if len(sys.argv) > 2 else f"{D}/books.json"))
STOP_AT = time.time() + float(os.environ.get("MAX_MIN", "1e9")) * 60
coins = {}
def ts(v):
    try: return dt.datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except Exception: return None
for v in t.values():
    if v.get("chain") != "solana" or not v.get("pair"): continue
    T = ts(v.get("logged"))
    if not T: continue
    age = (v.get("features") or {}).get("age_h") or 0
    coins.setdefault(v["token"], dict(token=v["token"], pair=v["pair"], name=v.get("name"), src=v.get("source"),
                                      t0=T, grad=T - age * 3600, liq0=v.get("liq0"), price0=v.get("price0"), mc0=v.get("mc0")))
for k, e in b["trades"].items():
    if e.get("chain") == "solana" and e.get("pair") and e["token"] not in coins and k.startswith("surv"):
        T = e.get("entryT") or ts(e.get("logged"))
        age = (e.get("features") or {}).get("age_h") or 24
        coins[e["token"]] = dict(token=e["token"], pair=e["pair"], name=e.get("name"), src="survbook", t0=T,
                                 grad=T - age * 3600, liq0=e.get("liq0"), price0=e.get("price0"), mc0=e.get("mc0"))
now = time.time()
lo, hi = dt.datetime(2026, 10, 6, tzinfo=dt.timezone.utc).timestamp(), now - 50 * 3600
todo = [c for c in coins.values() if lo <= c["t0"] <= hi]
out = os.environ.get("OUT", f"{D}/candles.jsonl")
done = set()
if os.path.exists(out):
    for l in open(out):
        done.add(json.loads(l)["token"])
todo = [c for c in todo if c["token"] not in done]
todo.sort(key=lambda c: -c["t0"])   # newest first
print("coins", len(coins), "todo", len(todo), flush=True)
f = open(out, "a")
for i, c in enumerate(todo):
    before = int(min(now, c["grad"] + 1000 * 900))
    url = (f"https://api.geckoterminal.com/api/v2/networks/solana/pools/{c['pair']}/ohlcv/minute"
           f"?aggregate=15&limit=1000&currency=usd&token=base&before_timestamp={before}")
    for a in range(5):
        try:
            r = urllib.request.urlopen(urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "flip-research/1.0"}), timeout=20)
            d = json.load(r); ok = True; break
        except urllib.error.HTTPError as e:
            if e.code == 429: time.sleep(15); continue
            d = {"err": e.code}; ok = False; break
        except Exception as e:
            d = {"err": str(e)}; time.sleep(3)
    c["ohlcv"] = (d.get("data") or {}).get("attributes", {}).get("ohlcv_list") if isinstance(d, dict) else None
    c["err"] = d.get("err") if isinstance(d, dict) else None
    f.write(json.dumps(c) + "\n"); f.flush()
    if i % 100 == 0: print(i, time.strftime("%H:%M:%S"), flush=True)
    if time.time() > STOP_AT: print("time limit", i, flush=True); break
    time.sleep(2.4)
print("finished", flush=True)
