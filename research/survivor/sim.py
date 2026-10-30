"""Survivor study on 15-min candles.

For every tracked coin: walk its candles from graduation, compute the survivor-lane numbers at each candle close
(age, 1h/6h/24h change, 24h volume, drop from the top, rough pool size), buy at the NEXT candle's open the first time
a filter passes, then run an exit plan on the candles after that.

Conservative fills: if a candle touches both the stop and a target, the stop comes first; stops fill at
min(stop, open) minus SLIP; target fills need the candle high, and a single-candle wick is capped at 2x the
candle body for fills; costs COST per round trip.
"""
import json, math, os
D = os.path.dirname(os.path.abspath(__file__))
SLIP = 0.03
COST = 0.01
Q = 900


def load(path=f"{D}/candles.jsonl"):
    coins = []
    for l in open(path):
        c = json.loads(l)
        o = c.get("ohlcv") or []
        if len(o) < 8:
            continue
        o = sorted(o)
        # drop exact duplicates and zero prices
        o = [x for x in o if x[1] > 0 and x[2] > 0 and x[3] > 0 and x[4] > 0]
        if len(o) < 8:
            continue
        c["o"] = o
        coins.append(c)
    return coins


def prep(c):
    """Feature rows for every candle close up to age 96h (cached on the coin)."""
    import bisect
    o = c["o"]
    ts = [x[0] + Q for x in o]
    cv = [0.0]
    for x in o:
        cv.append(cv[-1] + x[5])
    rows = []
    ath = 0.0
    first = o[0][1]
    for i, x in enumerate(o):
        ath = max(ath, min(x[2], 2 * max(x[1], x[4])))
        T = ts[i]
        age = (T - c["grad"]) / 3600
        if age > 96:
            break
        p = x[4]

        def at(t):
            j = bisect.bisect_right(ts, t) - 1
            return o[j][4] if j >= 0 else first

        def vol(t):
            j = bisect.bisect_right(ts, t)
            return cv[i + 1] - cv[j]
        liq = mc = None
        if c.get("liq0") and c.get("price0"):
            liq = c["liq0"] * math.sqrt(p / c["price0"])
            mc = (c.get("mc0") or 0) * p / c["price0"]
        rows.append(dict(i=i, T=T, age=age, p=p, chg1=p / at(T - 3600) - 1, chg6=p / at(T - 6 * 3600) - 1,
                         chg24=p / at(T - 24 * 3600) - 1, v1=vol(T - 3600), v6=vol(T - 6 * 3600), v24=vol(T - 24 * 3600),
                         dd=p / ath, run=ath / first, liq=liq, mc=mc,
                         act6=i + 1 - bisect.bisect_right(ts, T - 6 * 3600), hour=int((T % 86400) // 3600)))
    c["rows"] = rows
    return rows


def lane_ok(f, liq_min=10e3, v24_min=30e3):
    return (6 <= f["age"] <= 48 and (f["liq"] is None or f["liq"] >= liq_min) and f["v24"] >= v24_min
            and f["chg1"] >= -0.08 and -0.25 <= f["chg6"] <= 1.2 and f["chg24"] >= -0.5)


def run(c, i, plan):
    """Buy at open of candle i+1. plan: legs [(part, tp) | (part, 'trail', trail, act)], stop, be, H (hours)."""
    o = c["o"]
    if i + 1 >= len(o):
        return None
    buy = o[i + 1][1]
    t_end = o[i + 1][0] + plan["H"] * 3600
    stop = buy * (1 - plan["stop"])
    be = plan.get("be")
    legs = [dict(part=l[0], tp=l[1]) if l[1] != "trail" else dict(part=l[0], trail=l[2], act=l[3]) for l in plan["legs"]]
    cash = 0.0
    left = 1.0
    peak = buy
    for x in o[i + 1:]:
        t, op, hi, lo, cl = x[0], x[1], x[2], x[3], x[4]
        if t >= t_end:
            # time stop at this candle's open
            cash += left * op
            left = 0
            break
        hi_f = min(hi, 2 * max(op, cl))
        # stop first (conservative), using the peak known before this candle
        lvl = stop
        if be and peak >= buy * be:
            lvl = max(lvl, buy)
        if lo <= lvl:
            cash += left * min(lvl, op) * (1 - SLIP)
            left = 0
            break
        for L in legs:
            if L.get("done"):
                continue
            if "tp" in L:
                if hi_f >= buy * L["tp"]:
                    cash += L["part"] * max(buy * L["tp"], op)
                    left -= L["part"]
                    L["done"] = True
            else:
                if peak >= buy * L["act"] and lo <= peak * (1 - L["trail"]):
                    cash += L["part"] * min(peak * (1 - L["trail"]), op) * (1 - SLIP)
                    left -= L["part"]
                    L["done"] = True
        peak = max(peak, hi_f)
        left = max(0.0, left)
        if left <= 1e-9:
            break
    else:
        # ran out of candles: no trades any more; value what is left at the last close, halved (dead pool)
        cash += left * o[-1][4] * 0.5
        left = 0
    return cash / buy - COST


def first_signal(c, ok):
    rows = c.get("rows") or prep(c)
    for f in rows:
        if f["age"] >= 1 and ok(f):
            return f["i"], f
    return None, None
