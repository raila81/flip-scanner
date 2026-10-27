"""Real-price strategy simulator on the feed's tick paths.

Entry: market buy LAT s after the scanner signal (or after a wait), pool price plus impact.
Exits per leg: resting target (fills only if the price still holds DT_TGT s later),
trailing stop (armed at act), shared stop (optional break-even), time stop.
Stops and trails sell DELAY s after the cross at the pool price then, minus impact.
"""
import json, pickle, re, sys, bisect
import numpy as np

sys.path.insert(0, "/Users/rainerlang/Crypto/flip-scanner/scanner")
import playbooks as PB

FEE = 0.003          # pool fee per swap
TXC = 0.001          # priority fee + tip per transaction, share of a $50 trade
SIZE = 50.0

coins = json.load(open("coins.json"))
paths = pickle.load(open("paths.pkl", "rb"))


def pct(ws, pat):
    for w in ws or []:
        m = re.search(pat, w)
        if m:
            return float(m.group(1))
    return 0.0


class Coin:
    pass


def load(drain=None):
    out = []
    for tok, c in coins.items():
        if not c["signals"]:
            continue
        cov = c["cov"]
        ok = [s for s in c["signals"] if any(a - 5 <= s["t"] + 2 <= b for a, b in cov)]
        if not ok:
            continue
        s0 = ok[0]
        p = np.array(paths[tok], dtype=float)
        k = Coin()
        k.tok, k.sym, k.name = tok, c["symbol"], c["name"]
        k.E = s0["t"]
        k.t, k.px, k.sol = p[:, 0], p[:, 1], p[:, 2]
        k.cov = c["cov"]
        k.solUsd = c["solUsd"] or 190
        k.books = sorted({s["book"] for s in c["signals"]})
        k.source = s0["source"]
        tr = c["track"] or {}
        ws = tr.get("warnings") or []
        f = dict(
            famous=PB.famous_kind({"name": c["name"], "symbol": c["symbol"]}) or "none",
            liq=s0["liq0"] or 0, mc=s0["mc0"] or 0, chg1=s0["feat"].get("chg1"),
            holders=tr.get("holders"), tpb=tr.get("tradesPerBuyer"), buyers=tr.get("buyers24"),
            chg6=tr.get("chg6"), age=tr.get("age_h"), hour=tr.get("hourUtc"), boosts=tr.get("boosts"),
            hasX=tr.get("hasX"), hasWeb=tr.get("hasWeb"), bigSell=tr.get("bigSellUsd"), bigBuy=tr.get("bigBuyUsd"),
            same=pct(ws, r"same-size wallets hold ([\d.]+)%"), linked=pct(ws, r"Linked wallet group (?:may )?holds? ([\d.]+)%"),
            nwarn=len(ws), young=any("minutes old" in w for w in ws),
        )
        if drain and tok in drain:
            f.update(drain[tok])
        k.f = f
        out.append(k)
    out.sort(key=lambda k: k.E)
    return out


def at(k, t):
    """index of the last tick at or before t"""
    return max(0, int(np.searchsorted(k.t, t, side="right")) - 1)


def covered(k, t):
    return any(a - 5 <= t <= b for a, b in k.cov)


def sell_value(v, S):
    """SOL value v sold into a pool holding S SOL: constant product and fee."""
    x = v / S if S > 0 else 1.0
    return v / (1 + x) * (1 - FEE)


def run(k, cfg, t0, lat=2, delay=2, dt_tgt=1):
    """One trade. Returns (net return on SIZE, outcome)."""
    tb = t0 + lat
    if tb < k.t[0] - 1 or not covered(k, tb):
        return None
    i0 = at(k, tb)
    p0, S0 = k.px[i0], k.sol[i0]
    if p0 <= 0 or S0 <= 0:
        return None
    b = SIZE / k.solUsd
    pe = p0 * (1 + b / S0)                       # paid price before fee
    tokens = SIZE * (1 - FEE) / pe               # in USD units of the price series
    T = cfg["T"] * 60
    end = tb + T
    j1 = int(np.searchsorted(k.t, end, side="right"))
    t, px, sol = k.t[i0:j1], k.px[i0:j1], k.sol[i0:j1]
    last_t = k.t[-1]
    cm = np.maximum.accumulate(px)
    stop = cfg.get("stop")
    be = cfg.get("be")
    n = len(px)
    big = n + 1
    # shared stop index
    if stop:
        lvl = np.full(n, pe * (1 - stop))
        if be:
            lvl = np.where(cm >= pe * be, pe, lvl)
        hit = np.nonzero(px <= lvl)[0]
        si = hit[0] if len(hit) else big
    else:
        si = big
    total = 0.0
    txs = 1
    outs = []
    for leg in cfg["legs"]:
        part = leg["part"]
        q = tokens * part
        li, kind = big, None
        if "tp" in leg:
            tgt = pe * leg["tp"]
            cand = np.nonzero(px >= tgt)[0]
            for c in cand[:400]:
                jj = at(k, t[c] + dt_tgt)
                if k.px[jj] >= tgt:
                    li, kind = c, "tp"
                    break
        elif "trail" in leg:
            arm = pe * leg.get("act", 1.0)
            cond = (cm >= arm) & (px <= cm * (1 - leg["trail"]))
            h = np.nonzero(cond)[0]
            if len(h):
                li, kind = h[0], "trail"
        if si < li:
            li, kind = si, "stop"
        if li < n:
            if kind == "tp":
                v = q * pe * leg["tp"]
                S = sol[li]
                total += sell_value(v / k.solUsd, S) * k.solUsd
            else:
                jj = at(k, t[li] + delay)
                v = q * k.px[jj]
                total += sell_value(v / k.solUsd, k.sol[jj]) * k.solUsd
        else:
            # time stop, or the path ended first
            te = min(end, last_t)
            if not covered(k, te) and end > last_t:
                kind = "ended"
            else:
                kind = "time"
            jj = at(k, te)
            v = q * k.px[jj]
            total += sell_value(v / k.solUsd, k.sol[jj]) * k.solUsd
        txs += 1
        outs.append(kind)
    net = total / SIZE - 1 - TXC * txs
    return net, outs


def wait_ok(k, W, rule):
    """Delayed entry: look at the path from the signal to signal+W min."""
    t1 = k.E + W * 60
    if not covered(k, t1):
        return None
    i0, i1 = at(k, k.E), at(k, t1)
    if i1 <= i0:
        return None
    px, sol = k.px[i0:i1 + 1], k.sol[i0:i1 + 1]
    drops = sol[1:] / np.maximum(sol[:-1], 1e-9)
    worst = drops.min() if len(drops) else 1
    chg = px[-1] / px[0]
    hi = px.max() / px[0]
    return rule(worst, chg, hi, sol[-1] / max(sol[0], 1e-9))
