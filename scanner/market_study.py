#!/usr/bin/env python3
"""Market study: do the paper trades do better or worse depending on what BTC and SOL are doing?

Reads data/books.json (playbook trades) and data/track.json (main portfolio buy-now trades),
pulls 15-minute BTC and SOL prices from Binance (free, no key), and asks three questions:
  1. Do trades opened while BTC/SOL was rising do better than trades opened while it was falling?
  2. Does the P&L of each 6-hour block move with BTC/SOL in that block?
  3. Would a "market switch" (only trade when condition X holds) have helped each playbook,
     judged on a trimmed average that must be positive in BOTH the older and newer half?

Usage: python3 scanner/market_study.py [--out reports/market-study.md]
"""
import argparse
import json
import math
import os
import statistics as st
import sys
import urllib.request
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime, timezone

COST = 0.03
MIN_GROUP = 30
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


# ---------- prices ----------
def fetch_klines(symbol, interval="15m", limit=1000):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 flip-scanner study"})
    with urllib.request.urlopen(req, timeout=30) as r:
        rows = json.load(r)
    return [(row[0] / 1000, float(row[4])) for row in rows]  # (open time s, close)


class Series:
    def __init__(self, rows):
        self.t = [r[0] for r in rows]
        self.p = [r[1] for r in rows]

    def at(self, ts):
        i = bisect_right(self.t, ts) - 1
        return self.p[i] if i >= 0 else None

    def change(self, ts, hours):
        a, b = self.at(ts - hours * 3600), self.at(ts)
        return (b / a - 1) * 100 if a and b else None

    def above_ma(self, ts, hours=24):
        i = bisect_right(self.t, ts)
        lo = bisect_right(self.t, ts - hours * 3600)
        win = self.p[lo:i]
        now = self.at(ts)
        return (now > st.mean(win)) if win and now else None


# ---------- trades ----------
def mult(e):
    now = e["now"] if e.get("now") is not None else e["entry"]
    return (e.get("cash") or 0) + (e.get("pos") or 0) * now / e["entry"]


def load_trades():
    out = []
    with open(os.path.join(ROOT, "data", "books.json")) as fh:
        b = json.load(fh)
    labels = {k: v["label"] for k, v in b["books"].items()}
    for e in b["trades"].values():
        if e.get("entry") and e.get("final"):
            out.append(dict(group="playbook", book=e["book"], label=labels.get(e["book"], e["book"]), symbol=e["symbol"],
                            t_in=e["entryT"], t_out=e.get("exit") or e["entryT"], size=e["size"],
                            net=e["size"] * (mult(e) * (1 - COST) - 1)))
    with open(os.path.join(ROOT, "data", "track.json")) as fh:
        t = json.load(fh)
    for e in t.values():
        if e.get("plan") == "v2" and e.get("strategy") == "now" and e.get("entry") and e.get("final") and e.get("outcome") != "Bad data":
            out.append(dict(group="portfolio", book="portfolio_now", label="Main portfolio, buy now", symbol=e["symbol"],
                            t_in=e["entryT"], t_out=e.get("exit") or e["entryT"], size=e.get("size") or 250,
                            net=(e.get("size") or 250) * (mult(e) * (1 - COST) - 1)))
    return out


# ---------- stats helpers ----------
def pct(e):
    return e["net"] / e["size"] * 100


def trimmed(vals, share=0.02):
    if not vals:
        return None
    k = max(1, round(len(vals) * share)) if len(vals) >= 10 else 0
    v = sorted(vals)
    return st.mean(v[: len(v) - k]) if k else st.mean(v)


def halves(trades):
    ts = sorted(trades, key=lambda e: e["t_in"])
    h = len(ts) // 2
    a, b = ts[:h], ts[h:]
    return (trimmed([pct(e) for e in a]) if a else None, trimmed([pct(e) for e in b]) if b else None)


def summary(trades):
    vals = [pct(e) for e in trades]
    if not vals:
        return dict(n=0)
    a, b = halves(trades)
    return dict(n=len(vals), total=sum(e["net"] for e in trades), avg=st.mean(vals), trimmed=trimmed(vals),
                win=sum(1 for v in vals if v > 0) / len(vals) * 100, older=a, newer=b,
                solid=(a is not None and b is not None and a > 0 and b > 0 and len(vals) >= MIN_GROUP))


def pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx, my = st.mean(xs), st.mean(ys)
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs)),
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if not sx[0] or not sy:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx[0] * sy)


def ranks(vals):
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    r = [0] * len(vals)
    for rank, i in enumerate(order):
        r[i] = rank
    return r


def spearman(xs, ys):
    return pearson(ranks(xs), ranks(ys))


def fmt(v, suffix="%"):
    return "-" if v is None else f"{v:+.1f}{suffix}"


# ---------- the study ----------
CONDITIONS = [
    ("SOL up in the last 1h", lambda m: m["sol1h"] is not None and m["sol1h"] > 0),
    ("SOL up in the last 6h", lambda m: m["sol6h"] is not None and m["sol6h"] > 0),
    ("SOL up in the last 24h", lambda m: m["sol24h"] is not None and m["sol24h"] > 0),
    ("SOL above its 24h average", lambda m: m["solMA"] is True),
    ("BTC up in the last 6h", lambda m: m["btc6h"] is not None and m["btc6h"] > 0),
    ("BTC up in the last 24h", lambda m: m["btc24h"] is not None and m["btc24h"] > 0),
    ("BTC above its 24h average", lambda m: m["btcMA"] is True),
    ("SOL up 1h AND above 24h average", lambda m: m["sol1h"] is not None and m["sol1h"] > 0 and m["solMA"] is True),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "reports", "market-study.md"))
    args = ap.parse_args()

    btc, sol = Series(fetch_klines("BTCUSDT")), Series(fetch_klines("SOLUSDT"))
    trades = load_trades()
    for e in trades:
        t = e["t_in"]
        e["m"] = dict(btc1h=btc.change(t, 1), btc6h=btc.change(t, 6), btc24h=btc.change(t, 24), btcMA=btc.above_ma(t),
                      sol1h=sol.change(t, 1), sol6h=sol.change(t, 6), sol24h=sol.change(t, 24), solMA=sol.above_ma(t),
                      solDuring=(sol.at(e["t_out"]) / sol.at(t) - 1) * 100 if sol.at(t) and sol.at(e["t_out"]) else None,
                      btcDuring=(btc.at(e["t_out"]) / btc.at(t) - 1) * 100 if btc.at(t) and btc.at(e["t_out"]) else None)
    trades = [e for e in trades if e["m"]["sol24h"] is not None]
    play = [e for e in trades if e["group"] == "playbook"]
    port = [e for e in trades if e["group"] == "portfolio"]
    L = []
    P = L.append
    first = datetime.fromtimestamp(min(e["t_in"] for e in trades), timezone.utc)
    last = datetime.fromtimestamp(max(e["t_in"] for e in trades), timezone.utc)
    P(f"# Market study: paper trades vs BTC and SOL\n")
    P(f"Run {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC. Trades from {first:%b %d %H:%M} to {last:%b %d %H:%M} UTC. "
      f"{len(play)} closed playbook trades, {len(port)} closed main-portfolio buy-now trades. Costs 3%. "
      f"'Trimmed' = average after dropping the best 2% of trades. 'Solid' = trimmed average positive in both the older and newer half, with {MIN_GROUP}+ trades.\n")

    # 1. day table
    P("## 1. Day by day\n")
    P("| Day (UTC) | SOL day | BTC day | Playbook trades | Playbook P&L | Tight trail P&L | Big pool trail P&L | Portfolio P&L |")
    P("|---|---|---|---|---|---|---|---|")
    days = sorted({datetime.fromtimestamp(e["t_in"], timezone.utc).strftime("%Y-%m-%d") for e in trades})
    for d in days:
        d0 = datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
        pt = [e for e in play if datetime.fromtimestamp(e["t_in"], timezone.utc).strftime("%Y-%m-%d") == d]
        po = [e for e in port if datetime.fromtimestamp(e["t_in"], timezone.utc).strftime("%Y-%m-%d") == d]
        tt = sum(e["net"] for e in pt if e["book"] == "trail_tight")
        tp = sum(e["net"] for e in pt if e["book"] == "trail_pool")
        P(f"| {d} | {fmt(sol.change(d0 + 86400, 24))} | {fmt(btc.change(d0 + 86400, 24))} | {len(pt)} | ${sum(e['net'] for e in pt):+.0f} | ${tt:+.0f} | ${tp:+.0f} | ${sum(e['net'] for e in po):+.0f} |")

    # 2. correlations
    P("\n## 2. Does P&L move with the market?\n")
    P("Correlation runs from -1 to +1. Near 0 means no link. Spearman ignores the size of outliers.\n")
    P("| What is compared | Trades or blocks | Pearson | Spearman |")
    P("|---|---|---|---|")
    for name, pool in (("Playbook trade result vs SOL move during the trade", play), ("Playbook trade result vs BTC move during the trade", play),
                       ("Playbook trade result vs SOL change in the 6h before entry", play), ("Playbook trade result vs BTC change in the 24h before entry", play),
                       ("Portfolio trade result vs SOL move during the trade", port)):
        key = "solDuring" if "SOL move" in name else "btcDuring" if "BTC move" in name else "sol6h" if "SOL change" in name else "btc24h"
        pairs = [(e["m"][key], pct(e)) for e in pool if e["m"][key] is not None]
        xs, ys = [p[0] for p in pairs], [p[1] for p in pairs]
        P(f"| {name} | {len(pairs)} | {fmt(pearson(xs, ys), '')} | {fmt(spearman(xs, ys), '')} |")
    # 6-hour blocks
    blocks = defaultdict(float)
    for e in play:
        blocks[int(e["t_in"] // 21600)] += e["net"]
    bx, by, bb = [], [], []
    for k, v in sorted(blocks.items()):
        t0 = k * 21600
        s, b = sol.change(t0 + 21600, 6), btc.change(t0 + 21600, 6)
        if s is not None and b is not None:
            bx.append(s); bb.append(b); by.append(v)
    P(f"| Playbook P&L per 6-hour block vs SOL change in that block | {len(bx)} blocks | {fmt(pearson(bx, by), '')} | {fmt(spearman(bx, by), '')} |")
    P(f"| Playbook P&L per 6-hour block vs BTC change in that block | {len(bb)} blocks | {fmt(pearson(bb, by), '')} | {fmt(spearman(bb, by), '')} |")

    # 3. conditions, pooled
    def cond_table(pool, title):
        P(f"\n### {title} ({len(pool)} trades)\n")
        base = summary(pool)
        P(f"All trades: trimmed {fmt(base['trimmed'])}, win {base['win']:.0f}%, older half {fmt(base['older'])}, newer half {fmt(base['newer'])}.\n")
        P("| Condition at entry | Trades ON | Trimmed ON | Win ON | Older ON | Newer ON | Trades OFF | Trimmed OFF | Win OFF | Verdict |")
        P("|---|---|---|---|---|---|---|---|---|---|")
        for name, fn in CONDITIONS:
            on = [e for e in pool if fn(e["m"])]
            off = [e for e in pool if not fn(e["m"])]
            so, sf = summary(on), summary(off)
            if so["n"] < 5 or sf["n"] < 5:
                continue
            gap = (so["trimmed"] or 0) - (sf["trimmed"] or 0)
            verdict = "solid: ON beats OFF" if so["solid"] and gap > 2 else "ON better, not solid" if gap > 2 else "OFF better" if gap < -2 else "no difference"
            P(f"| {name} | {so['n']} | {fmt(so['trimmed'])} | {so['win']:.0f}% | {fmt(so['older'])} | {fmt(so['newer'])} | {sf['n']} | {fmt(sf['trimmed'])} | {sf['win']:.0f}% | {verdict} |")

    P("\n## 3. Would a market switch have helped?\n")
    P("ON = trades opened while the condition held. OFF = the rest. A switch only helps if ON is clearly better than OFF, and ON is positive in both halves.\n")
    cond_table(play, "All playbooks pooled")
    cond_table(port, "Main portfolio, buy now")
    for book in ("trail_tight", "trail_pool", "be_2x", "quick", "card", "surv_quick"):
        pool = [e for e in play if e["book"] == book]
        if len(pool) >= MIN_GROUP:
            cond_table(pool, pool[0]["label"])

    # 4. plain-language verdict
    P("\n## 4. Verdict\n")
    best = []
    for book in sorted({e["book"] for e in play}):
        pool = [e for e in play if e["book"] == book]
        if len(pool) < MIN_GROUP:
            continue
        for name, fn in CONDITIONS:
            on = summary([e for e in pool if fn(e["m"])])
            off = summary([e for e in pool if not fn(e["m"])])
            if on["n"] >= MIN_GROUP and on["solid"] and (on["trimmed"] or 0) - (off["trimmed"] or 0) > 2:
                best.append((pool[0]["label"], name, on["n"], on["trimmed"], off["trimmed"]))
    if best:
        P("Conditions that pass the solid test (ON positive in both halves, 30+ trades, beats OFF by over 2 points per trade):\n")
        for lab, name, n, a, b in best:
            P(f"- {lab}: {name}. {n} trades ON, trimmed {fmt(a)} vs {fmt(b)} OFF.")
    else:
        P("No condition passed the solid test for any playbook. A market switch is not supported by this data yet.")
    with open(args.out, "w") as fh:
        fh.write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
