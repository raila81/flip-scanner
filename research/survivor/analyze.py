"""Survivor study: entry filters x exit plans on 15-min candles, picked on older coins, checked on newer ones."""
import sys, json, random, statistics as st, pickle, os
from collections import Counter
import sim

path = sys.argv[1] if len(sys.argv) > 1 else "candles.jsonl"
coins = sim.load(path)
for c in coins:
    sim.prep(c)
print("coins with candles", len(coins))

# ---- survival facts -------------------------------------------------------
def alive_at(c, h, vmin=30e3, lmin=10e3):
    for f in c["rows"]:
        if h <= f["age"] < h + 1 and f["v24"] >= vmin and (f["liq"] is None or f["liq"] >= lmin):
            return True
    return False
fresh = [c for c in coins if c.get("src") == "fresh"]
for h in (2, 6, 12, 24, 48):
    print(f"fresh coins still active (24h vol $30K+, pool $10K+) at age {h}h: {sum(alive_at(c, h) for c in fresh) / max(1, len(fresh)) * 100:.1f}%")

# ---- exit plans -----------------------------------------------------------
EX = {}
def add(name, legs, stop, H, be=None):
    EX[name] = dict(legs=legs, stop=stop, H=H, be=be)
add("swing now (1.5x/2x/trail30, st25, 48h)", [(0.5, 1.5), (0.3, 2.0), (0.2, "trail", 0.3, 1.0)], 0.25, 48)
add("quick now (1.25x, st15, 12h)", [(1.0, 1.25)], 0.15, 12)
add("2x now (2x, st25, be1.3, 4h)", [(1.0, 2.0)], 0.25, 4, 1.3)
for st_ in (0.2, 0.3, 0.4):
    for H in (12, 24, 48, 96):
        add(f"all 1.5x st{st_} {H}h", [(1.0, 1.5)], st_, H)
        add(f"all 2x st{st_} {H}h", [(1.0, 2.0)], st_, H)
        add(f"all 3x st{st_} {H}h", [(1.0, 3.0)], st_, H)
        add(f"half 1.5x half 3x st{st_} {H}h", [(0.5, 1.5), (0.5, 3.0)], st_, H)
        add(f"half 2x half trail30 st{st_} {H}h", [(0.5, 2.0), (0.5, "trail", 0.3, 1.0)], st_, H)
        add(f"swing ladder st{st_} {H}h", [(0.5, 1.5), (0.3, 2.0), (0.2, "trail", 0.3, 1.0)], st_, H)
        add(f"ladder 1.5/3/trail40 st{st_} {H}h", [(0.4, 1.5), (0.4, 3.0), (0.2, "trail", 0.4, 1.0)], st_, H)
        add(f"trail25 after 1.3x st{st_} {H}h", [(1.0, "trail", 0.25, 1.3)], st_, H)
        add(f"trail40 after 1.5x st{st_} {H}h", [(1.0, "trail", 0.4, 1.5)], st_, H)
        add(f"swing ladder be1.5 st{st_} {H}h", [(0.5, 1.5), (0.3, 2.0), (0.2, "trail", 0.3, 1.0)], st_, H, 1.5)
        add(f"half 2x half trail30 be1.5 st{st_} {H}h", [(0.5, 2.0), (0.5, "trail", 0.3, 1.0)], st_, H, 1.5)
names = list(EX)

# ---- entry filters --------------------------------------------------------
def L(f, **k):
    return sim.lane_ok(f, **k)
F = {}
F["lane now"] = L
F["lane, any age 6-96"] = lambda f: 6 <= f["age"] <= 96 and f["v24"] >= 30e3 and (f["liq"] or 1e9) >= 10e3 and f["chg1"] >= -0.08 and -0.25 <= f["chg6"] <= 1.2 and f["chg24"] >= -0.5
for a, b in ((6, 12), (12, 24), (24, 48), (48, 96)):
    F[f"lane age {a}-{b}h"] = lambda f, a=a, b=b: a <= f["age"] < b and F["lane, any age 6-96"](f)
EXTRA = {
    "chg1>=0": lambda f: f["chg1"] >= 0,
    "chg1>=5%": lambda f: f["chg1"] >= 0.05,
    "chg1<0": lambda f: f["chg1"] < 0,
    "chg6<=30%": lambda f: f["chg6"] <= 0.3,
    "chg6>=30%": lambda f: f["chg6"] >= 0.3,
    "chg6<0": lambda f: f["chg6"] < 0,
    "chg24>=0": lambda f: f["chg24"] >= 0,
    "chg24<0": lambda f: f["chg24"] < 0,
    "near top dd>=0.8": lambda f: f["dd"] >= 0.8,
    "dd 0.4-0.8": lambda f: 0.4 <= f["dd"] < 0.8,
    "deep dip dd<0.4": lambda f: f["dd"] < 0.4,
    "pool>=20K": lambda f: (f["liq"] or 0) >= 20e3,
    "pool>=40K": lambda f: (f["liq"] or 0) >= 40e3,
    "pool<20K": lambda f: (f["liq"] or 0) < 20e3,
    "mc<100K": lambda f: (f["mc"] or 0) < 100e3,
    "mc 100-500K": lambda f: 100e3 <= (f["mc"] or 0) < 500e3,
    "mc>=500K": lambda f: (f["mc"] or 0) >= 500e3,
    "vol24<mc": lambda f: f["mc"] and f["v24"] < f["mc"],
    "vol24 1-3x mc": lambda f: f["mc"] and f["mc"] <= f["v24"] < 3 * f["mc"],
    "vol24>=3x mc": lambda f: f["mc"] and f["v24"] >= 3 * f["mc"],
    "vol surge 1h>=2x avg": lambda f: f["v6"] > 0 and f["v1"] >= 2 * f["v6"] / 6,
    "vol fading 1h<0.5x avg": lambda f: f["v6"] > 0 and f["v1"] < 0.5 * f["v6"] / 6,
    "busy 24/24 slots in 6h": lambda f: f["act6"] >= 24,
    "ran 5x+ ever": lambda f: f["run"] >= 5,
    "ran <3x ever": lambda f: f["run"] < 3,
    "EU/US hours 12-22": lambda f: 12 <= f["hour"] < 22,
    "Asia hours 0-8": lambda f: f["hour"] < 8,
}
base = dict(F)
for bn in ("lane now", "lane, any age 6-96"):
    for en, ef in EXTRA.items():
        F[f"{bn} & {en}"] = lambda f, bf=base[bn], ef=ef: bf(f) and ef(f)
ek = list(EXTRA)
for i, a in enumerate(ek):
    for b in ek[i + 1:]:
        F[f"lane, any age 6-96 & {a} & {b}"] = lambda f, x=EXTRA[a], y=EXTRA[b]: base["lane, any age 6-96"](f) and x(f) and y(f)
print("filters", len(F), "exits", len(EX))

# ---- run ------------------------------------------------------------------
res = {}   # filter -> (times, matrix rows)
MEMO = {}
for fn, ff in F.items():
    rows = []
    for c in coins:
        i, f = sim.first_signal(c, ff)
        if i is None:
            continue
        key = (c["token"], i)
        if key not in MEMO:
            MEMO[key] = [sim.run(c, i, EX[n]) for n in names]
        r = MEMO[key]
        if r[0] is None:
            continue
        rows.append((f["T"], c["token"], r, f))
    rows.sort(key=lambda x: x[0])
    res[fn] = rows
pickle.dump((names, res), open("res.pkl", "wb"))

def stats(v):
    s = sorted(v)
    trim = s[: len(s) - max(1, len(s) // 50)]
    return dict(n=len(v), mean=st.mean(v), trim=st.mean(trim), med=st.median(v), win=sum(x > 0 for x in v) / len(v))

# global time split: older 60% of all signal times of the base lane
allT = sorted(x[0] for x in res["lane, any age 6-96"])
cut = allT[int(len(allT) * 0.6)] if allT else 0
print("split at", cut)
out = []
for fn, rows in res.items():
    tr = [r for r in rows if r[0] < cut]
    te = [r for r in rows if r[0] >= cut]
    if len(tr) < 40 or len(te) < 20:
        continue
    for j, n in enumerate(names):
        a = [r[2][j] for r in tr]
        b = [r[2][j] for r in te]
        sa, sb = stats(a), stats(b)
        out.append((sa["trim"], fn, n, sa, sb))
out.sort(key=lambda x: -x[0])
print("\nTOP 40 picked on older coins (trimmed mean), then newer coins")
for x in out[:40]:
    sa, sb = x[3], x[4]
    print(f"{sa['trim']*100:+6.1f}% n{sa['n']:4d} win{sa['win']*100:3.0f}% | newer {sb['mean']*100:+6.1f}% trim {sb['trim']*100:+6.1f}% med {sb['med']*100:+6.1f}% n{sb['n']:4d} | {x[1]} | {x[2]}")
top = out[:200]
print("of top 200: newer trimmed > 0:", sum(1 for x in top if x[4]["trim"] > 0), " mean newer trim", st.mean([x[4]["trim"] for x in top]) * 100 if top else None)
for fn in ("lane now", "lane, any age 6-96"):
    rows = res[fn]
    for n in names[:3]:
        j = names.index(n)
        v = [r[2][j] for r in rows]
        if v:
            s = stats(v)
            print(f"BASE {fn} | {n}: n{s['n']} mean {s['mean']*100:+.1f}% trim {s['trim']*100:+.1f}% med {s['med']*100:+.1f}% win {s['win']*100:.0f}%")
