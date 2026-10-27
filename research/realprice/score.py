"""Score exits x filters: pick on train (older 60%), report test (newer 40%)."""
import sys, pickle, json
import numpy as np
from sim import load

f = sys.argv[1]
drain = json.load(open("drainfeat.json")) if len(sys.argv) > 2 else None
names, R, toks = pickle.load(open(f, "rb"))
K = {k.tok: k for k in load(drain)}
K = [K[t] for t in toks]
n = len(K)
order = np.arange(n)                       # K is sorted by signal time
ok = ~np.isnan(R[:, 0])
idx = np.nonzero(ok)[0]
cut = idx[int(len(idx) * 0.6)]
train = ok & (order < cut)
test = ok & (order >= cut)


def g(k, key, d=None):
    v = k.f.get(key)
    return d if v is None else v


F = {"all": lambda k: True}
F["famous exact"] = lambda k: k.f["famous"] == "exact"
F["not famous"] = lambda k: k.f["famous"] == "none"
for lo, hi in [(0, 20e3), (20e3, 40e3), (40e3, 1e12), (25e3, 1e12)]:
    F[f"pool {lo/1e3:.0f}-{hi/1e3:.0f}K"] = lambda k, lo=lo, hi=hi: lo <= g(k, "liq", 0) < hi
for lo, hi in [(0, 100), (100, 1e9), (200, 1e9), (400, 1e9)]:
    F[f"holders {lo}-{hi}"] = lambda k, lo=lo, hi=hi: k.f["holders"] is not None and lo <= k.f["holders"] < hi
for lo, hi in [(-1e9, 0), (0, 50), (50, 150), (150, 1e9)]:
    F[f"chg1 {lo}..{hi}"] = lambda k, lo=lo, hi=hi: k.f["chg1"] is not None and lo <= k.f["chg1"] < hi
F["no same-size"] = lambda k: k.f["same"] == 0
F["no linked group"] = lambda k: k.f["linked"] == 0
F["tpb<=2"] = lambda k: g(k, "tpb", 9) <= 2
F["not young"] = lambda k: not k.f["young"]
F["has web"] = lambda k: bool(k.f["hasWeb"])
F["source fresh"] = lambda k: k.source == "fresh"
F["source trending"] = lambda k: (k.source or "").startswith("trend")
F["EU/US hours 12-22"] = lambda k: k.f["hour"] is not None and 12 <= k.f["hour"] < 22
F["Asia hours 0-8"] = lambda k: k.f["hour"] is not None and 0 <= k.f["hour"] < 8
if drain:
    for th in (0.1, 0.2, 0.3, 0.5):
        F[f"top1 drain<{th}"] = lambda k, th=th: g(k, "d1", 9) < th
        F[f"top5 drain<{th*1.5:.2f}"] = lambda k, th=th: g(k, "d5", 9) < th * 1.5
        F[f"top10 drain<{th*2:.1f}"] = lambda k, th=th: g(k, "d10", 9) < th * 2
    F["drain data"] = lambda k: k.f.get("d1") is not None
W = float(f.split("_W")[1].split("_")[0])
if W:
    import sim
    for k in K:
        k.w = sim.wait_ok(k, W, lambda worst, chg, hi, solg: dict(worst=worst, chg=chg, hi=hi, solg=solg))
    w = lambda k, key, d: (k.w or {}).get(key, d)
    F["wait: no tick drop over 15%"] = lambda k: w(k, "worst", 0) > 0.85
    F["wait: no tick drop over 30%"] = lambda k: w(k, "worst", 0) > 0.70
    F["wait: price up"] = lambda k: w(k, "chg", 0) > 1.0
    F["wait: price up 20%+"] = lambda k: w(k, "chg", 0) > 1.2
    F["wait: price down"] = lambda k: w(k, "chg", 9) < 1.0
    F["wait: pool SOL grew"] = lambda k: w(k, "solg", 0) > 1.0
    F["wait: pool SOL up 20%+"] = lambda k: w(k, "solg", 0) > 1.2
masks = {nm: np.array([fn(k) for k in K]) for nm, fn in F.items()}
# pairs of filters
base = list(masks)
for a in base:
    for b in base:
        if a < b and a != "all" and b != "all":
            masks[a + " & " + b] = masks[a] & masks[b]


def stats(v):
    if len(v) == 0:
        return dict(n=0)
    s = np.sort(v)
    trim = s[: max(1, len(s) - max(1, len(s) // 50))]   # best 2% removed
    return dict(n=len(v), mean=v.mean(), trim=trim.mean(), med=np.median(v), win=(v > 0).mean(), usd=v.sum() * 50)


rows = []
for mn, m in masks.items():
    tr, te = m & train, m & test
    if tr.sum() < 25 or te.sum() < 12:
        continue
    A, B = R[tr], R[te]
    ma, mb = np.nanmean(A, 0), np.nanmean(B, 0)
    for j in np.argsort(-ma)[:3]:
        rows.append((ma[j], mn, names[j], int(tr.sum()), mb[j], int(te.sum())))
rows.sort(reverse=True)
print(f"{'train':>7} {'test':>7}  n_tr n_te  filter | exit")
for r in rows[:40]:
    print(f"{r[0]*100:+6.1f}% {r[4]*100:+6.1f}%  {r[3]:4d} {r[5]:4d}  {r[1]} | {r[2]}")
# how often does the train winner hold up
top = rows[:200]
print("\nof top 200 train picks, test > 0:", sum(1 for r in top if r[4] > 0), " test mean", np.mean([r[4] for r in top]) * 100)
# best single exits for all coins
ma = np.nanmean(R[ok], 0)
print("\nbest exits on all coins (both halves):")
for j in np.argsort(-ma)[:15]:
    a, b = np.nanmean(R[train][:, j]), np.nanmean(R[test][:, j])
    s = stats(R[ok][:, j])
    print(f"  {names[j]:28s} all {ma[j]*100:+5.1f}% trim {s['trim']*100:+5.1f}% med {s['med']*100:+5.1f}% win {s['win']*100:3.0f}%  older {a*100:+5.1f}% newer {b*100:+5.1f}%  ${s['usd']:+.0f}")
