#!/usr/bin/env python3
"""What worked: compare winners and losers on every number saved at scan time.

Reads data/track.json (main portfolio "buy now" trades that are closed) and writes data/insights.json.
Plain statistics, no AI. For each number: split the trades into three buckets (low, mid, high),
and for each yes/no flag: on vs off. A bucket is "solid" when it has 30+ trades, beats the rest
by over 3 points per trade, and does so in BOTH the older and the newer half of the data.
Solid buckets become suggested rules. Trimmed = average after dropping the best 2% of trades.

Usage: python3 scanner/learn.py [--out data/insights.json]
"""
import argparse
import json
import os
import statistics as st
from datetime import datetime, timezone

COST = 0.03
MIN_GROUP, MIN_GAP = 30, 3.0
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# (key, label, kind). kind: "num", "bool", "cat". Keys match metricOf() in index.html.
METRICS = [
    ("age_h", "Age at scan (hours)", "num"), ("firstSeenAgeH", "Age when first seen (hours)", "num"),
    ("mc", "Market cap at scan", "num"), ("liq", "Pool at scan", "num"), ("liqToMc", "Pool as % of market cap", "num"),
    ("holders", "Holders", "num"), ("buyers24", "Unique buyers, 24h", "num"), ("tradesPerBuyer", "Buys per buyer, 24h", "num"),
    ("buys24", "Buys, 24h", "num"), ("sells24", "Sells, 24h", "num"), ("volToMc", "24h volume / market cap", "num"),
    ("chg1", "1h change at scan (%)", "num"), ("chg6", "6h change at scan (%)", "num"), ("chg24", "24h change at scan (%)", "num"),
    ("gt_score", "GeckoTerminal score", "num"), ("warns", "Warnings on the card", "num"),
    ("bigBuyUsd", "Big buys, 24h ($)", "num"), ("bigSellUsd", "Big sells, 24h ($)", "num"), ("bigNet", "Big buys minus big sells ($)", "num"),
    ("bigWallets", "Wallets behind big trades", "num"), ("hourUtc", "Hour of day (UTC)", "num"),
    ("runup6h", "Run-up over 6h before scan (%)", "num"), ("runup2h", "Run-up over 2h before scan (%)", "num"),
    ("distSupport", "Distance from support (%)", "num"), ("fromHigh6h", "Below the 6h high (%)", "num"),
    ("swing", "Average candle swing (%)", "num"), ("volTrend", "Volume trend (last 1h / hour before)", "num"),
    ("higherLows", "Higher lows in the last hour (0-4)", "num"), ("greenShare", "Green candles, last 2h (share)", "num"),
    ("hasX", "Has an X account", "bool"), ("hasTg", "Has a Telegram", "bool"), ("hasWeb", "Has a website", "bool"),
    ("whale", "Whale buy over $5K seen", "bool"), ("boosted", "Paid DexScreener boost", "bool"), ("pons", "Pons launch", "bool"),
    ("planOk", "Card had an entry plan", "bool"),
    ("source", "Source", "cat"), ("label", "Label", "cat"), ("weekday", "Weekday (0 = Monday)", "cat"),
]


def metric(e, key):
    f = e.get("features") or {}
    ch = f.get("chart") or {}
    if key == "mc": return e.get("mc0")
    if key == "liq": return e.get("liq0")
    if key == "warns": return e.get("warns")
    if key == "volToMc": return (f.get("vol24") / e["mc0"]) if f.get("vol24") is not None and e.get("mc0") else None
    if key == "bigNet": return (f.get("bigBuyUsd") or 0) - (f.get("bigSellUsd") or 0)
    if key == "boosted": return bool(f.get("boosts"))
    if key == "label":
        lab = (e.get("label") or "").lower()
        return "utility claim" if "utility" in lab and "meme" not in lab else "meme" if "meme" in lab else "none"
    if key == "source": return e.get("source")
    if key in ch: return ch.get(key)
    return f.get(key)


def net_pct(e):
    return ((e.get("cash") or 0) * (1 - COST) - 1) * 100  # closed: pos is 0


def trimmed(vals):
    if not vals:
        return None
    k = max(1, round(len(vals) * 0.02)) if len(vals) >= 10 else 0
    v = sorted(vals)
    return st.mean(v[: len(v) - k]) if k else st.mean(v)


def stats(trades):
    if not trades:
        return dict(n=0, trimmed=None, win=None, older=None, newer=None)
    ts = sorted(trades, key=lambda e: e["entryT"])
    h = len(ts) // 2
    vals = [net_pct(e) for e in ts]
    return dict(n=len(ts), trimmed=trimmed(vals), win=sum(1 for v in vals if v > 0) / len(vals) * 100,
                older=trimmed(vals[:h]) if h else None, newer=trimmed(vals[h:]) if h else None)


def compare(inside, rest):
    """Two tiers. "helps": the bucket loses less than the rest by MIN_GAP, in both halves, with MIN_GROUP trades.
    "solid": the same, AND the bucket actually makes money in both halves. Only solid buckets are worth trading on."""
    a, b = stats(inside), stats(rest)
    gap = (a["trimmed"] - b["trimmed"]) if a["n"] and b["n"] else None
    both = (a["older"] is not None and b["older"] is not None and a["newer"] is not None and b["newer"] is not None)
    helps = (a["n"] >= MIN_GROUP and b["n"] >= 10 and gap is not None and gap > MIN_GAP and both
             and a["older"] > b["older"] and a["newer"] > b["newer"])
    solid = helps and a["older"] > 0 and a["newer"] > 0
    return dict(a, gap=gap, helps=helps, solid=solid, restTrimmed=b["trimmed"])


def fmt_num(v):
    v = float(v)
    if abs(v) >= 1e6: return f"{v / 1e6:.1f}M"
    if abs(v) >= 1e4: return f"{v / 1e3:.0f}K"
    if abs(v) >= 100: return f"{v:.0f}"
    if abs(v) >= 10: return f"{v:.1f}"
    return f"{v:.2f}"


def study(trades):
    out = []
    for key, label, kind in METRICS:
        rows = [(metric(e, key), e) for e in trades]
        rows = [(v, e) for v, e in rows if v is not None]
        if len(rows) < MIN_GROUP * 2:
            continue
        buckets = []
        if kind == "num":
            vals = sorted(v for v, _ in rows)
            lo, hi = vals[len(vals) // 3], vals[2 * len(vals) // 3]
            if lo == hi:  # most values equal: split at the value
                groups = [("equal to " + fmt_num(lo), None, None, [e for v, e in rows if v == lo], lambda v: v == lo),
                          ("above " + fmt_num(lo), lo, None, [e for v, e in rows if v > lo], None),
                          ("below " + fmt_num(lo), None, lo, [e for v, e in rows if v < lo], None)]
            else:
                groups = [("under " + fmt_num(lo), None, lo, [e for v, e in rows if v < lo], None),
                          (fmt_num(lo) + " to " + fmt_num(hi), lo, hi, [e for v, e in rows if lo <= v < hi], None),
                          (fmt_num(hi) + " and up", hi, None, [e for v, e in rows if v >= hi], None)]
            for name, blo, bhi, inside, _ in groups:
                if not inside:
                    continue
                ids = {id(e) for e in inside}
                c = compare(inside, [e for _, e in rows if id(e) not in ids])
                buckets.append(dict(name=name, rule=dict(key=key, lo=blo, hi=bhi), **c))
        else:
            values = sorted({v for v, _ in rows}, key=lambda x: str(x))
            for val in values:
                inside = [e for v, e in rows if v == val]
                rest = [e for v, e in rows if v != val]
                if len(inside) < 5:
                    continue
                name = ("yes" if val else "no") if kind == "bool" else str(val)
                c = compare(inside, rest)
                buckets.append(dict(name=name, rule=dict(key=key, eq=val), **c))
        out.append(dict(key=key, label=label, kind=kind, n=len(rows), buckets=buckets))
    return out


def passes(e, rule):
    v = metric(e, rule["key"])
    if v is None:
        return False
    if "eq" in rule:
        return v == rule["eq"]
    if rule.get("lo") is not None and v < rule["lo"]:
        return False
    if rule.get("hi") is not None and v >= rule["hi"]:
        return False
    return True


def rule_text(label, b):
    r = b["rule"]
    if "eq" in r:
        return f"{label}: {b['name']}"
    return f"{label}: {b['name']}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "insights.json"))
    args = ap.parse_args()
    with open(os.path.join(ROOT, "data", "track.json")) as fh:
        track = json.load(fh)
    trades = [e for e in track.values() if e.get("plan") == "v2" and e.get("strategy") == "now" and e.get("final")
              and e.get("entry") and e.get("outcome") != "Bad data"]
    base = stats(trades)
    features = study(trades)
    helps, solid = [], []
    for f in features:
        for b in f["buckets"]:
            if b["helps"]:
                row = dict(text=rule_text(f["label"], b), key=f["key"], label=f["label"], bucket=b["name"], rule=b["rule"],
                           n=b["n"], trimmed=b["trimmed"], rest=b["restTrimmed"], gap=b["gap"], win=b["win"],
                           older=b["older"], newer=b["newer"], solid=b["solid"])
                helps.append(row)
                if b["solid"]:
                    solid.append(row)
    helps.sort(key=lambda s: -s["gap"])
    solid.sort(key=lambda s: -s["gap"])
    # Combined filter: the top "helps" rules stacked one at a time, as long as 30+ trades remain. One rule per number.
    combo, chosen, used = None, [], set()
    pool = trades
    for s in helps:
        if s["key"] in used or len(chosen) >= 4:
            continue
        nxt = [e for e in pool if passes(e, s["rule"])]
        if len(nxt) >= MIN_GROUP:
            pool, chosen = nxt, chosen + [s]
            used.add(s["key"])
    if chosen:
        ids = {id(e) for e in pool}
        c = compare(pool, [e for e in trades if id(e) not in ids])
        combo = dict(rules=[s["text"] for s in chosen], ruleset=[s["rule"] for s in chosen], **c)
    out = dict(updated=datetime.now(timezone.utc).isoformat(), what="Main portfolio, buy now, closed trades since Oct 6 2026",
               minGroup=MIN_GROUP, minGap=MIN_GAP, base=base, suggestions=solid, leastBad=helps[:12], combo=combo, features=features)
    with open(args.out, "w") as fh:
        json.dump(out, fh, separators=(",", ":"))
    print(f"{base['n']} trades, base trimmed {base['trimmed']:+.1f}%, win {base['win']:.0f}%, older {base['older']:+.1f}% newer {base['newer']:+.1f}%")
    print(f"{len(solid)} rules make money in both halves; {len(helps)} lose less than the rest")
    for s in helps[:12]:
        print(f"{'SOLID ' if s['solid'] else 'helps '} {s['text']}: {s['n']} trades, {s['trimmed']:+.1f}% vs {s['rest']:+.1f}% rest (gap {s['gap']:+.1f}), win {s['win']:.0f}%, halves {s['older']:+.1f}/{s['newer']:+.1f}")
    if combo:
        print(f"COMBO  {' + '.join(combo['rules'])}: {combo['n']} trades, {combo['trimmed']:+.1f}% vs {combo['restTrimmed']:+.1f}%, halves {combo['older']:+.1f}/{combo['newer']:+.1f}, makes money={combo['solid']}")


if __name__ == "__main__":
    main()
