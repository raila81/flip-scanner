"""Turn the holder rebuild into drain-risk features per coin.

h = a wallet's tokens at the buy, R = pool token reserve at the buy.
Selling h into the pool takes h/(R+h) of the pool's SOL.
d1 = biggest single wallet, d5 / d10 = top 5 / top 10 wallets selling together.
"""
import json
from collections import defaultdict

out = {}
late = 0
for line in open("drainout.jsonl"):
    r = json.loads(line)
    if "cand" not in r or not r.get("resTok"):
        continue
    R = r["resTok"]
    by_owner = defaultdict(float)
    unknown = 0
    for acct, e in r["cand"].items():
        if e.get("pool") or e.get("skip"):
            continue
        if e.get("balE") is None:
            unknown += 1
            continue
        by_owner[e["owner"]] += e["balE"]
    hs = sorted(by_owner.values(), reverse=True)
    share = lambda h: h / (R + h)
    big_sellers_after = [s for s in r["sells"] if s["sold"] > 0.3 * R]
    late += sum(1 for s in big_sellers_after if by_owner.get(s["owner"], 0) < 0.3 * s["sold"])
    out[r["token"]] = dict(d1=share(hs[0]) if hs else 0.0, d5=share(sum(hs[:5])), d10=share(sum(hs[:10])),
                           n10=sum(1 for h in hs if h >= 0.1 * R), unk=unknown)
json.dump(out, open("drainfeat.json", "w"))
print("coins", len(out), "big sellers who bought after the buy:", late)
