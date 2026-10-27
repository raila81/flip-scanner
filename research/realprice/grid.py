"""Exit grid x entry filters, chronological train (first 60%) / test (last 40%)."""
import json, sys, itertools, pickle
import numpy as np
from sim import *

W = float(sys.argv[1]) if len(sys.argv) > 1 else 0      # wait minutes before the buy
LAT = float(sys.argv[2]) if len(sys.argv) > 2 else 2
drain = json.load(open("drainfeat.json")) if len(sys.argv) > 3 else None
K = load(drain)

exits = {}
for tp, st, T in itertools.product([1.03, 1.05, 1.08, 1.1, 1.15, 1.2, 1.3, 1.5, 2.0], [None, 0.05, 0.1, 0.2, 0.3], [1, 2, 3, 5, 10, 20, 30]):
    exits[f"tp{tp}/st{st}/T{T}"] = dict(legs=[{"part": 1, "tp": tp}], stop=st, T=T)
for act, d, st, T in itertools.product([1.0, 1.05, 1.1, 1.2], [0.05, 0.1, 0.15, 0.25], [None, 0.05, 0.1, 0.2], [3, 5, 10, 20, 30]):
    exits[f"tr{act}-{d}/st{st}/T{T}"] = dict(legs=[{"part": 1, "trail": d, "act": act}], stop=st, T=T)
for a, b, st, T in itertools.product([1.05, 1.1, 1.2], [1.3, 1.5, 2.0], [None, 0.1, 0.2], [5, 10, 20, 30]):
    exits[f"lad{a}+{b}/st{st}/T{T}"] = dict(legs=[{"part": .5, "tp": a}, {"part": .5, "tp": b}], stop=st, T=T)
for a, d, st, T in itertools.product([1.05, 1.1, 1.2], [0.1, 0.2], [None, 0.1, 0.2], [10, 20, 30]):
    exits[f"tp{a}+tr{d}/st{st}/T{T}"] = dict(legs=[{"part": .5, "tp": a}, {"part": .5, "trail": d, "act": a}], stop=st, T=T)
for T in [1, 2, 3, 5, 10]:
    exits[f"hold/T{T}"] = dict(legs=[{"part": 1, "tp": 999}], T=T)

# delayed-entry path stats
for k in K:
    k.w = None
    if W:
        k.w = wait_ok(k, W, lambda worst, chg, hi, solg: dict(worst=worst, chg=chg, hi=hi, solg=solg))

names = list(exits)
R = np.full((len(K), len(names)), np.nan)
for i, k in enumerate(K):
    if W and k.w is None:
        continue
    t0 = k.E + W * 60
    for j, nm in enumerate(names):
        r = run(k, exits[nm], t0, lat=LAT)
        if r:
            R[i, j] = r[0]
pickle.dump((names, R, [k.tok for k in K]), open(f"grid_W{W}_L{LAT}.pkl", "wb"))
ok = ~np.isnan(R[:, 0])
print("coins with a run", ok.sum(), "of", len(K))
