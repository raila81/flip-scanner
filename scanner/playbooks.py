#!/usr/bin/env python3
"""Playbooks: complete bot setups paper-traded side by side on the same coins (Rainer, Oct 6 2026).

Every rule here is one the real bot can copy 1:1 with Jupiter: a market buy at the check minute or a limit
buy at support, then take-profit legs, a stop, a trailing stop and a time stop, plus money rules (bet size,
max open coins, a daily loss limit that pauses buying). Results live in data/books.json; the page shows a table.
"""
import glob
import json
import os
import re
import time
import urllib.request
from datetime import datetime, timezone

import scan as S

COST = 0.03          # the page takes 3% off every trade for fees and slippage
MIN_AGE_S = 900      # a trade is first re-checked 15 minutes after the buy
BUDGET_S = 240
CARD = [{"part": 0.5, "tp": 2}, {"part": 0.4, "tp": 3}, {"part": 0.1, "trail": 0.4}]

# ---- Famous names (Rainer, Oct 17 2026). The Oct 17 review found that all of "v2 Tight trail"'s profit came from coins named after
# known brands, people or memes (YouTube, MrBeast, NASA, Samsung, GitHub, Rockstar, IShowSpeed, FOMO): +$1,132 on 70 trades, while the
# other 338 trades lost $347. Two paper books test that on purpose. "exact" = the coin's name or ticker IS the famous term (YouTube,
# NASA, MrBeast); "any" = the term appears somewhere in the name (Flying Tesla Roadster, Trump in Batter), which lost in the review.
FAMOUS_TERMS = (
    # companies, brands, products
    "youtube|google|github|samsung|nasa|spacex|tesla|apple|iphone|microsoft|windows|amazon|meta|facebook|instagram|tiktok|netflix|"
    "disney|pixar|nintendo|playstation|xbox|sony|rockstar|gta|gta ?6|minecraft|roblox|fortnite|pokemon|lego|nike|adidas|mcdonald'?s?|"
    "burger king|kfc|starbucks|coca ?cola|pepsi|red ?bull|ferrari|lamborghini|porsche|bmw|mercedes|toyota|walmart|costco|ikea|visa|"
    "mastercard|paypal|stripe|uber|airbnb|spotify|reddit|discord|telegram|whatsapp|snapchat|twitch|kick|openai|chatgpt|gpt|claude|"
    "anthropic|gemini|grok|xai|nvidia|amd|intel|oracle|ibm|coinbase|binance|kraken|robinhood|wikipedia|pornhub|onlyfans|"
    # people
    "elon|musk|trump|melania|barron|biden|obama|putin|kim ?jong|zelensky|kanye|drake|taylor ?swift|beyonce|rihanna|kardashian|kylie|"
    "ronaldo|messi|lebron|mbappe|neymar|jordan|tyson|mcgregor|mr ?beast|i ?show ?speed|speed|pewdiepie|kai ?cenat|logan ?paul|"
    "jake ?paul|andrew ?tate|tate|joe ?rogan|rogan|oprah|zuckerberg|zuck|bezos|bill ?gates|jensen|saylor|vitalik|cz|altman|buffett|"
    "powell|satoshi|nakamoto|snoop|eminem|bieber|bad ?bunny|travis ?scott|kendrick|hamilton|verstappen|einstein|pope|jesus|"
    # characters and memes
    "pepe|doge|shiba|wojak|chad|gigachad|bonk|wif|popcat|mog|brett|spongebob|patrick|squidward|pikachu|mario|luigi|sonic|batman|"
    "joker|superman|spiderman|hulk|thor|goku|naruto|minions|shrek|homer|simpson|rick|morty|peppa|kermit|garfield|snoopy|"
    "fomo|useless|hodl|wagmi|degen|rekt|moon|giga|sigma|rizz|skibidi|ohio|"
    # institutions and events
    "white ?house|pentagon|cia|fbi|fed|federal ?reserve|oscars|super ?bowl|world ?cup|olympics|halloween|christmas|thanksgiving"
)
FAMOUS = re.compile(r"\b(" + FAMOUS_TERMS + r")\b", re.I)
FAMOUS_EXACT = re.compile(r"^\W*(?:the\s+)?(?:\$)?(" + FAMOUS_TERMS + r")(?:\s*(?:coin|token|games|inc|ai))?\W*$", re.I)


def famous_kind(c):
    """'exact' when the coin's name or ticker is a famous term by itself, 'any' when a term appears inside, else None."""
    name, sym = (c.get("name") or ""), (c.get("symbol") or "")
    if FAMOUS_EXACT.match(name) or FAMOUS_EXACT.match(sym):
        return "exact"
    if FAMOUS.search(name) or FAMOUS.search(sym):
        return "any"
    return None


# ---- Holder screen (Rainer, Oct 27 2026). Most real-money losses are one-swap pool drains: a wallet sells and takes 50-85% of the
# pool's SOL in one block. Rebuilt on chain for 241 Season 2 coins: when one wallet already held enough at the buy to take 50%+ of the
# pool's SOL (h / (R + h), h = its tokens, R = the pool's tokens), 93% were drained within an hour. Two cheap Helius calls per coin.
RPC_URL = os.environ.get("FEED_RPC") or "https://api.mainnet-beta.solana.com"
_RISK = {}


def _rpc(method, params):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(RPC_URL, data=body, headers={"Content-Type": "application/json", "User-Agent": "flip-scanner/1.0"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read()).get("result")


def drain_risk(c):
    """Share of the pool's SOL the biggest wallet (d1), the top 5 (d5) and top 10 (d10) would take by selling all at once.
    Reads the coin's 20 biggest token accounts; the pool's own vault (owned by the pair address) gives R. None when unknown."""
    tok, pool = c.get("token"), c.get("pair")
    if c.get("chain") != "solana" or not tok or not pool:
        return None
    hit = _RISK.get(tok)
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    res = None
    try:
        top = (_rpc("getTokenLargestAccounts", [tok]) or {}).get("value") or []
        info = (_rpc("getMultipleAccounts", [[a["address"] for a in top], {"encoding": "jsonParsed"}]) or {}).get("value") or []
        R, owners = 0.0, {}
        for v in info:
            try:
                p = v["data"]["parsed"]["info"]
                amt = float(p["tokenAmount"]["uiAmount"] or 0)
            except (TypeError, KeyError, ValueError):
                continue
            if p["owner"] == pool:
                R += amt
            else:
                owners[p["owner"]] = owners.get(p["owner"], 0) + amt
        if R > 0:
            hs = sorted(owners.values(), reverse=True)
            share = lambda h: round(h / (R + h), 3)
            res = dict(d1=share(hs[0]) if hs else 0.0, d5=share(sum(hs[:5])), d10=share(sum(hs[:10])))
    except Exception:
        res = None
    _RISK[tok] = (time.time(), res)
    return res


def calm(c):
    """Calm coin (Oct 27 2026 study): not a famous name, not falling in the last hour, at most 2,000 buyers in 24h.
    Hype coins (famous names, thousands of bot buyers) were the ones drained."""
    b = c.get("buyers24") or 0
    return famous_kind(c) != "exact" and (c.get("chg1") or 0) >= 0 and 0 < b <= 2000


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
    # ---- Stop-slippage twins (Rainer, Oct 15 2026). Each copies every "v2 Tight trail" trade exactly (same coin, same buy, same stop and
    # trail) and only changes how badly a stop sale fills: 15% and 20% worse than the stop price instead of 10%. Same trades, so the
    # gap between the three rows is purely the fill quality. They start with the whole Tight trail history re-priced (backfill_mirrors).
    "trail_tight_s15": dict(label="v2 Tight trail, stops fill 15% worse", mirror="trail_tight", slip=0.15, take="mirror", entry="market",
                            legs=[{"part": 1.0, "trail": 0.15, "act": 1.2}], stop=0.95, timeH=1, size=50, maxOpen=10, dayLoss=150, v2=True,
                            desc="Twin of v2 Tight trail: the same trades, but every stop or trailing-stop sale fills 15% worse than its price (Tight trail assumes 10%)."),
    "trail_tight_s20": dict(label="v2 Tight trail, stops fill 20% worse", mirror="trail_tight", slip=0.20, take="mirror", entry="market",
                            legs=[{"part": 1.0, "trail": 0.15, "act": 1.2}], stop=0.95, timeH=1, size=50, maxOpen=10, dayLoss=150, v2=True,
                            desc="Twin of v2 Tight trail: the same trades, but every stop or trailing-stop sale fills 20% worse than its price (Jupiter's default stop slippage is up to 20%)."),
    "famous_exact": dict(label="v2 Famous name (exact)", take="famous_exact", entry="market", legs=[{"part": 1.0, "trail": 0.15, "act": 1.2}],
                         stop=0.95, timeH=1, size=50, maxOpen=10, dayLoss=150, v2=True,
                         desc="Coins whose name or ticker IS a famous brand, person or meme (YouTube, NASA, MrBeast, FOMO) and not falling in the last hour. Same exits as Tight trail: stop 5%, 15% trail once up 20%, out after 1 hour."),
    "famous_any": dict(label="v2 Famous name (anywhere)", take="famous_any", entry="market", legs=[{"part": 1.0, "trail": 0.15, "act": 1.2}],
                       stop=0.95, timeH=1, size=50, maxOpen=10, dayLoss=150, v2=True,
                       desc="Coins with a famous term somewhere in the name (Flying Tesla Roadster, Trump in Batter), not falling in the last hour. Same exits as Tight trail. The review says these lose; this checks it."),
    # ---- Meta bursts (Rainer, Oct 17 2026). fast.py spots a "meta" when 3+ coins with the same new name appear on pump.fun within
    # 15 minutes (bots copying a famous tweet). Two coins get a card: the first one created and the one with the most buyers.
    "meta_first": dict(label="Meta burst: first coin", take="meta_first", entry="market", legs=[{"part": 1.0, "trail": 0.25, "act": 1.3}],
                       stop=0.75, timeH=2, size=50, maxOpen=5, dayLoss=150, v2=True,
                       desc="The first coin created in a name burst (4+ coins by 3+ creators with the same new name within 15 minutes). Market buy. Stop 25%. Once up 30%, a 25% trailing stop takes over. Out after 2 hours."),
    "meta_leader": dict(label="Meta burst: most buyers", take="meta_leader", entry="market", legs=[{"part": 1.0, "trail": 0.25, "act": 1.3}],
                        stop=0.75, timeH=2, size=50, maxOpen=5, dayLoss=150, v2=True,
                        desc="The coin with the most buyers in a name burst (often, but not always, the first one). Same exits: stop 25%, 25% trail once up 30%, out after 2 hours."),
    # ---- "Let it run" twins (Rainer, Oct 17 2026): the same buys as a winning book, but half the position has no 1-hour time stop.
    # It stays in until its own trailing stop hits (30% off the peak), up to 3 days. Forward test only: no history is re-priced,
    # because a different exit would need every old trade re-simulated on 1-minute candles that GeckoTerminal no longer has.
    "trail_tight_run": dict(label="v2 Tight trail, half runs", mirror="trail_tight", take="mirror", entry="market",
                            legs=[{"part": 0.5, "trail": 0.15, "act": 1.2}, {"part": 0.5, "trail": 0.30, "act": 1.2}],
                            stop=0.95, timeH=72, size=50, maxOpen=10, dayLoss=150, v2=True,
                            desc="The same buys as v2 Tight trail. Stop 5%. Once up 20%: half sells on a 15% trailing stop like Tight trail, the other half keeps running on a 30% trailing stop with no 1-hour time stop (3 days at most)."),
    "famous_exact_run": dict(label="v2 Famous name (exact), half runs", mirror="famous_exact", take="mirror", entry="market",
                             legs=[{"part": 0.5, "trail": 0.15, "act": 1.2}, {"part": 0.5, "trail": 0.30, "act": 1.2}],
                             stop=0.95, timeH=72, size=50, maxOpen=10, dayLoss=150, v2=True,
                             desc="The same buys as v2 Famous name (exact). Stop 5%. Once up 20%: half sells on a 15% trailing stop, the other half keeps running on a 30% trailing stop with no 1-hour time stop (3 days at most)."),
    "be_2x": dict(label="v2 2x with break-even", take="pool20nf", entry="market", legs=[{"part": 1.0, "tp": 2.0}], be=1.3,
                  stop=0.85, timeH=4, size=50, maxOpen=10, dayLoss=150, v2=True,
                  desc="Pool $20K+ and not falling in the last hour. Market buy. Stop 15%, moved up to the buy price once up 30%. Sell all at 2x. Out after 4 hours."),
    "sell30": dict(label="v2 Sell all at +30%", take="pool20nf", entry="market", legs=[{"part": 1.0, "tp": 1.3}],
                   stop=0.90, timeH=4, size=50, maxOpen=10, dayLoss=150, v2=True,
                   desc="Rainer's idea. Pool $20K+ and not falling in the last hour. Market buy. Sell everything at +30%. Stop 10%. Out after 4 hours."),
    "surv_2x": dict(label="v2 Survivor 2x", take="surv", entry="market", legs=[{"part": 1.0, "tp": 2.0}], be=1.3,
                    stop=0.75, timeH=4, size=50, maxOpen=10, dayLoss=100, v2=True,
                    desc="Survivor coins. Market buy. Stop 25%, moved up to the buy price once up 30%. Sell all at 2x. Out after 4 hours. Based on only 11 trades."),
    # ---- v3 calm coins (Rainer, Oct 27 2026). Picked by replaying 242 Season 2 coins on the live feed's real pool prices (800 exit
    # rules x buy filters, 2 s buy delay, stops sold 2 s late with price impact and fees). No rule was green on all coins (best -4% a
    # trade). Calm coins (not famous, at most 2,000 buyers in 24h, not falling) with this exit made +9% a trade on 79 coins, $50 bets;
    # buying 10 s late or $200 bets nearly erased it. Picked on the same data it was tested on, so this is a forward test, not a winner.
    "calm10": dict(label="v3 Calm coins, 10 minutes", take="calm", entry="market", legs=[{"part": 1.0, "tp": 2.0}],
                   stop=0.80, timeH=10 / 60, size=50, maxOpen=10, dayLoss=150, v2=True,
                   desc="Not a famous name, at most 2,000 buyers in 24h, not falling in the last hour. Market buy. Stop 20%. Sell all at 2x. Out after 10 minutes."),
    "calm10_safe": dict(label="v3 Calm coins + holder screen", take="calm_safe", entry="market", legs=[{"part": 1.0, "tp": 2.0}],
                        stop=0.80, timeH=10 / 60, size=50, maxOpen=10, dayLoss=150, v2=True,
                        desc="Same as Calm coins, 10 minutes, but skips the coin when one wallet holds enough to take half the pool's SOL in one sell (checked on chain at the buy)."),
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
    if t == "meta_first":
        return src_key == "meta" and bool((c.get("meta") or {}).get("isFirst"))
    if t == "meta_leader":
        return src_key == "meta" and bool((c.get("meta") or {}).get("isLeader"))
    if src_key in ("survivors", "curve", "meta"):
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
    if t == "famous_exact":  # famous name by itself, and not falling in the last hour
        return famous_kind(c) == "exact" and (c.get("chg1") or 0) >= 0
    if t == "famous_any":    # famous term inside the name (not exact), and not falling in the last hour
        return famous_kind(c) == "any" and (c.get("chg1") or 0) >= 0
    if t == "pool20nf":    # both
        return (c.get("liq") or 0) >= 20000 and (c.get("chg1") or 0) >= 0
    if t == "calm":
        return calm(c)
    if t == "calm_safe":   # calm, and no wallet can take half the pool in one sell
        if not calm(c):
            return False
        r = drain_risk(c)
        return r is not None and r["d1"] < 0.5
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
                         skipped=cfg.get(name, {}).get("skipped", {}), mirror=b.get("mirror"), slip=b.get("slip"))
        for c, src in cards:
            key = f"{name}:{c['token']}"
            mirror = trades.get(f"{b['mirror']}:{c['token']}") if b.get("mirror") else None
            if key in trades or not c.get("price"):
                continue
            if b.get("mirror"):
                if not mirror:
                    continue  # a twin buys exactly what its source playbook bought, nothing else
            elif not takes(b, c, src):
                continue
            if not b.get("mirror"):
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
                     slip=b.get("slip"), mirror=b.get("mirror"), onCurve=bool(c.get("curveProgress")),
                     entry=None, entryT=None, limit=None, stop0=None, now=None, liq=None, cash=0.0, pos=1.0, best=None, exit=None,
                     final=False, checked=None, outcome="Open", why="",
                     features=dict(firstSeenAgeH=c.get("firstSeenAgeH"), planOk=o.get("ok"), warns=len(c.get("warns") or []),
                                   chg1=c.get("chg1"), runup2h=(c.get("chartF") or {}).get("runup2h"), curveProgress=c.get("curveProgress"),
                                   meta=c.get("meta"), buyers24=c.get("buyers24"),
                                   drain=None if b.get("mirror") or src in ("curve", "meta") else drain_risk(c)))
            if b["entry"] == "limit":
                e.update(limit=o["entry"], outcome="Waiting for fill", why=f"limit buy at {S.money(o['entry'])}")
            elif b["entry"] == "chain":
                e.update(outcome="Waiting for fill", why="buys at the live feed's first on-chain price",
                         paperEntry=mirror.get("entry") if mirror else None, limit=mirror.get("limit") if mirror else None)
                if mirror and mirror.get("entryT"):
                    watch_update(key, dict(book=name, token=e["token"], pair=e["pair"], chain=e["chain"], symbol=e["symbol"],
                                           entry=mirror["entry"], entryT=mirror["entryT"], timeH=e["timeH"]))
            elif mirror and mirror.get("entry"):
                fill(e, mirror["entry"], mirror["entryT"])  # the same buy, to the cent
            else:
                fill(e, c["price"], time.time())
            trades[key] = e
            opened += 1
            if name in RECORD_BOOKS and e.get("entry"):
                watch_update(key, dict(book=name, token=e["token"], pair=e["pair"], chain=e["chain"], symbol=e["symbol"],
                                       entry=e["entry"], entryT=e["entryT"], stop0=e["stop0"], legs=e["legs"], timeH=e["timeH"]))
    return opened


def backfill_mirrors(books):
    """Create the twin of every source trade that has none yet, so a new twin book starts with the whole history.
    Exact for single-leg trail books: only a stop or trailing-stop sale (outcome "Stop hit" or "All targets hit") has slippage in
    its cash; every other exit (time stop, dead, bad data) has none. So re-pricing = swap the 10% for the twin's slippage.
    Open source trades are copied as open and get simulated going forward with the twin's slippage."""
    trades = books.setdefault("trades", {})
    added = 0
    for name, b in BOOKS.items():
        src = b.get("mirror")
        if not src or b.get("slip") is None:
            continue  # exit-twins (no slip) run forward only; only stop-fill twins can re-price history exactly
        for key, e in list(trades.items()):
            if e.get("book") != src:
                continue
            twin_key = f"{name}:{e['token']}"
            if twin_key in trades:
                continue
            t = dict(e, book=name, slip=b["slip"], mirror=src, backfilled=True)
            if e.get("final") and e.get("entry") and e.get("outcome") in ("Stop hit", "All targets hit"):
                t["cash"] = e["cash"] * (1 - b["slip"]) / (1 - S.SLIP)
            trades[twin_key] = t
            added += 1
    return added


def fill(e, price, t):
    stop = e["orderStop"] if e["stopRule"] == "card" else price * e["stopRule"]
    if not stop or stop >= price:
        stop = price * (S.NOW_STOP if e["stopRule"] == "card" else e["stopRule"])
    e.update(entry=price, entryT=t, stop0=stop, outcome="Open")


def simulate(e, candles):
    r = S.run_legs(candles, e["entry"], e["entryT"], e["stop0"], e["legs"], e["timeH"] * 3600, size=e.get("candle", 900), be=e.get("be"), slip=e.get("slip"))
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


# Real trades around each paper stop (added Oct 18 2026): the paper book fills a stop at the candle low minus 10%.
# To learn what a real sell would have fetched, the real swaps of the stop minute are saved from GeckoTerminal the
# moment the paper trade closes (the trades endpoint only keeps the last 300 trades, so it must happen right away).
# Real-money twins (Rainer asked Oct 23 2026, "all playbooks set up as if live"): every source book gets a "<key>_chain"
# twin that buys the same coins at the on-chain price the live feed sees 1 s after the paper buy (limit books: when the
# chain price reaches the limit), and sells from the live tick path: targets at their price, stops and trailing stops
# EXIT_DELAY_S after the price crosses them, minus the price impact of the whole position and the 0.3% pool fee.
# Curve and meta books trade bonding curves, which the feed cannot watch, so they get no twin.
LIVE_SKIP = {"curve_run", "curve_quick", "meta_first", "meta_leader"}
for _k, _b in list(BOOKS.items()):
    if _b.get("mirror") or _k in LIVE_SKIP or _k.endswith("_chain"):
        continue
    BOOKS[_k + "_chain"] = dict(_b, label=_b["label"] + ", real chain price", mirror=_k, take="mirror", entry="chain", paperEntry=_b["entry"],
                                desc="Real-money version: the same buys as \"" + _b["label"] + "\", but at the on-chain price the live feed saw 1 second after the paper buy"
                                     + (" (limit buys fill when the chain price reaches the limit)" if _b["entry"] == "limit" else "")
                                     + ". Every sell is priced from the live pool: targets at their price, stops and trailing stops 2 seconds after the price crosses them, minus the price impact of the whole position and the pool fee. Original rules: " + _b["desc"])
RECORD_BOOKS = {k for k in BOOKS if k + "_chain" in BOOKS}  # the live feed watches every source book with a twin
SEASON2 = "2026-10-22T18:30:00+00:00"  # season 2 (real chain price twins live): the page can show every book from this moment only
DATA_DIR = None  # set by fast.py; the live feed (scanner/feed.py) reads data/feed/watch.json and writes data/feed/<key>.json


def feed_dir():
    return os.path.join(DATA_DIR, "feed") if DATA_DIR else None


def watch_update(key, fields):
    """Tell the live feed about a paper trade (opened or closed). Small JSON file, replaced atomically."""
    try:
        fd = feed_dir()
        if not fd:
            return
        os.makedirs(fd, exist_ok=True)
        path = os.path.join(fd, "watch.json")
        try:
            items = json.load(open(path))
        except Exception:
            items = {}
        cut = time.time() - 6 * 3600
        items = {k: v for k, v in items.items() if (v.get("entryT") or 0) > cut}
        items[key] = {**items.get(key, {}), **fields}
        tmp = path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(items, fh, separators=(",", ":"))
        os.replace(tmp, path)
    except Exception as ex:
        S.say(f"watch file failed: {ex}")


def attach_feed(e):
    """Copy the live feed's summary (without the price path) into the trade record. Returns True when final."""
    fd = feed_dir()
    if not fd:
        return False
    path = os.path.join(fd, e["book"] + "_" + e["token"] + ".json")
    if not os.path.exists(path):
        return False
    try:
        f = json.load(open(path))
    except Exception:
        return False
    f.pop("path", None)
    e["feed"] = f
    return bool(f.get("final"))


def record_chain_trades(e):
    try:
        d = S.get(f"{S.GT}/{e['chain']}/pools/{e['pair']}/trades?trade_volume_in_usd_greater_than=0")
        rows = []
        for t in (d.get("data") or []):
            a = t.get("attributes") or {}
            ts = S.ts_of(a.get("block_timestamp"))
            if not ts or ts < e["exit"] - 180 or ts > e["exit"] + 900:
                continue
            kind = a.get("kind")
            price = S.num(a.get("price_from_in_usd") if kind == "sell" else a.get("price_to_in_usd"))
            rows.append([int(ts), kind[0] if kind else "?", price, round(S.num(a.get("volume_in_usd")), 2)])
        rows.sort()
        best = e.get("best") or 1.0
        e["stopLevel"] = e["entry"] * max(0.95, 0.85 * best) if best >= 1.2 else e["stop0"]
        e["chainTrades"] = rows[:120]
        e["chainTradesN"] = len(rows)
    except Exception as ex:
        e["chainTrades"] = None
        e["chainTradesErr"] = str(ex)[:80]


EXIT_DELAY_S = 2  # a real bot sells about 2 s after the price crosses the stop (see Oct 23 2026 review)


def feed_file(e):
    """The live feed's summary for a twin: its own file if the feed watched it, else its source's, else any book's
    watch of the same pool (all books on a coin share the pool). Prefers the file with the most ticks."""
    fd = feed_dir()
    if not fd:
        return None
    best = None
    for path in sorted(glob.glob(os.path.join(fd, f"*_{e['token']}.json"))):
        try:
            f = json.load(open(path))
        except Exception:
            continue
        if f.get("solUsd") and (best is None or (f.get("ticksN") or 0) > (best.get("ticksN") or 0)):
            best = f
    return best


def feed_path(e):
    """The tick path for a twin. Returns (path, solUsd)."""
    f = feed_file(e)
    if not f:
        return None, None
    pts = [x for x in (f.get("path") or []) if x[1]]
    return (pts, f["solUsd"]) if pts else (None, None)


def real_exit(e):
    """Walk the on-chain tick path from the twin's buy with the book's own legs: a target leg sells at its price the
    moment the chain price reaches it; a trailing leg (once armed at "act" x the buy) and the shared stop (moved to the
    buy price once "be" x the buy is seen) sell EXIT_DELAY_S after the price crosses them, at the pool's price then,
    minus the price impact of that part of the position (constant product, 0.3% fee). The time stop sells the rest.
    Returns dict(cash, pos, best, legs, done, exit, kind, ...) or None when no path is available yet."""
    pts, sol = feed_path(e)
    if not pts:
        return None
    entry, t0 = e["entry"], e["entryT"]
    after = [x for x in pts if x[0] >= t0 and x[1]]
    if not after:
        return None
    legs = [dict(l) for l in (e.get("legs") or [{"part": 1.0}])]
    stop = e.get("stop0") or entry * 0.95
    be = e.get("be")
    t_end = t0 + e["timeH"] * 3600
    tokens_all = e["size"] / entry
    best, cash, closed, exit_t, kind = entry, 0.0, 0, None, None

    def sell(part, at):
        state = [x for x in pts if x[0] <= at][-1]
        price, quote = state[1], state[2]
        base = quote / (price / sol) if (price and quote and sol) else 0
        tok = tokens_all * part
        if base <= 0:
            return price * tok, state[0], price
        got = quote - (base * quote) / (base + tok * 0.997)
        return got * sol, state[0], price

    for x in after:
        t, px = x[0], x[1]
        if t >= t_end:
            for l in legs:
                if not l.get("done"):
                    p, ft, fp = sell(l["part"], t)
                    cash += p; l.update(done=True, kind="time", t=ft, price=fp)
            exit_t, kind = t, "time"
            break
        best = max(best, px)
        if be and best >= entry * be:
            stop = max(stop, entry)
        for l in legs:
            if l.get("done"):
                continue
            armed = l.get("trail") and l.get("act") and best >= entry * l["act"]
            if l.get("tp") and px >= entry * l["tp"]:
                tok = tokens_all * l["part"]
                cash += entry * l["tp"] * tok * 0.997   # resting limit sell fills at its price, minus the pool fee
                l.update(done=True, kind="tp", t=t, price=entry * l["tp"])
            elif armed and px <= best * (1 - l["trail"]):
                p, ft, fp = sell(l["part"], t + EXIT_DELAY_S)
                cash += p; l.update(done=True, kind="trail", t=ft, price=fp)
            elif not armed and px <= stop:
                p, ft, fp = sell(l["part"], t + EXIT_DELAY_S)
                cash += p; l.update(done=True, kind="stop", t=ft, price=fp)
        if all(l.get("done") for l in legs):
            exit_t = max(l["t"] for l in legs)
            kinds = {l["kind"] for l in legs}
            kind = "tp" if kinds == {"tp"} else "stop" if kinds == {"stop"} else "trail" if kinds == {"trail"} else "mixed"
            break
    pos = sum(l["part"] for l in legs if not l.get("done"))
    return dict(cash=cash / e["size"], pos=round(pos, 6), best=best / entry, legs=legs, done=pos == 0, exit=exit_t, kind=kind,
                pathEnd=pts[-1][0], last=pts[-1][1])


def chain_fill(e):
    """Fill a real-chain-price twin from the live feed's summary of its source trade. Returns True when filled."""
    f = feed_file(e)
    if e.get("limit") and BOOKS.get(e["book"], {}).get("paperEntry") == "limit":
        pts = [x for x in ((f or {}).get("path") or []) if x[1]]
        hit = next((x for x in pts if x[1] <= e["limit"]), None)
        if hit:
            fill(e, e["limit"], hit[0])
            e.update(why="limit buy filled at the on-chain price", feedDelayS=(f or {}).get("feedDelayS"))
            watch_update(f"{e['book']}:{e['token']}", dict(book=e["book"], token=e["token"], pair=e["pair"], chain=e["chain"], symbol=e["symbol"],
                                                         entry=e["entry"], entryT=e["entryT"], timeH=e["timeH"]))
            return True
        if time.time() - S.ts_of(e["logged"]) > 12 * 3600 or (f and f.get("final")):
            e.update(outcome="Missed", why="the on-chain price never came down to the limit", final=True, exit=int(time.time()), cash=1.0, pos=0.0)
        return False
    price = (f or {}).get("chainEntryUsd")
    stale = (f or {}).get("entryStale")
    if price and stale and not (0.5 <= stale <= 2.0):
        # the feed's price is more than 2x off the paper price: almost always a wrong account or a broken pool read
        e.update(outcome="Missed", why=f"the live feed's price was {stale:.3g}x the paper price (feed read looks wrong)",
                 final=True, exit=int(time.time()), cash=1.0, pos=0.0, entryStale=stale)
        return False
    if price and (f.get("feedDelayS") or 99) <= 30:
        fill(e, price, f.get("startedAt") or time.time())
        e.update(entryStale=f.get("entryStale"), feedDelayS=f.get("feedDelayS"), why="bought at the live feed's first on-chain price")
        return True
    if time.time() - S.ts_of(e["logged"]) > 1800:
        why = "the live feed had no price for this pool" if not f else f"the live feed started too late or saw no price ({(f or {}).get('status')})"
        e.update(outcome="Missed", why=why, final=True, exit=int(time.time()), cash=1.0, pos=0.0)
    return False


def repair_chain_twins(trades):
    """Twins filled before the 2x sanity check (Oct 23 2026): a feed price more than 2x off the paper price was a broken
    read, so the trade is marked Bad data (counted flat), like other broken price data."""
    n = 0
    for e in trades.values():
        if BOOKS.get(e["book"], {}).get("entry") == "chain" and e.get("entry") and e.get("entryStale") and not (0.5 <= e["entryStale"] <= 2.0) and e.get("outcome") != "Bad data":
            e.update(cash=1.0, pos=0.0, outcome="Bad data", why=f"feed price was {e['entryStale']:.3g}x the paper price (broken read)",
                     final=True, exit=e.get("exit") or int(time.time()))
            n += 1
    return n


def check_books(books, cache, say=S.say):
    """Re-check open playbook trades. cache: {(chain, token): ((price, liq), candles)}, shared with the main portfolio."""
    trades = books.get("trades", {})
    fixed = repair_chain_twins(trades)
    if fixed:
        say(f"{fixed} real-price twins had a broken feed price, marked Bad data")
    todo = [e for e in trades.values() if not e.get("final") and S.ts_of(e["logged"]) < time.time() - MIN_AGE_S]
    todo.sort(key=lambda e: (e.get("checked") or "", e["logged"]))
    started, n = time.time(), 0
    for e in todo:
        if time.time() - started > BUDGET_S:
            say(f"playbooks: time budget used, {len(todo) - n} trades wait")
            break
        key = (e["chain"], e["token"], e.get("candle", 900))
        if key not in cache and BOOKS.get(e["book"], {}).get("entry") == "chain" and feed_file(e):
            cache[key] = ((e.get("now"), e.get("liq")), None)  # real-money twins run on the live feed: no candle calls needed
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
                # DexPaprika backup: 1h candles keyless, 10-minute with a free key; 1-minute books get nothing.
                candles = S.dp_candles(e["chain"], e["pair"], e.get("candle", 900) if tf.startswith("minute") else 3600) or None
                if candles:
                    e["candleSrc"] = "dexpaprika"
            cache[key] = (price, candles)
            time.sleep(S.PAUSE)
        (now_p, liq), candles = cache[key]
        if now_p is not None:
            e["now"], e["liq"] = now_p, liq
        if BOOKS.get(e["book"], {}).get("entry") == "chain":
            if not e.get("entry"):
                chain_fill(e)
                if e.get("final"):
                    e["checked"] = now_iso()
                    n += 1
                    continue
            if e.get("entry"):
                r = real_exit(e)
                if r:
                    hits = sum(1 for l in r["legs"] if l.get("kind") == "tp")
                    e.update(cash=r["cash"], pos=r["pos"], best=r["best"], now=r["last"], realLegs=r["legs"], exitSrc="chain")
                    if r["done"]:
                        out = {"tp": "All targets hit", "stop": "Stop hit", "trail": "Trailing stop", "time": "Time stop" + (f" after {hits} target{'s' if hits != 1 else ''}" if hits else ""),
                               "mixed": f"{hits} target{'s' if hits != 1 else ''} hit, rest stopped"}[r["kind"]] + " (real chain price)"
                        e.update(exit=int(r["exit"]), outcome=out, final=True, why=f"sells priced from the live pool, {EXIT_DELAY_S} s after each stop")
                        watch_update(f"{e['book']}:{e['token']}", dict(closedAt=int(time.time()), exit=e["exit"], outcome=out))
                        e["checked"] = now_iso()
                        n += 1
                        continue
                    stale = r["pathEnd"] < time.time() - 900
                    if not stale or time.time() < e["entryT"] + e["timeH"] * 3600:
                        e["outcome"] = f"{hits} target{'s' if hits != 1 else ''} hit, rest running" if hits else "Open"
                        e["checked"] = now_iso()
                        n += 1
                        continue
                    # the feed stopped before the book's time stop: the rest sells at the last chain price seen
                    e.update(cash=e["cash"] + e["pos"] * r["last"] / e["entry"], pos=0.0, exit=int(r["pathEnd"]), final=True,
                             outcome="Feed ended, rest sold at the last chain price", why="the live feed stopped before this book's time stop")
                    e["checked"] = now_iso()
                    n += 1
                    continue
                e["exitSrc"] = "candles"  # no usable path: fall back to the 1-minute candles below
        if candles:
            if not e.get("entry") and e.get("limit"):
                S.watch_fill(e, candles)  # sets entry/entryT on a fill, or Missed after 12 hours
                if e.get("entry"):
                    fill(e, e["entry"], e["entryT"])
            if e.get("entry"):
                was_open = not e.get("final")
                simulate(e, candles)
                if was_open and e.get("final") and e["book"] in RECORD_BOOKS:
                    best = e.get("best") or 1.0
                    e["stopLevel"] = e["entry"] * max(0.95, 0.85 * best) if best >= 1.2 else e["stop0"]
                    watch_update(f"{e['book']}:{e['token']}", dict(closedAt=int(time.time()), exit=e.get("exit"), outcome=e.get("outcome"),
                                                                 stopLevel=e["stopLevel"], best=best))
                    if e.get("outcome") in ("Stop hit", "All targets hit"):
                        record_chain_trades(e)
                    attach_feed(e)
        on_curve = e.get("source") == "curve" or e.get("onCurve")
        if e.get("entry") and not e["final"] and on_curve and liq and liq >= 1000 and candles:
            # A curve coin with pool money has graduated: the curve stopped. The bot would sell at the last curve price.
            last = sorted(candles)[-1][4]
            e.update(cash=e["cash"] + e["pos"] * last / e["entry"], pos=0.0, outcome="Graduated, sold at the last curve price", exit=int(time.time()), final=True)
        if e.get("entry") and not e["final"]:
            if (e.get("best") or 0) > 100 or (now_p and now_p / e["entry"] > 100):
                e.update(cash=1.0, pos=0.0, outcome="Bad data", exit=int(time.time()), final=True)
            elif on_curve and now_p and now_p / e["entry"] < 0.1:
                e.update(cash=e["cash"] + e["pos"] * now_p / e["entry"], pos=0.0, outcome="Dead", exit=int(time.time()), final=True)
            elif not on_curve and ((liq is not None and liq < 1000) or (now_p and now_p / e["entry"] < 0.1)):
                e.update(cash=e["cash"] + e["pos"] * (now_p or 0) / e["entry"], pos=0.0, outcome="Dead", exit=int(time.time()), final=True)
            elif time.time() > e["entryT"] + e["timeH"] * 3600 + 7200:
                e.update(cash=e["cash"] + e["pos"] * (now_p or 0) / e["entry"], pos=0.0, outcome="Time stop", exit=int(time.time()), final=True)
        e["checked"] = now_iso()
        n += 1
    books["updated"] = now_iso()
    cut = time.time() - 900
    for e in trades.values():
        if e.get("final") and e["book"] in RECORD_BOOKS and (e.get("exit") or 0) > cut and not e.get("feedFinal"):
            if attach_feed(e):
                e["feedFinal"] = True
    return n
