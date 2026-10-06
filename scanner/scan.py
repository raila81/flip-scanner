#!/usr/bin/env python3
"""Flip Scanner, automatic run (GitHub Actions, every hour).

Same rules as index.html. Writes two files the page reads:
  data/latest.json  the last scan, same shape the page builds itself
  data/track.json   the paper portfolio: every passed coin, plus what happened since

Free public data only: GeckoTerminal, DexScreener, RugCheck, GoPlus. No keys.
Usage: python3 scanner/scan.py [--hours 6] [--chains pumpfun,robinhood,movers] [--out data]
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html import unescape

GT = "https://api.geckoterminal.com/api/v2/networks"
UA = {"User-Agent": "Mozilla/5.0 flip-scanner (github.com/raila81/flip-scanner)"}
PAUSE = 7
WHALE = 5000
STOP, COST = 0.67, 0.03
PAPER = {"pumpfun": 250, "robinhood": 250, "movers": 100}

PONS_DEPLOYER = "0x3711cea4feade896c913c68f01eda97cb06d1a42"
RH_CHAIN_ID = "4663"
RH_POOL_MANAGER = "0x8366a39cc670b4001a1121b8f6a443a643e40951"
RH_LOCKERS = {"0x267444d099b10fb5ed7c3cc7b7c767adca574952": "Pons launch locker"}
BURN = {"0x0000000000000000000000000000000000000000", "0x000000000000000000000000000000000000dead"}
POOL_WORDS = re.compile(r"pool|amm|vault|lock|escrow|streamflow|meteora|raydium|pump fun amm|pumpswap", re.I)
NOT_NEW = {"weth", "eth", "usdg", "usdc", "usdt", "sol", "wsol", "wbtc", "btc", "spy", "qqq", "nvda", "tsla",
           "aapl", "msft", "amzn", "goog", "googl", "meta", "hood", "coin", "gme", "amc", "pltr", "mstr"}
FAME = re.compile(
    r"\b(elon|musk|trump|melania|barron|cz|binance|saylor|vitalik|kanye|ye|drake|taylor|swift|ibm|google|gemini|grok|"
    r"openai|chatgpt|gpt|claude|anthropic|apple|tesla|nvidia|microsoft|amazon|meta|facebook|robinhood|mercedes|bmw|"
    r"ferrari|nike|disney|pepsi|coca|starbucks|spacex|x|twitter|united states|usa|official|government|federal|fed|dividend|etf)\b", re.I)
UTIL_WORDS = re.compile(
    r"\b(app|platform|protocol|sdk|api|agent|agents|ai|infra|infrastructure|launchpad|dex|swap|wallet|bot|tool|tools|network|"
    r"compute|gpu|defi|lending|staking|revenue|buy-?back|burn|fees?|dashboard|browser|game|marketplace|payments?|data|trading|terminal|server)\b", re.I)
MEME_WORDS = re.compile(
    r"\b(meme|memecoin|dog|doge|cat|kitten|pepe|frog|inu|shib|moon|wif|hat|vibes?|community|lol|cult|based|degen|pump it|"
    r"to the moon|just a|no utility|for fun|chad|wojak|ape|monkey|bonk|fart|squirrel|hamster|penguin|duck|goat|mascot|ticker is)\b", re.I)

STD_LIMITS = dict(minLiq=20000, maxFdv=5e6, minTx24=100, minSells24=300, minSells1=10, maxChg24=2000, maxBuyRatio=3, maxVolToMc=10, maxAge=None)
SOURCES = {
    "pumpfun": {
        "label": "pump.fun (Solana)", "network": "solana", "dexChain": "solana",
        "feeds": lambda h: [{"name": "busiest", "pages": 10, "url": lambda p: f"{GT}/solana/dexes/pumpswap/pools?sort=h24_tx_count_desc&page={p}"}]
        + ([{"name": "volume", "pages": 5, "url": lambda p: f"{GT}/solana/dexes/pumpswap/pools?sort=h24_volume_usd_desc&page={p}"},
            {"name": "trending", "pages": 1, "url": lambda p: f"{GT}/solana/trending_pools?duration=1h&page=1", "onlyDex": "pumpswap"}] if h <= 12 else []),
        "limits": STD_LIMITS,
    },
    "robinhood": {
        "label": "Robinhood Chain", "network": "robinhood", "dexChain": "robinhood",
        "feeds": lambda h: [{"name": "busiest", "pages": 5, "url": lambda p: f"{GT}/robinhood/pools?sort=h24_tx_count_desc&page={p}"}]
        + ([{"name": "volume", "pages": 3, "url": lambda p: f"{GT}/robinhood/pools?sort=h24_volume_usd_desc&page={p}"}] if h <= 12 else []),
        "limits": dict(STD_LIMITS, minLiq=10000, minTx24=50, minSells24=30, minSells1=1),
    },
    # Movers: small pools on any Solana exchange that just started moving. Catches sleepers once they wake.
    "movers": {
        "label": "Movers (small pools, Solana)", "network": "solana", "dexChain": "solana",
        "feeds": lambda h: [{"name": "trending 5m", "pages": 1, "url": lambda p: f"{GT}/solana/trending_pools?duration=5m&page=1"},
                            {"name": "trending 1h", "pages": 1, "url": lambda p: f"{GT}/solana/trending_pools?duration=1h&page=1"},
                            {"name": "trending 6h", "pages": 1, "url": lambda p: f"{GT}/solana/trending_pools?duration=6h&page=1"}],
        "limits": dict(STD_LIMITS, minLiq=3000, minTx24=50, minSells24=50, minSells1=5, maxAge=168),
    },
}


# ---------- helpers ----------
def say(msg):
    print(datetime.now().strftime("%H:%M:%S"), msg, file=sys.stderr, flush=True)


def get(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
    return json.loads(body) if body.strip() else {}


def get_slow(url):
    try:
        return get(url)
    except Exception:
        say("Data site asked us to slow down, waiting 30 seconds")
        time.sleep(30)
        return get(url)


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def money(x):
    x = num(x)
    neg = x < 0
    x = abs(x)
    if x >= 1e6:
        s = f"${x / 1e6:.2f}M"
    elif x >= 1e3:
        s = f"${x / 1e3:.1f}K"
    elif x >= 1:
        s = f"${x:.2f}"
    elif x == 0:
        s = "$0"
    else:
        d = 2
        while x < 10 ** -(d - 2) and d < 14:
            d += 1
        s = f"${x:.{d}f}"
    return "-" + s if neg else s


def same_size_group(pcts):
    s = sorted(pcts, reverse=True)
    best = []
    for top in s:
        grp = [x for x in s if 0 <= top - x <= 0.1]
        if len(grp) >= 3 and sum(grp) > sum(best):
            best = grp
    return best


def safe_url(u):
    return u if isinstance(u, str) and re.match(r"^https?://", u, re.I) else None


# ---------- step 1: pool lists ----------
def fetch_pools(src, hours):
    seen, planned, read = {}, 0, 0
    for feed in src["feeds"](hours):
        planned += feed["pages"]
        for page in range(1, feed["pages"] + 1):
            say(f"{src['label']}: reading {feed['name']} list, page {page} of {feed['pages']}")
            try:
                d = get_slow(feed["url"](page))
            except Exception:
                break
            read += 1
            data = d.get("data") or []
            for p in data:
                if feed.get("onlyDex") and p["relationships"]["dex"]["data"]["id"] != feed["onlyDex"]:
                    continue
                seen.setdefault(p["id"], p)
            if len(data) < 20:
                break
            time.sleep(PAUSE)
    return list(seen.values()), read, planned


# ---------- step 2: red-flag filters ----------
def prefilter(pools, hours, L):
    now = datetime.now(timezone.utc)
    window = L.get("maxAge") or hours
    recent = []
    for p in pools:
        created = datetime.fromisoformat(p["attributes"]["pool_created_at"].replace("Z", "+00:00"))
        age_h = (now - created).total_seconds() / 3600
        if age_h <= max(48, window):
            recent.append((p, age_h))
    sym_count = {}
    for p, _ in recent:
        s = p["attributes"]["name"].split(" / ")[0].strip().lower()
        sym_count[s] = sym_count.get(s, 0) + 1
    keep, dropped, seen = {}, {}, set()
    for p, age_h in recent:
        a = p["attributes"]
        sym = a["name"].split(" / ")[0].strip()
        token = p["relationships"]["base_token"]["data"]["id"].split("_", 1)[1]
        tx = a.get("transactions") or {}
        t24, t1 = tx.get("h24") or {}, tx.get("h1") or {}
        buys24, sells24 = t24.get("buys") or 0, t24.get("sells") or 0
        buys1, sells1 = t1.get("buys") or 0, t1.get("sells") or 0
        liq = num(a.get("reserve_in_usd"))
        fdv = num(a.get("market_cap_usd")) or num(a.get("fdv_usd"))
        vol24 = num((a.get("volume_usd") or {}).get("h24"))
        chg24 = num((a.get("price_change_percentage") or {}).get("h24"))
        reason = None
        if sym.lower() in NOT_NEW:
            reason = "money or stock token, not a new coin"
        elif age_h < 1 or age_h > window:
            reason = "outside time window"
        elif liq < L["minLiq"]:
            reason = f"pool under ${L['minLiq'] // 1000}K"
        elif fdv > L["maxFdv"]:
            reason = "market cap over $5M"
        elif buys24 + sells24 < L["minTx24"] or sells24 < L["minSells24"] or sells1 < L["minSells1"]:
            reason = "too few sells (maybe can't sell)"
        elif chg24 > L["maxChg24"]:
            reason = "already up over 2,000%"
        elif (sells24 and buys24 / sells24 > L["maxBuyRatio"]) or (sells1 and buys1 / sells1 > L["maxBuyRatio"]):
            reason = "one-sided buying (over 3 buys per sell)"
        elif fdv and vol24 / fdv > L["maxVolToMc"]:
            reason = "fake volume (volume over 10x market cap)"
        elif sym_count[sym.lower()] > 1 and token not in seen:
            reason = "copy name (same name launched twice)"
        elif FAME.search(sym) or FAME.search(a["name"]):
            reason = "celebrity or company name"
        if reason:
            dropped[reason] = dropped.get(reason, 0) + 1
            continue
        seen.add(token)
        tpb = buys24 / t24["buyers"] if t24.get("buyers") else None
        if token not in keep or keep[token]["liq"] < liq:
            keep[token] = dict(token=token, symbol=sym, liq=liq, vol24=vol24, ageH=age_h, tpb=tpb, buyers24=t24.get("buyers") or 0)
    return list(keep.values()), sorted(dropped.items(), key=lambda x: -x[1])


# ---------- step 3: flip check ----------
def find_pair(token, chain):
    pairs = get(f"https://api.dexscreener.com/token-pairs/v1/{chain}/{token}")
    if not isinstance(pairs, list) or not pairs:
        return None
    return max(pairs, key=lambda p: (p.get("liquidity") or {}).get("usd") or 0)


def solana_safety(token, pair_addr, F, W, N):
    try:
        r = get(f"https://api.rugcheck.xyz/v1/tokens/{token}/report")
    except Exception:
        r = None
    if not r:
        N["unchecked"] = "RugCheck gave no data"
        return
    if r.get("rugged"):
        F.append("RugCheck marks it as rugged")
    if r.get("mintAuthority"):
        F.append("Mint is ON (team can print more coins)")
    if r.get("freezeAuthority"):
        F.append("Freeze is ON (team can freeze your coins)")
    fee = (r.get("transferFee") or {}).get("pct") or 0
    if fee > 5:
        F.append(f"Transfer fee {fee}%")
    markets = r.get("markets") or []
    usd = lambda m: (m.get("lp") or {}).get("quoteUSD") or 0
    mk = (next((m for m in markets if m.get("pubkey") == pair_addr), None)
          or next((m for m in markets if m.get("marketType") == "pump_fun_amm"), None)
          or (markets[0] if markets else None))
    if mk:
        lp = (mk.get("lp") or {}).get("lpLockedPct") or 0
        if lp < 90:
            F.append(f"Only {lp:.0f}% of pool money locked")
        elif mk.get("marketType") != "pump_fun_amm":
            N["notes"].append(f"Pool money {lp:.0f}% locked")
        for m in markets:
            if m is mk or usd(m) < 20000 or usd(m) < 0.5 * usd(mk):
                continue
            if ((m.get("lp") or {}).get("lpLockedPct") or 0) < 90:
                W.append(f"Big second pool with no lock: {money(usd(m))} on {m.get('marketType') or 'another exchange'}")
    else:
        W.append("No graduated pool found: may still be on the pump.fun curve")
    known = r.get("knownAccounts") or {}
    supply = (r.get("token") or {}).get("supply") or 0
    holders = r.get("topHolders") or []
    top = []
    for h in holders[:10]:
        k = known.get(h.get("owner")) or known.get(h.get("address")) or {}
        if k.get("type") in ("AMM", "LOCKER") or POOL_WORDS.search(k.get("name", "")):
            continue
        top.append(h["pct"])
    t10 = sum(top)
    (F if t10 > 30 else N["notes"]).append(f"Top 10 wallets (not pools) hold {t10:.1f}%")
    grp = same_size_group([h["pct"] for h in holders[:20]])
    if len(grp) >= 10:
        F.append(f"{len(grp)} same-size wallets hold {sum(grp):.1f}%: one buyer split into many wallets")
    elif grp and sum(grp) >= 5:
        W.append(f"{len(grp)} same-size wallets hold {sum(grp):.1f}% (maybe one buyer)")
    biggest, big_net = 0, 0
    for n in r.get("insiderNetworks") or []:
        held = n.get("currentHolding") if n.get("currentHolding") is not None else n.get("tokenAmount")
        if supply and held:
            biggest = max(biggest, held / supply * 100)
        big_net = max(big_net, n.get("activeAccounts") or n.get("size") or 0)
    # HNUT (Oct 6 2026): 148 linked wallets ran the whole coin. A network this big is a bundled launch, whatever the % says.
    if big_net >= 100:
        F.append(f"Linked wallet network of {big_net} wallets: a bundled launch")
    elif biggest > 100:
        W.append(f"Linked wallet network of {big_net} wallets, RugCheck numbers unclear: check the bubble map")
    elif biggest > 20:
        F.append(f"Linked wallet group holds {biggest:.1f}% (RugCheck estimate)")
    elif biggest > 10:
        W.append(f"Linked wallet group may hold {biggest:.1f}% (RugCheck estimate, check the bubble map)")
    elif big_net >= 50:
        W.append(f"Linked wallet network of {big_net} wallets (often a bundled launch)")
    elif biggest >= 5:
        W.append(f"Linked wallet group holds {biggest:.1f}%")
    cb = r.get("creatorBalance") or 0
    if supply and cb / supply * 100 > 5:
        F.append(f"Creator still holds {cb / supply * 100:.1f}%")
    N["holders"] = r.get("totalHolders")
    N["creator"] = r.get("creator")


def robinhood_safety(token, pair_addr, F, W, N):
    try:
        d = get(f"https://api.gopluslabs.io/api/v1/token_security/{RH_CHAIN_ID}?contract_addresses={token}")
    except Exception:
        d = {}
    r = next(iter((d.get("result") or {}).values()), None)
    if not r:
        N["unchecked"] = "GoPlus gave no data"
        return
    for key, msg in [("is_mintable", "Mintable (team can print more coins)"), ("owner_change_balance", "Owner can change wallet balances"),
                     ("hidden_owner", "Hidden owner"), ("transfer_pausable", "Transfers can be paused"),
                     ("is_honeypot", "Honeypot (you cannot sell)"), ("cannot_sell_all", "Cannot sell all coins"),
                     ("is_blacklisted", "Team can block wallets"), ("can_take_back_ownership", "Owner can take control back")]:
        if r.get(key) == "1":
            F.append(msg)
    if r.get("slippage_modifiable") == "1":
        W.append("Team can change the tax")
    if r.get("is_open_source") != "1":
        W.append("Code not public")
    for side in ("buy_tax", "sell_tax"):
        if num(r.get(side)) * 100 > 5:
            F.append(f"{side.replace('_', ' ')} over 5%")
    tok, pair = token.lower(), (pair_addr or "").lower()
    top, contracts = [], []
    for h in (r.get("holders") or [])[:10]:
        a = h["address"].lower()
        p = num(h.get("percent")) * 100
        if a in BURN or a in (RH_POOL_MANAGER, tok, pair) or a in RH_LOCKERS or h.get("is_locked") == 1:
            continue
        top.append(p)
        if h.get("is_contract") == 1:
            contracts.append(f"{a[:8]}.. {p:.1f}%")
    t10 = sum(top)
    (F if t10 > 30 else N["notes"]).append(f"Top 10 wallets (not pools) hold {t10:.1f}%")
    if contracts:
        W.append("Unlabeled contracts in top 10 (could be staking or a lock, or a whale): " + ", ".join(contracts))
    grp = same_size_group([num(h.get("percent")) * 100 for h in (r.get("holders") or [])[:20]])
    if len(grp) >= 10:
        F.append(f"{len(grp)} same-size wallets hold {sum(grp):.1f}%: one buyer split into many wallets")
    elif grp and sum(grp) >= 5:
        W.append(f"{len(grp)} same-size wallets hold {sum(grp):.1f}% (maybe one buyer)")
    cp = num(r.get("creator_percent")) * 100
    if cp > 5:
        F.append(f"Creator still holds {cp:.1f}%")
    lps = r.get("lp_holders") or []
    locked = sum(num(x.get("percent")) for x in lps if x.get("is_locked") == 1 or x["address"].lower() in RH_LOCKERS) * 100
    if (r.get("creator_address") or "").lower() == PONS_DEPLOYER:
        N["notes"].append("Launched with Pons: pool money held by the Pons launch locker (Pons code is unaudited)")
    elif locked >= 90:
        N["notes"].append(f"Pool money in a known lock: {locked:.0f}%")
    else:
        W.append("Pool lock unknown: not a Pons launch, and GoPlus cannot see Uniswap V4 pools")
    N["holders"] = r.get("holder_count")
    N["creator"] = r.get("creator_address")


def check(p):
    chain, b = p["chainId"], p["baseToken"]
    liq = (p.get("liquidity") or {}).get("usd") or 0
    mc = p.get("marketCap") or p.get("fdv") or 0
    price = num(p.get("priceUsd"))
    age_min = (time.time() * 1000 - (p.get("pairCreatedAt") or time.time() * 1000)) / 60000
    tx1 = (p.get("txns") or {}).get("h1") or {}
    tx24 = (p.get("txns") or {}).get("h24") or {}
    chg = p.get("priceChange") or {}
    F, W, N = [], [], {"notes": [], "unchecked": None, "holders": None, "creator": None}
    if liq < 10000:
        F.append(f"Pool money only {money(liq)} (under $10K)")
    elif liq < 20000:
        W.append(f"Thin pool: {money(liq)}")
    if age_min < 30:
        W.append(f"Only {age_min:.0f} minutes old: sniper bots are still selling")
    if (tx1.get("buys") or 0) >= 20 and (tx1.get("sells") or 0) == 0:
        F.append("Many buys, zero sells in 1h: maybe you cannot sell")
    if mc and liq / mc < 0.05:
        W.append(f"Pool is only {liq / mc * 100:.1f}% of market cap: big sells crash it")
    if (chg.get("h1") or 0) <= -30:
        W.append(f"Falling hard: {chg.get('h1')}% in 1h")
    if (chg.get("h6") or 0) >= 150:
        W.append(f"Already up {round(chg.get('h6'))}% in 6h: you would be buying after the run")
    bubblemap = None
    if chain == "solana":
        solana_safety(b["address"], p["pairAddress"], F, W, N)
        bubblemap = f"https://app.bubblemaps.io/sol/token/{b['address']}"
    elif chain == "robinhood":
        robinhood_safety(b["address"], p["pairAddress"], F, W, N)
    else:
        W.append(f"Chain {chain} not covered: safety check skipped")
    info = p.get("info") or {}
    soc = {"x": None, "telegram": None, "website": None, "image": info.get("imageUrl")}
    for s in info.get("socials") or []:
        kind = (s.get("type") or s.get("platform") or "").lower()
        url = s.get("url") or s.get("handle")
        if kind in ("twitter", "x") and not soc["x"]:
            soc["x"] = url
        elif kind == "telegram" and not soc["telegram"]:
            soc["telegram"] = url
    if info.get("websites"):
        soc["website"] = info["websites"][0].get("url")
    verdict = "FAIL" if F else "NOT CHECKED" if N["unchecked"] else "PASS WITH WARNINGS" if W else "PASS"
    return dict(
        symbol=b["symbol"], name=b["name"], chain=chain, token=b["address"], pair=p["pairAddress"],
        verdict=verdict, unchecked=N["unchecked"], age_h=round(age_min / 60, 1), price=price, mc=mc, liq=liq,
        vol24=(p.get("volume") or {}).get("h24") or 0, buys24=tx24.get("buys") or 0, sells24=tx24.get("sells") or 0,
        chg1=chg.get("h1") or 0, chg6=chg.get("h6") or 0, chg24=chg.get("h24") or 0,
        holders=N["holders"], creator=N["creator"], fails=F, warns=W, chart=p.get("url"), bubblemap=bubblemap,
        plan={"x2": price * 2, "x3": price * 3, "stop": price * 0.67, "max_bet": liq * 0.02}, **soc)


# ---------- step 4: description, label, big trades ----------
def label_for(desc, cats, has_web):
    cats = [c.lower() for c in (cats or [])]
    text = f"{desc} {' '.join(cats)}"
    util = bool(UTIL_WORDS.search(text)) or any(re.search(r"defi|ai|infra|gaming|utility|dex", c) for c in cats)
    meme = bool(MEME_WORDS.search(text)) or "meme" in cats
    if not desc and not has_web:
        return "No description"
    if util and not meme:
        return "Says utility (not verified)"
    if meme and not util:
        return "Looks like a meme"
    if meme and util:
        return "Meme with a utility claim"
    return "Unclear"


def add_info(c, src):
    try:
        a = get_slow(f"{GT}/{src['network']}/tokens/{c['token']}/info")["data"]["attributes"]
    except Exception:
        c["desc"], c["label"], c["gt_score"] = "", "No description", None
        return
    c["desc"] = re.sub(r"\s+", " ", unescape(a.get("description") or "")).strip()[:280]
    if not c["x"] and a.get("twitter_handle"):
        c["x"] = f"https://x.com/{a['twitter_handle']}"
    if not c["telegram"] and a.get("telegram_handle"):
        c["telegram"] = f"https://t.me/{a['telegram_handle']}"
    if not c["website"] and a.get("websites"):
        c["website"] = a["websites"][0]
    if not c["image"] and a.get("image_url"):
        c["image"] = a["image_url"]
    if not c["holders"] and (a.get("holders") or {}).get("count"):
        c["holders"] = a["holders"]["count"]
    c["gt_score"] = round(num(a.get("gt_score"))) if a.get("gt_score") else None
    c["label"] = label_for(c["desc"], a.get("categories"), bool(c["website"]))


def add_big_trades(c, src):
    c["big"] = None
    if not c.get("pair"):
        return
    try:
        d = get_slow(f"{GT}/{src['network']}/pools/{c['pair']}/trades?trade_volume_in_usd_greater_than=1000")
    except Exception:
        return
    since = time.time() * 1000 - 864e5
    big = dict(buys=0, buyUsd=0.0, sells=0, sellUsd=0.0, wallets=set(), buyers={}, sellers={}, top=None)
    for t in d.get("data") or []:
        a = t.get("attributes") or {}
        ts = datetime.fromisoformat(a.get("block_timestamp", "1970-01-01T00:00:00Z").replace("Z", "+00:00")).timestamp() * 1000
        if ts < since:
            continue
        usd, w = num(a.get("volume_in_usd")), a.get("tx_from_address") or ""
        kind = "buy" if a.get("kind") == "buy" else "sell"
        if kind == "buy":
            big["buys"] += 1
            big["buyUsd"] += usd
            if w:
                big["buyers"][w] = big["buyers"].get(w, 0) + usd
        else:
            big["sells"] += 1
            big["sellUsd"] += usd
            if w:
                big["sellers"][w] = big["sellers"].get(w, 0) + usd
        if w:
            big["wallets"].add(w)
        if not big["top"] or usd > big["top"]["usd"]:
            big["top"] = dict(usd=usd, kind=kind, wallet=w, time=a.get("block_timestamp"))
    big["wallets"] = len(big["wallets"])
    # The lesson from COINPUTER: the creator wallet dumped through big trades while holding "0%".
    cr = c.get("creator")
    if cr:
        sold, bought = big["sellers"].get(cr, 0), big["buyers"].get(cr, 0)
        if sold >= 1000:
            c["fails"].append(f"Creator wallet is selling: {money(sold)} in big trades today")
            c["verdict"] = "FAIL"
        elif bought >= 1000:
            c["warns"].append(f"Creator wallet is buying its own coin ({money(bought)}): can be fake volume")
    big["buyers"] = [{"w": w, "usd": round(u)} for w, u in sorted(big["buyers"].items(), key=lambda x: -x[1])[:10]]
    del big["sellers"]
    c["big"] = big


# ---------- order plan: a suggested entry and the exact orders to set (Oct 6 2026) ----------
# Entry = support: the 2-hour VWAP (average price paid, weighted by size). Stop under the 2-hour low.
# Orders are written for Jupiter OTOCO (limit buy that arms its own take-profit and stop-loss).
def make_plan(c, zone, low2h, size):
    price = c["price"]
    if not zone or not price:
        return {"ok": False, "why": "No price history yet to find support."}
    rh = c["chain"] == "robinhood"
    if price < zone * 0.85:
        return {"ok": False, "zone": zone, "why": f"Price is {(1 - price / zone) * 100:.0f}% under support ({money(zone)}): it broke down. No order."}
    at_support = price <= zone * 1.03
    entry = min(price, zone)
    stop = (low2h or entry * 0.8) * 0.98
    if stop >= entry * 0.9:
        stop = entry * 0.85  # give it at least 15% room: these coins swing
    risk = (entry - stop) / entry
    if risk > 0.35:
        return {"ok": False, "zone": zone, "why": f"Stop would sit {risk:.0%} under entry, under the 2-hour low {money(low2h)}. Too risky, no order."}
    above = (price / zone - 1) * 100
    why = (f"Support is {money(zone)}, the average price buyers paid in the last 2 hours. "
           + ("Price is at support now. " if at_support else f"Price is {above:.0f}% above it, so the order waits for a dip. ")
           + f"The stop sits under the 2-hour low ({money(low2h)}), {risk:.0%} below entry.")
    bet = round(min(size, c["liq"] * 0.02))
    legs = [{"part": 0.5, "usd": round(bet * 0.5), "tp": entry * 2, "label": "take profit at 2x"},
            {"part": 0.4, "usd": round(bet * 0.4), "tp": entry * 3, "label": "take profit at 3x"},
            {"part": 0.1, "usd": bet - round(bet * 0.5) - round(bet * 0.4), "tp": None, "label": "moonbag: after it fills, swap the stop for a 40% trailing stop"}]
    return {"ok": True, "zone": zone, "low2h": low2h, "entry": entry, "stop": stop, "risk": risk, "atSupport": at_support,
            "aboveSupport": above, "bet": bet, "expiryH": 12, "legs": legs, "why": why, "manual": rh}


def chart_features(candles, price):
    """Chart pattern snapshot from the last 6 hours of 15-minute candles. Saved for the weekly 'What worked' study."""
    if len(candles) < 4 or not price:
        return None
    last8, last4, prev4 = candles[-8:], candles[-4:], candles[-8:-4]
    vol8 = sum(x[5] for x in last8)
    zone = sum((x[2] + x[3] + x[4]) / 3 * x[5] for x in last8) / vol8 if vol8 else None
    pct = lambda a, b: round((a / b - 1) * 100, 1) if a and b else None
    return dict(
        runup6h=pct(price, candles[0][1]), runup2h=pct(price, last8[0][1]),
        distSupport=pct(price, zone), fromHigh6h=pct(price, max(x[2] for x in candles)),
        swing=round(sum((x[2] - x[3]) / x[3] * 100 for x in last8 if x[3]) / len(last8), 1),
        volTrend=round(sum(x[5] for x in last4) / sum(x[5] for x in prev4), 2) if prev4 and sum(x[5] for x in prev4) else None,
        higherLows=sum(1 for a, b in zip(candles[-5:-1], last4) if b[3] > a[3]),
        greenShare=round(sum(1 for x in last8 if x[4] > x[1]) / len(last8), 2), candles=len(candles))


def add_levels(c, src, size):
    c["order"] = None
    if not c.get("pair"):
        return
    try:
        d = get_slow(f"{GT}/{src['network']}/pools/{c['pair']}/ohlcv/minute?aggregate=15&limit=24")
        candles = sorted(((d.get("data") or {}).get("attributes") or {}).get("ohlcv_list") or [])
    except Exception:
        return
    c["chartF"] = chart_features(candles, c["price"])
    last2h = candles[-8:]
    vol = sum(x[5] for x in last2h)
    zone = (sum((x[2] + x[3] + x[4]) / 3 * x[5] for x in last2h) / vol) if vol > 0 else (sum(x[4] for x in last2h) / len(last2h) if last2h else None)
    low2h = min((x[3] for x in last2h), default=None)
    c["order"] = make_plan(c, zone, low2h, size)


def is_whale(c):
    b = c.get("big") or {}
    return bool(b.get("top") and b["top"]["kind"] == "buy" and b["top"]["usd"] >= WHALE)


# ---------- the scan ----------
def is_pass(c):
    return c["verdict"] in ("PASS", "PASS WITH WARNINGS")


def run_scan(hours, chains):
    result = {"hours": hours, "started": datetime.now(timezone.utc).isoformat(), "auto": True, "sources": []}
    order = {"PASS": 0, "PASS WITH WARNINGS": 1, "NOT CHECKED": 2, "FAIL": 3}
    for key in chains:
        src = SOURCES[key]
        pools, read, planned = fetch_pools(src, hours)
        keep, dropped = prefilter(pools, hours, src["limits"])
        keep = sorted(keep, key=lambda k: k["ageH"])[:20]
        say(f"{src['label']}: {len(keep)} coins left after red-flag filters, running safety checks")
        cards = []
        for i, k in enumerate(keep, 1):
            say(f"{src['label']}: safety check {i} of {len(keep)} ({k['symbol']})")
            try:
                p = find_pair(k["token"], src["dexChain"])
                if p:
                    c = check(p)
                    c["tpb"], c["buyers24"] = k["tpb"], k["buyers24"]
                    # Bots trade the same coin over and over from a few wallets. HNUT: 97 buys per buyer.
                    if k["tpb"] and k["tpb"] > 10:
                        c["fails"].append(f"{k['tpb']:.0f} buys per buyer in 24h: run by bots")
                        c["verdict"] = "FAIL"
                    elif k["tpb"] and k["tpb"] > 3.5:
                        c["warns"].append(f"{k['tpb']:.1f} buys per buyer in 24h: looks like bot churn")
                    if k["buyers24"] and k["buyers24"] < 300 and c["mc"] > 1e6:
                        c["fails"].append(f"Only {k['buyers24']} real buyers in 24h for a {money(c['mc'])} coin")
                        c["verdict"] = "FAIL"
                    if c["verdict"] == "PASS" and c["warns"]:
                        c["verdict"] = "PASS WITH WARNINGS"
                    cards.append(c)
            except Exception as e:
                say(f"{k['symbol']}: check failed ({e})")
            time.sleep(1)
        to_read = [c for c in cards if is_pass(c)]
        for i, c in enumerate(to_read, 1):
            say(f"{src['label']}: reading description {i} of {len(to_read)} ({c['symbol']})")
            add_info(c, src)
            time.sleep(PAUSE)
            say(f"{src['label']}: reading big trades {i} of {len(to_read)} ({c['symbol']})")
            add_big_trades(c, src)
            if is_pass(c):
                time.sleep(PAUSE)
                say(f"{src['label']}: finding entry and targets {i} of {len(to_read)} ({c['symbol']})")
                add_levels(c, src, PAPER.get(key, 250))
            if c["verdict"] == "PASS" and c["warns"]:
                c["verdict"] = "PASS WITH WARNINGS"
            time.sleep(PAUSE)
        cards.sort(key=lambda c: (order[c["verdict"]], c["age_h"]))
        result["sources"].append(dict(key=key, label=src["label"], looked=len(pools), pagesRead=read, pagesPlanned=planned,
                                      dropped=[list(x) for x in dropped], passed=[c for c in cards if is_pass(c)],
                                      unchecked=[c for c in cards if c["verdict"] == "NOT CHECKED"],
                                      failed=[c for c in cards if c["verdict"] == "FAIL"]))
    result["finished"] = datetime.now(timezone.utc).isoformat()
    return result


# ---------- paper portfolio ----------
# Two strategies run side by side on every passed coin (Rainer, Oct 6 2026):
#   "now": buy at the scan price.
#   "dip": wait up to 12h for the price to dip to support (2h VWAP, the average price paid, weighted by size)
#          and bounce (a green 15-minute candle that closes back above it). Stop just under the dip low.
# Exit plan v2 for both: stop until 2x; at 2x sell half and move the stop to entry; at 3x sell 40%;
# the last 10% (moonbag) rides a trailing stop 40% under its peak; time stop after 14 days.
VWAP_HOURS, WATCH_HOURS, BREAK_PCT, MAX_RISK = 2, 12, 0.15, 0.35
NOW_STOP, TRAIL, TIME_STOP_D = 0.70, 0.40, 14


def ts_of(iso):
    return datetime.fromisoformat(iso).timestamp()


def log_passed(track, res):
    added = 0
    now = datetime.now(timezone.utc)
    for s in res["sources"]:
        for c in s["passed"]:
            if c["token"] in track or not c["price"]:
                continue
            b = c.get("big") or {}
            base = dict(
                token=c["token"], pair=c["pair"], chain=c["chain"], source=s["key"], symbol=c["symbol"], name=c["name"],
                label=c.get("label") or "", warns=len(c["warns"]), logged=res["finished"], size=PAPER.get(s["key"], 250),
                price0=c["price"], liq0=c["liq"], mc0=c["mc"], chart=c["chart"], plan="v2",
                features=dict(
                    age_h=c["age_h"], holders=c["holders"], buys24=c["buys24"], sells24=c["sells24"], vol24=c["vol24"],
                    buyers24=c.get("buyers24"), tradesPerBuyer=round(c["tpb"], 1) if c.get("tpb") else None,
                    liqToMc=round(c["liq"] / c["mc"] * 100, 1) if c["mc"] else None,
                    chg1=c["chg1"], chg6=c["chg6"], chg24=c["chg24"], gt_score=c.get("gt_score"), warnings=c["warns"][:6],
                    hasX=bool(safe_url(c["x"])), hasTg=bool(safe_url(c["telegram"])), hasWeb=bool(safe_url(c["website"])),
                    bigBuys=b.get("buys", 0), bigBuyUsd=round(b.get("buyUsd", 0)), bigSells=b.get("sells", 0),
                    bigSellUsd=round(b.get("sellUsd", 0)), bigWallets=b.get("wallets", 0), bigBuyers=b.get("buyers", []),
                    whale=is_whale(c), hourUtc=now.hour, weekday=now.weekday(), window=res["hours"], auto=True,
                    chart=c.get("chartF"), plannedEntry=(c.get("order") or {}).get("entry"), planOk=(c.get("order") or {}).get("ok")),
                now=None, liq=None, best=None, t2=None, exit=None, final=False, checked=None, cash=0.0, pos=1.0)
            track[c["token"]] = dict(base, strategy="now", entry=c["price"], entryT=ts_of(res["finished"]),
                                     stop0=c["price"] * NOW_STOP, outcome="Open")
            track["dip:" + c["token"]] = dict(base, strategy="dip", entry=None, entryT=None, stop0=None, zone=None,
                                              outcome="Waiting for dip", why=None)
            added += 1
    return added


def vwap_before(candles, t0):
    pre = [c for c in candles if t0 - VWAP_HOURS * 3600 <= c[0] < t0]
    vol = sum(c[5] for c in pre)
    if vol > 0:
        return sum((c[2] + c[3] + c[4]) / 3 * c[5] for c in pre) / vol
    return sum(c[4] for c in pre) / len(pre) if pre else None


def watch_dip(e, candles):
    """Look for the dip to support and the bounce. Sets entry, or Skipped / Missed."""
    t0 = ts_of(e["logged"])
    if e.get("zone") is None:
        e["zone"] = vwap_before(candles, t0)
    zone = e["zone"]
    if not zone:
        e.update(outcome="Skipped", why="no price history before the scan", final=True)
        return
    touched, low = False, None
    for t, o, h, l, c, v in sorted(x for x in candles if t0 <= x[0] < t0 + WATCH_HOURS * 3600):
        if not touched and l <= zone:
            touched, low = True, l
        if not touched:
            continue
        low = min(low, l)
        if c < zone * (1 - BREAK_PCT):
            e.update(outcome="Skipped", why=f"broke below support {money(zone)}", final=True)
            return
        if c > zone and c > o:
            stop = low * 0.98
            risk = (c - stop) / c
            if risk > MAX_RISK:
                e.update(outcome="Skipped", why=f"stop would be {risk:.0%} below entry, too risky", final=True)
                return
            e.update(entry=c, entryT=t + 900, stop0=stop, outcome="Open", why=f"bounced off {money(zone)}")
            return
    if time.time() > t0 + WATCH_HOURS * 3600:
        e.update(outcome="Missed", why="dipped but never bounced" if touched else f"never dipped to {money(zone)}", final=True)
    else:
        last = max((x for x in candles if x[0] < t0 + WATCH_HOURS * 3600), default=None)
        above = (last[4] / zone - 1) * 100 if last else 0
        e["why"] = f"waiting for a dip to {money(zone)}" + (f" (price is {above:.0f}% above support)" if above > 30 else "")


def simulate(e, candles):
    """Replay exit plan v2 from the entry. Conservative: inside one candle the stop counts before a target."""
    entry, stop, t_in = e["entry"], e["stop0"], e["entryT"]
    cash, pos, hit2, hit3, peak, best = 0.0, 1.0, False, False, entry, 1.0
    status, exit_t, t2, t3 = "Open", None, None, None
    for t, o, h, l, c, v in sorted(x for x in candles if x[0] >= t_in):
        best = max(best, h / entry)
        if not hit2:
            if l <= stop:
                cash, pos, status, exit_t = cash + pos * stop / entry, 0.0, "Stop hit", t
                break
            if h >= 2 * entry:
                cash, pos, hit2, t2, status = cash + 1.0, 0.5, True, t, "2x hit, rest running"
        if hit2 and not hit3:
            if h >= 3 * entry:
                cash, pos, hit3, t3, peak, status = cash + 1.2, 0.1, True, t, h, "3x hit, moonbag running"
            elif t != t2 and l <= entry:
                cash, pos, status, exit_t = cash + pos, 0.0, "2x, rest out at entry", t
                break
        if hit3 and t != t3:
            peak = max(peak, h)
            if l <= peak * (1 - TRAIL):
                cash, pos, status, exit_t = cash + pos * peak * (1 - TRAIL) / entry, 0.0, "Moonbag trailed out", t
                break
        if t - t_in > TIME_STOP_D * 86400:
            cash, pos, status, exit_t = cash + pos * c / entry, 0.0, "Time stop", t
            break
    e.update(cash=cash, pos=pos, best=best, t2=t2, exit=exit_t, outcome=status, final=pos == 0)


def old_replay(candles, price0):
    stop, x2, x3 = price0 * 0.67, price0 * 2, price0 * 3
    best, hit2, hit3, stopped, done, t2, t3, t_stop = 0, False, False, False, False, None, None, None
    for t, _o, high, low, _c, _v in candles:
        best = max(best, high / price0)
        if done:
            continue
        if not hit2:
            if low <= stop:
                stopped, t_stop, done = True, t, True
                continue
            if high >= x2:
                hit2, t2 = True, t
        if hit2 and high >= x3:
            hit3, t3, done = True, t, True
    return dict(best=best, hit2=hit2, hit3=hit3, stopped=stopped, t2=t2, t3=t3, tStop=t_stop)


def check_results(track):
    for e in track.values():  # an exit before the buy came from an old replay bug: check again
        if e.get("plan") != "v2" and e.get("exit") and e["exit"] < ts_of(e["logged"]):
            e.update(final=False, exit=None, outcome="Open", best=None, t2=None)
    todo = [e for e in track.values() if not e.get("final") and ts_of(e["logged"]) < time.time() - 3600]
    cache = {}
    for i, e in enumerate(todo, 1):
        say(f"Checking {i} of {len(todo)} ({e['symbol']}, {e.get('strategy', 'now')})")
        key = (e["chain"], e["token"])
        if key not in cache:
            try:
                p = find_pair(e["token"], e["chain"])
                price = (num(p.get("priceUsd")), (p.get("liquidity") or {}).get("usd") or 0) if p else (0, 0)
            except Exception:
                price = (e.get("now"), e.get("liq"))
            logged = ts_of(e["logged"])
            tf = "minute?aggregate=15&limit=1000" if (time.time() - logged) / 86400 <= 10 else "hour?limit=1000"
            net = "solana" if e["chain"] == "solana" else "robinhood"
            try:
                d = get_slow(f"{GT}/{net}/pools/{e['pair']}/ohlcv/{tf}")
                candles = ((d.get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
            except Exception:
                candles = None
            cache[key] = (price, candles)
            time.sleep(PAUSE)
        (now_p, liq), candles = cache[key]
        e["now"], e["liq"] = now_p, liq
        age_days = (time.time() - ts_of(e["logged"])) / 86400
        if e.get("plan") == "v2":
            if candles:
                if e["strategy"] == "dip" and not e.get("entry"):
                    watch_dip(e, candles)
                if e.get("entry"):
                    simulate(e, candles)
            if e.get("entry") and not e["final"] and ((liq is not None and liq < 1000) or (now_p and now_p / e["entry"] < 0.1)):
                e.update(cash=e["cash"] + e["pos"] * (now_p or 0) / e["entry"], pos=0.0, outcome="Dead", exit=int(time.time()), final=True)
            if age_days > 21 and not e["final"]:
                if e.get("entry"):
                    e.update(cash=e["cash"] + e["pos"] * (now_p or 0) / e["entry"], pos=0.0, outcome="Time stop")
                e.update(final=True, exit=e.get("exit") or int(time.time()))
        else:  # old trades keep the old plan: half at 2x, rest at 3x, stop -33%
            if candles:
                after = sorted(c for c in candles if c[0] >= ts_of(e["logged"]))
                if after:
                    r = old_replay(after, e["price0"])
                    e["best"], e["t2"] = r["best"], r["t2"]
                    e["outcome"] = "3x hit" if r["hit3"] else "2x hit" if r["hit2"] else "Stop hit" if r["stopped"] else "Open"
                    e["exit"] = r["t3"] if r["hit3"] else r["tStop"] if r["stopped"] else None
            if e["outcome"] == "Open" and ((liq is not None and liq < 1000) or (now_p and e["price0"] and now_p / e["price0"] < 0.1)):
                e["outcome"], e["exit"] = "Dead", int(time.time())
            if e["outcome"] in ("3x hit", "Stop hit", "Dead") or age_days > 14:
                e["final"], e["exit"] = True, e.get("exit") or int(time.time())
        e["checked"] = datetime.now(timezone.utc).isoformat()
    return len(todo)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=6)
    ap.add_argument("--chains", default="pumpfun,robinhood,movers")
    ap.add_argument("--out", default="data")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    track_path = os.path.join(args.out, "track.json")
    try:
        with open(track_path) as fh:
            track = json.load(fh)
    except (OSError, ValueError):
        track = {}
    res = run_scan(args.hours, [c.strip() for c in args.chains.split(",") if c.strip() in SOURCES])
    added = log_passed(track, res)
    say(f"{added} new paper trades")
    checked = check_results(track)
    say(f"{checked} positions re-checked")
    with open(os.path.join(args.out, "latest.json"), "w") as fh:
        json.dump(res, fh, separators=(",", ":"))
    with open(track_path, "w") as fh:
        json.dump(track, fh, separators=(",", ":"))
    for s in res["sources"]:
        say(f"{s['label']}: looked at {s['looked']}, {len(s['passed'])} passed, {len(s['failed'])} failed, {len(s['unchecked'])} unchecked")


if __name__ == "__main__":
    main()
