"""Merge feed paths per pool, collect entry signals and features, write coins.json + paths.pkl."""
import json, glob, os, pickle, collections

S2 = "2026-10-22T18:30"
books = json.load(open("books.json"))["trades"]
track = json.load(open("track.json"))

files = collections.defaultdict(list)
for f in glob.glob("feed/*.json"):
    b = os.path.basename(f)
    if b == "watch.json" or "_" not in b:
        continue
    files[b[:-5].rsplit("_", 1)[1]].append(f)

coins = {}
paths = {}
for tok, fl in files.items():
    pts = {}
    meta = None
    spans = []
    for f in fl:
        try:
            d = json.load(open(f))
        except Exception:
            continue
        p = d.get("path") or []
        if not p:
            continue
        spans.append((p[0][0], p[-1][0]))
        for t, px, sol in p:
            pts[(t, px)] = (t, px, sol)
        if meta is None or d.get("startedAt", 9e18) < meta.get("startedAt", 9e18):
            meta = d
    if not pts or meta is None:
        continue
    path = sorted(pts.values())
    # merge coverage spans (gaps over 120 s count as no data)
    spans.sort()
    cov = []
    for a, b in spans:
        if cov and a <= cov[-1][1] + 120:
            cov[-1][1] = max(cov[-1][1], b)
        else:
            cov.append([a, b])
    paths[tok] = path
    coins[tok] = {"token": tok, "pool": meta["pool"], "symbol": meta.get("symbol"),
                  "solUsd": meta.get("solUsd"), "start": path[0][0], "end": path[-1][0],
                  "cov": cov, "ticks": len(path)}

# entry signals: every Season 2 source-book paper trade on a watched coin
sig = collections.defaultdict(list)
for k, x in books.items():
    if x["logged"] < S2 or x["book"].endswith("_chain") or x.get("mirror"):
        continue
    if x["token"] in coins and x.get("entryT"):
        sig[x["token"]].append({"book": x["book"], "t": x["entryT"], "paper": x["entry"],
                                "liq0": x.get("liq0"), "mc0": x.get("mc0"), "source": x.get("source"),
                                "name": x.get("name"), "feat": x.get("features") or {}})
for tok, c in coins.items():
    s = sorted(sig.get(tok, []), key=lambda r: r["t"])
    c["signals"] = s
    tr = track.get(tok)
    c["track"] = (tr or {}).get("features") if tr else None
    c["name"] = s[0]["name"] if s else None

json.dump(coins, open("coins.json", "w"))
pickle.dump(paths, open("paths.pkl", "wb"))
n = sum(1 for c in coins.values() if c["signals"])
print("coins", len(coins), "with S2 signals", n, "ticks", sum(len(p) for p in paths.values()))
dur = sorted((c["end"] - c["start"]) / 3600 for c in coins.values())
print("coverage hours median", dur[len(dur) // 2], "p25", dur[len(dur) // 4], "p75", dur[3 * len(dur) // 4])
print("track features found", sum(1 for c in coins.values() if c["track"] and "holders" in c["track"]))
