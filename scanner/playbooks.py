#!/usr/bin/env python3
"""Playbooks: complete bot setups paper-traded side by side on the same coins (Rainer, Oct 6 2026).

Every rule here is one the real bot can copy 1:1 with Jupiter: a market buy at the check minute or a limit
buy at support, then take-profit legs, a stop, a trailing stop and a time stop, plus money rules (bet size,
max open coins, a daily loss limit that pauses buying). Results live in data/books.json; the page shows a table.
"""
import time
from datetime import datetime, timezone

import scan as S

COST = 0.03          # the page takes 3% off every trade for fees and slippage
MIN_AGE_S = 900      # a trade is first re-checked 15 minutes after the buy
BUDGET_S = 240
CARD = [{"part": 0.5, "tp": 2}, {"part": 0.4, "tp": 3}, {"part": 0.1, "trail": 0.4}]

BOOKS = {
    "card": dict(label="Card plan as is", take="pass", entry="market", legs=CARD, stop="card", timeH=14 * 24, size=50, maxOpen=5, dayLoss=150,
                 desc="Every pass. Market buy. 50% sells at 2x, 40% at 3x, 10% trails 40%. Stop under the 2-hour low, or 30%."),
    "entry_limit": dict(label="Entry plan only, limit buy", take="plan", entry="limit", legs=CARD, stop="card", timeH=14 * 24, size=50, maxOpen=5, dayLoss=150,
                        desc="Only passes with a suggested entry. Limit buy at support, good for 12 hours. Card exits."),
    "entry_market": dict(label="Entry plan only, market buy", take="plan", entry="market", legs=CARD, stop="card", timeH=14 * 24, size=50, maxOpen=5, dayLoss=150,
                         desc="Only passes with a suggested entry, but bought at once. Card exits."),
    "nochase": dict(label="No chasers", take="nochase", entry="market", legs=[{"part": 0.5, "tp": 1.5}, {"part": 0.4, "tp": 2}, {"part": 0.1, "trail": 0.3}],
                    stop="card", timeH=14 * 24, size=50, maxOpen=5, dayLoss=150,
                    desc="Skips coins up 50%+ in the last 2 hours or falling in the last hour. Market buy. 50% at 1.5x, 40% at 2x, 10% trails 30%."),
    "freshdip": dict(label="Fresh dip", take="fresh_plan", entry="limit", legs=[{"part": 1.0, "tp": 1.5}], stop=0.75, timeH=6, size=50, maxOpen=5, dayLoss=150,
                     desc="Fresh graduates with a suggested entry. Limit buy at support. Sell all at 1.5x, stop 25%, out after 6 hours."),
    "quick": dict(label="Quick flip", take="pass", entry="market", legs=[{"part": 1.0, "tp": 1.5}], stop=0.75, timeH=4, size=50, maxOpen=5, dayLoss=150,
                  desc="Every pass. Market buy. Sell all at 1.5x, stop 25%, out after 4 hours."),
    "surv_quick": dict(label="Survivor quick", take="surv", entry="market", legs=[{"part": 1.0, "tp": 1.25}], stop=0.85, timeH=12, size=50, maxOpen=10, dayLoss=100,
                       desc="Coins that already lasted 6 to 48 hours and held up. Market buy. Sell all at 1.25x, stop 15%, out after 12 hours."),
    "surv_swing": dict(label="Survivor swing", take="surv", entry="market", legs=[{"part": 0.5, "tp": 1.5}, {"part": 0.3, "tp": 2}, {"part": 0.2, "trail": 0.3}],
                       stop=0.75, timeH=48, size=50, maxOpen=10, dayLoss=100,
                       desc="The same coins. Market buy. 50% sells at 1.5x, 30% at 2x, 20% trails 30%. Stop 25%, out after 48 hours."),
    "curve_run": dict(label="Curve run", take="curve", entry="market", legs=None, legsFn="to90", stop=0.70, timeH=1.5, size=50, maxOpen=5, dayLoss=100,
                      desc="Coins still on the pump.fun curve, 30-80% full. Market buy. Sell all at the price the curve has when 90% full, stop 30%, out after 90 minutes."),
    "curve_quick": dict(label="Curve quick", take="curve", entry="market", legs=[{"part": 1.0, "tp": 1.5}], stop=0.75, timeH=0.5, size=50, maxOpen=5, dayLoss=100,
                        desc="The same curve coins. Market buy. Sell all at 1.5x, stop 25%, out after 30 minutes."),
    # ---- Adjusted playbooks (Rainer, Oct 9 2026). Picked by replaying 447 fast-scan trades, 58 curve and 11 survivor trades on
    # real 1- and 5-minute candles over 5,440 settings. None was green in both halves at a 10% stop slippage; the trailing-stop
    # family turned green at 5% slippage, so these test live whether real stops fill well enough. Forward test, not winners.
    "trail_tight": dict(label="v2 Tight trail", take="notfalling", entry="market", legs=[{"part": 1.0, "trail": 0.15, "act": 1.2}],
                        stop=0.95, timeH=1, size=50, maxOpen=10, dayLoss=150, v2=True,
                        desc="Coins not falling in the last hour. Market buy. Stop 5% under the buy. Once up 20%, a 15% trailing stop takes over. Out after 1 hour."),
    "trail_pool": dict(label="v2 Trail, big pool", take="pool20nf", entry="market", legs=[{"part": 1.0, "trail": 0.15, "act": 1.2}],
                       stop=0.90, timeH=1, size=50, maxOpen=10, dayLoss=150, v2=True,
                       desc="Pool $20K+ and not falling in the last hour. Market buy. Stop 10%. Once up 20%, a 15% trailing stop takes over. Out after 1 hour."),
    "be_2x": dict(label="v2 2x with break-even", take="pool20nf", entry="market", legs=[{"part": 1.0, "tp": 2.0}], be=1.3,
                  stop=0.85, timeH=4, size=50, maxOpen=10, dayLoss=150, v2=True,
                  desc="Pool $20K+ and not falling in the last hour. Market buy. Stop 15%, moved up to the buy price once up 30%. Sell all at 2x. Out after 4 hours."),
    "sell30": dict(label="v2 Sell all at +30%", take="pool20nf", entry="market", legs=[{"part": 1.0, "tp": 1.3}],
                   stop=0.90, timeH=4, size=50, maxOpen=10, dayLoss=150, v2=True,
                   desc="Rainer's idea. Pool $20K+ and not falling in the last hour. Market buy. Sell everything at +30%. Stop 10%. Out after 4 hours."),
    "surv_2x": dict(label="v2 Survivor 2x", take="surv", entry="market", legs=[{"part": 1.0, "tp": 2.0}], be=1.3,
                    stop=0.75, timeH=4, size=50, maxOpen=10, dayLoss=100, v2=True,
                    desc="Survivor coins. Market buy. Stop 25%, moved up to the buy price once up 30%. Sell all at 2x. Out after 4 hours. Based on only 11 trades."),
    "big": dict(label="Big coins (unproven)", take="big", entry="market", legs=[{"part": 0.5, "tp": 1.3}, {"part": 0.5, "tp": 1.5}], stop=0.85, timeH=48, size=100, maxOpen=5, dayLoss=200,
                desc="Safe coins the scanner rejects only for a market cap over $5M. Market buy. 50% at 1.3x, 50% at 1.5x, stop 15%, out after 48 hours."),
}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def takes(book, c, src_key):
    t = book["take"]
    ok = bool((c.get("order") or {}).get("ok"))
    if t == "big":
        return src_key == "big"
    if src_key == "big":
        return False
    if t == "surv":
        return src_key == "survivors"
    if t == "curve":
        return src_key == "curve" and (c.get("curveProgress") or 0) <= 80
    if src_key in ("survivors", "curve"):
        return False  # survivors and curve coins have their own playbooks, so the fresh-coin playbooks stay clean
    if t == "pass":
        return True
    if t == "plan":
        return ok
    if t == "fresh_plan":
        return src_key == "fresh" and ok
    # Adjusted playbooks (Oct 9 2026), picked by replaying 450+ fast-scan trades on real candles:
    if t == "pool20":      # pool money at least $20K when checked
        return (c.get("liq") or 0) >= 20000
    if t == "notfalling":  # not falling in the last hour
        return (c.get("chg1") or 0) >= 0
    if t == "pool20nf":    # both
        return (c.get("liq") or 0) >= 20000 and (c.get("chg1") or 0) >= 0
    if t == "nochase":
        ch = c.get("chartF") or {}
        if ch.get("runup2h") is None:
            return False  # not enough chart history to tell
        return ch["runup2h"] < 50 and (c.get("chg1") or 0) >= 0
    return False


def mult(e):
    if not e.get("entry"):
        return None
    now = e["now"] if e.get("now") is not None else e["entry"]
    return (e.get("cash") or 0) + (e.get("pos") or 0) * now / e["entry"]


def realized_today(trades, name):
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    total = 0.0
    for e in trades.values():
        if e["book"] == name and e.get("final") and e.get("entry") and e.get("exit"):
            if datetime.fromtimestamp(e["exit"], timezone.utc).strftime("%Y-%m-%d") == day:
                total += e["size"] * (mult(e) * (1 - COST) - 1)
    return total


def consider(books, cards):
    """cards: list of (card, source_key) checked this cycle. Opens paper trades in every playbook that takes the coin."""
    trades = books.setdefault("trades", {})
    cfg = books.setdefault("books", {})
    opened = 0
    for name, b in BOOKS.items():
        cfg[name] = dict(label=b["label"], desc=b["desc"], size=b["size"], maxOpen=b["maxOpen"], dayLoss=b["dayLoss"],
                         skipped=cfg.get(name, {}).get("skipped", {}))
        for c, src in cards:
            key = f"{name}:{c['token']}"
            if key in trades or not c.get("price") or not takes(b, c, src):
                continue
            open_n = sum(1 for e in trades.values() if e["book"] == name and not e.get("final"))
            if open_n >= b["maxOpen"]:
                cfg[name]["skipped"]["max open"] = cfg[name]["skipped"].get("max open", 0) + 1
                continue
            if realized_today(trades, name) <= -b["dayLoss"]:
                cfg[name]["skipped"]["daily loss limit"] = cfg[name]["skipped"].get("daily loss limit", 0) + 1
                continue
            o = c.get("order") or {}
            legs = b["legs"]
            if b.get("legsFn") == "to90":  # sell where the curve is 90% full: a fixed price target, known at the buy
                legs = [{"part": 1.0, "tp": round(S.curve_ratio((c.get("curveProgress") or 0) / 100, 0.90), 3)}]
            e = dict(book=name, token=c["token"], pair=c["pair"], chain=c["chain"], source=src, symbol=c["symbol"], name=c["name"],
                     chart=c.get("chart"), logged=now_iso(), size=b["size"], price0=c["price"], liq0=c["liq"], mc0=c["mc"],
                     legs=legs, timeH=b["timeH"], stopRule=b["stop"], orderStop=o.get("stop") if o.get("ok") else None,
                     be=b.get("be"), candle=60 if b.get("v2") and b["timeH"] <= 2 else 900,  # old playbooks keep 15-minute candles
                     entry=None, entryT=None, limit=None, stop0=None, now=None, liq=None, cash=0.0, pos=1.0, best=None, exit=None,
                     final=False, checked=None, outcome="Open", why="",
                     features=dict(firstSeenAgeH=c.get("firstSeenAgeH"), planOk=o.get("ok"), warns=len(c.get("warns") or []),
                                   chg1=c.get("chg1"), runup2h=(c.get("chartF") or {}).get("runup2h"), curveProgress=c.get("curveProgress")))
            if b["entry"] == "limit":
                e.update(limit=o["entry"], outcome="Waiting for fill", why=f"limit buy at {S.money(o['entry'])}")
            else:
                fill(e, c["price"], time.time())
            trades[key] = e
            opened += 1
    return opened


def fill(e, price, t):
    stop = e["orderStop"] if e["stopRule"] == "card" else price * e["stopRule"]
    if not stop or stop >= price:
        stop = price * (S.NOW_STOP if e["stopRule"] == "card" else e["stopRule"])
    e.update(entry=price, entryT=t, stop0=stop, outcome="Open")


def simulate(e, candles):
    r = S.run_legs(candles, e["entry"], e["entryT"], e["stop0"], e["legs"], e["timeH"] * 3600, size=e.get("candle", 900), be=e.get("be"))
    st = r["st"]
    hits = sum(1 for s in st if s == "tp")
    if all(s == "open" for s in st):
        out = "Open"
    elif all(s == "stop" for s in st):
        out = "Stop hit"
    elif "time" in st:
        out = "Time stop" + (f" after {hits} target{'s' if hits != 1 else ''}" if hits else "")
    elif all(s != "open" for s in st):
        out = "All targets hit" if all(s in ("tp", "trail") for s in st) else f"{hits} target{'s' if hits != 1 else ''} hit, rest stopped"
    else:
        out = f"{hits} target{'s' if hits != 1 else ''} hit, rest running"
    e.update(cash=r["cash"], pos=r["pos"], best=r["best"], exit=r["exit"], outcome=out, final=r["pos"] == 0)


def check_books(books, cache, say=S.say):
    """Re-check open playbook trades. cache: {(chain, token): ((price, liq), candles)}, shared with the main portfolio."""
    trades = books.get("trades", {})
    todo = [e for e in trades.values() if not e.get("final") and S.ts_of(e["logged"]) < time.time() - MIN_AGE_S]
    todo.sort(key=lambda e: (e.get("checked") or "", e["logged"]))
    started, n = time.time(), 0
    for e in todo:
        if time.time() - started > BUDGET_S:
            say(f"playbooks: time budget used, {len(todo) - n} trades wait")
            break
        key = (e["chain"], e["token"], e.get("candle", 900))
        if key not in cache:
            try:
                p = S.find_pair(e["token"], e["chain"])
                price = (S.num(p.get("priceUsd")), (p.get("liquidity") or {}).get("usd") or 0) if p else (0, 0)
            except Exception:
                price = (e.get("now"), e.get("liq"))
            tf = "minute?aggregate=1&limit=1000" if e.get("candle") == 60 else "minute?aggregate=15&limit=1000" if (time.time() - S.ts_of(e["logged"])) / 86400 <= 10 else "hour?limit=1000"
            try:
                d = S.get_slow(f"{S.GT}/{e['chain']}/pools/{e['pair']}/ohlcv/{tf}")
                candles = ((d.get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
            except Exception:
                candles = None
            cache[key] = (price, candles)
            time.sleep(S.PAUSE)
        (now_p, liq), candles = cache[key]
        e["now"], e["liq"] = now_p, liq
        if candles:
            if not e.get("entry") and e.get("limit"):
                S.watch_fill(e, candles)  # sets entry/entryT on a fill, or Missed after 12 hours
                if e.get("entry"):
                    fill(e, e["entry"], e["entryT"])
            if e.get("entry"):
                simulate(e, candles)
        if e.get("entry") and not e["final"] and e.get("source") == "curve" and liq and liq >= 1000 and candles:
            # A curve coin with pool money has graduated: the curve stopped. The bot would sell at the last curve price.
            last = sorted(candles)[-1][4]
            e.update(cash=e["cash"] + e["pos"] * last / e["entry"], pos=0.0, outcome="Graduated, sold at the last curve price", exit=int(time.time()), final=True)
        if e.get("entry") and not e["final"]:
            if (e.get("best") or 0) > 100 or (now_p and now_p / e["entry"] > 100):
                e.update(cash=1.0, pos=0.0, outcome="Bad data", exit=int(time.time()), final=True)
            elif e.get("source") == "curve" and now_p and now_p / e["entry"] < 0.1:
                e.update(cash=e["cash"] + e["pos"] * now_p / e["entry"], pos=0.0, outcome="Dead", exit=int(time.time()), final=True)
            elif e.get("source") != "curve" and ((liq is not None and liq < 1000) or (now_p and now_p / e["entry"] < 0.1)):
                e.update(cash=e["cash"] + e["pos"] * (now_p or 0) / e["entry"], pos=0.0, outcome="Dead", exit=int(time.time()), final=True)
            elif time.time() > e["entryT"] + e["timeH"] * 3600 + 7200:
                e.update(cash=e["cash"] + e["pos"] * (now_p or 0) / e["entry"], pos=0.0, outcome="Time stop", exit=int(time.time()), final=True)
        e["checked"] = now_iso()
        n += 1
    books["updated"] = now_iso()
    return n
