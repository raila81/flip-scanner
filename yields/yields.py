#!/usr/bin/env python3
"""
Yield scanner: finds passive-income pools and sorts them into Low / Mid / High risk.

Runs in the GitHub Actions chain (see .github/workflows/scan.yml) and writes
  data/yields.json          what the page yields.html shows
  data/yields_history.json  a small yield + pool-size history per pool (for the alerts)

Free data, no keys:
  DefiLlama yields   https://yields.llama.fi/pools        (yield now, 30-day average, pool size, stablecoin, IL risk)
  DefiLlama protocols https://api.llama.fi/protocols      (site, audits, age)
  DefiLlama hacks    https://api.llama.fi/hacks           (hack list, used for the "hacked" alert)
  DefiLlama fees     https://api.llama.fi/summary/fees/jupiter-perpetual-exchange  (JLP fee yield)
  Hyperliquid        POST https://api.hyperliquid.xyz/info vaultDetails           (HLP yield)
  Hylo               https://api.hylo.so/stats                                     (hyUSD stability pool, collateral ratio)
  CoinGecko          simple price                                                  (SOL, JUP, JLP, HYPE)

Risk tiers (the page explains them in plain words; change them here and there together):
  Low   big, old, single-asset pools on trusted lenders / savers / SOL staking, yield at most 12%,
        pool at least $50M, yield not far above its 30-day average, no hack in the last year.
  Mid   smaller or younger pools, real-world-asset tokens, perps pools (JLP, HLP), stable-stable LP,
        pools where most of the yield is reward tokens.
  High  volatile LP pools (impermanent loss), anything 20%+ a year, pools under $5M, leverage,
        yields more than 2.5x their 30-day average (a spike), hacked in the last year.
Price risk is shown separately from the tier: none (stablecoin), SOL (staking), mixed (perps pools), coin.
"""
import argparse, json, os, sys, time, urllib.request, urllib.error
from datetime import datetime, timezone

UA = {"User-Agent": "yield-scanner/1.0 (github.com/raila81/flip-scanner)", "Accept": "application/json"}
NOW = time.time()
DAY = 86400


def fetch(url, data=None, timeout=40, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=data, headers={**UA, **({"Content-Type": "application/json"} if data else {})})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except Exception as e:  # noqa
            if i == tries - 1:
                print(f"  failed {url}: {e}", file=sys.stderr)
                return None
            time.sleep(2 + 3 * i)


# ---------- what the page says about each product, in plain words ----------
TRUSTED = {
    "sky-lending", "spark-savings", "sparklend", "maple", "aave-v3", "morpho-blue", "fluid-lending", "ethena-usde",
    "blackrock-buidl", "ondo-yield-assets", "kamino-lend", "jupiter-lend",
    "jito-liquid-staking", "jupiter-staked-sol", "marinade-liquid-staking", "binance-staked-sol", "helius-staked-sol",
    "blazestake", "the-vault-liquid-staking", "jpool", "bybit-staked-sol", "phantom-sol", "sanctum-infinity",
}
RWA = {"onre", "hastra", "ondo-yield-assets", "blackrock-buidl", "centrifuge-protocol", "invesco-ustb", "bitwise-uscc",
       "vaneck-treasury-fund", "apollo-diversified-credit-securitize-fund", "credix"}
LENDERS = {"kamino-lend", "jupiter-lend", "aave-v3", "morpho-blue", "fluid-lending", "sky-lending", "spark-savings",
           "sparklend", "maple", "save", "loopscale-lending", "marginfi", "neutral-trade", "sentora-curator", "project-0",
           "vectis-finance", "reflect-tranches"}
UNVERIFIED = {"hastra"}  # no readable docs or team found on Oct 17 2026
# Pools outside Solana are kept only from this list (blue chips), and only big stablecoin pools.
OTHER_CHAINS = {"Ethereum", "Arbitrum", "Base", "Robinhood Chain", "Hyperliquid L1"}
OTHER_PROJECTS = {"sky-lending", "spark-savings", "sparklend", "maple", "aave-v3", "morpho-blue", "fluid-lending",
                  "ethena-usde", "blackrock-buidl", "pendle"}

WHAT = {
    "kamino-lend": "Lends your coins to Solana leverage traders. Biggest Solana lender.",
    "jupiter-lend": "Jupiter's own lender, launched 2025. Lends to leverage traders.",
    "save": "Old Solana lender (was Solend). Small pools now.",
    "loopscale-lending": "Order-book lender, merging with Orca. Exploited for $5.8M in Apr 2025.",
    "neutral-trade": "Market-neutral trading bot vaults. Lost $3.7M in the Drift hack.",
    "sky-lending": "Sky (was MakerDAO) savings rate. Oldest DeFi dollar.",
    "spark-savings": "Sky's savings product on more chains.",
    "sparklend": "Sky's lender.",
    "maple": "Lends to crypto trading firms against collateral. Loans can go bad.",
    "aave-v3": "Biggest lender in DeFi. Boring, which is good.",
    "morpho-blue": "Lending vaults run by curators (Steakhouse, Gauntlet). Curator picks the risk.",
    "fluid-lending": "Lender by Instadapp.",
    "ethena-usde": "Synthetic dollar. Yield comes from shorting ETH/BTC futures (funding). Can go to 0% in bear markets.",
    "blackrock-buidl": "BlackRock treasury fund token. Needs KYC and a big minimum. Shown for reference.",
    "ondo-yield-assets": "Treasury-backed dollar token (USDY). Yield = US interest rate minus fees.",
    "onre": "Dollar token backed by a Bermuda reinsurance account. Yield = insurance premiums. A bad claims year cuts it.",
    "hastra": "Real-world-asset yield tokens. No readable docs or team found. Unverified.",
    "jito-liquid-staking": "SOL staking token. Paid in SOL, so SOL price matters most.",
    "jupiter-staked-sol": "Jupiter's SOL staking token. Paid in SOL.",
    "marinade-liquid-staking": "SOL staking token. Paid in SOL.",
    "binance-staked-sol": "Binance's SOL staking token. Paid in SOL.",
    "helius-staked-sol": "Helius SOL staking token. Paid in SOL.",
    "blazestake": "SOL staking token. Paid in SOL.",
    "sanctum-infinity": "Basket of SOL staking tokens plus swap fees. A bit above plain staking.",
    "drift-staked-sol": "Drift's SOL staking token. Drift was hacked for $285M in Apr 2026 (the perps side, not the stake pool).",
    "hylo-lsts": "Hylo's SOL staking token.",
    "orca-dex": "Market making. You sell on the way up and buy on the way down (impermanent loss). Needs weekly care.",
    "raydium-amm": "Market making on Raydium. Same impermanent loss. Many meme pairs.",
    "kamino-liquidity": "Kamino runs a market-making position for you. Still impermanent loss.",
    "meteora-dlmm": "Active market making. A job, not passive.",
    "gmx-solana": "You are the house for GMX perps traders on Solana. Small pools.",
    "pendle": "Lock a fixed yield until a date.",
    "unitas-usdu": "Small synthetic dollar. Tiny pool.",
    "reflect-tranches": "Junior slice of a lending book. Takes losses first.",
    "vectis-finance": "Small lender. Tiny pool.",
    "sentora-curator": "Curated Kamino vault (PYUSD). Part of the yield is reward tokens.",
    "project-0": "Small Solana lender.",
    "kyros": "Small SOL staking token.",
}
WHAT_BY_KIND = {
    "lend": "Lends your coins out. Yield moves with borrow demand.",
    "stake": "SOL staking token. Paid in SOL, so SOL price matters most.",
    "rwa": "Real-world asset wrapped in a token.",
    "lp-volatile": "Market making between two coins. Impermanent loss when prices move apart.",
    "lp-stable": "Market making between two dollar coins. Low fees, low risk, small yield.",
    "perps-lp": "You are the house for leverage traders. Earn fees, lose when traders win.",
    "synthetic": "Synthetic dollar or yield token.",
    "stake-gov": "Governance staking paid in the project's own coin.",
}
EXIT = {
    "lend": "Leave when the yield sits under 3% for 2 weeks, or the pool shrinks 30% in a week.",
    "stake": "Decide the SOL price where you sell before you buy. Staking yield is a bonus on a SOL bet.",
    "rwa": "Leave if the 30-day yield drops under 7% or the token price falls two days in a row.",
    "lp-volatile": "Close when the price leaves your range. Take fees out weekly, do not re-add them.",
    "lp-stable": "Leave if one of the two dollar coins trades under $0.99.",
    "perps-lp": "Set a SOL price to sell at before you buy. Leave if monthly fees fall under $2M.",
    "synthetic": "Leave if the token trades under $0.99 or the yield drops under 3%.",
    "stake-gov": "Only stake what you would hold 12 months. Unstaking takes 30 days.",
}


def kind_of(p):
    proj, sym, exp = p["project"], p["symbol"].upper(), p.get("exposure")
    if proj in RWA:
        return "rwa"
    if exp == "multi":
        return "lp-volatile" if p.get("ilRisk") == "yes" else "lp-stable"
    if proj in LENDERS or proj == "pendle":
        return "lend"
    if proj == "ethena-usde" or proj == "unitas-usdu":
        return "synthetic"
    if sym.endswith("SOL") or sym == "INF":
        return "stake"
    return "lend" if p.get("stablecoin") else "synthetic"


def price_risk(p, kind):
    if kind == "perps-lp":
        return "mixed"
    if kind in ("lp-volatile",):
        return "coin"
    if p.get("stablecoin") or kind in ("rwa", "lp-stable", "synthetic"):
        return "none"
    if kind == "stake" or "SOL" in p["symbol"].upper():
        return "SOL"
    return "coin"


def tier_of(row):
    apy, tvl, m30, kind = row["apy"] or 0, row["tvl"] or 0, row.get("apy30d") or 0, row["kind"]
    reasons = []
    t = "Mid"
    if kind == "lp-volatile":
        t, reasons = "High", ["volatile LP (impermanent loss)"]
    elif apy >= 20:
        t, reasons = "High", ["20%+ a year"]
    elif tvl < 5e6:
        t, reasons = "High", ["pool under $5M"]
    elif m30 > 0 and apy > 2.5 * m30 and apy > 8:
        t, reasons = "High", ["yield is a spike (2.5x its 30-day average)"]
    elif kind in ("perps-lp", "rwa", "lp-stable", "synthetic", "stake-gov"):
        t, reasons = "Mid", [{"perps-lp": "perps pool, trader risk", "rwa": "real-world asset", "lp-stable": "stable LP",
                              "synthetic": "synthetic dollar", "stake-gov": "paid in own coin"}[kind]]
        if row["project"] in ("blackrock-buidl", "ondo-yield-assets") and tvl >= 50e6:
            t, reasons = "Low", ["treasury-backed, big"]
    elif (row.get("apyReward") or 0) > 0.5 * apy and apy > 0:
        t, reasons = "Mid", ["more than half the yield is reward tokens"]
    elif row["project"] in TRUSTED and tvl >= 50e6 and apy <= 12:
        t, reasons = "Low", ["trusted, big, single asset"]
    else:
        reasons = ["smaller or younger pool"]
    if row.get("unverified"):
        t = "High" if t == "Low" else t
        reasons.append("unverified project")
    if row.get("hacked") and row["hacked"].get("material"):
        t = {"Low": "Mid", "Mid": "High", "High": "High"}[t]
        reasons.append(f"hacked {row['hacked']['when']}")
    if kind == "stake-gov":
        t = "High"
    row["tier"], row["why"] = t, "; ".join(reasons)
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data")
    ap.add_argument("--min-tvl", type=float, default=1e6)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    hist_path = os.path.join(a.out, "yields_history.json")
    try:
        hist = json.load(open(hist_path))
    except Exception:
        hist = {}

    print("DefiLlama pools")
    pools = (fetch("https://yields.llama.fi/pools") or {}).get("data") or []
    print("DefiLlama protocols, hacks")
    protos = {p["slug"]: p for p in (fetch("https://api.llama.fi/protocols") or [])}
    hacks = fetch("https://api.llama.fi/hacks") or []
    recent_hacks = [h for h in hacks if (h.get("date") or 0) > NOW - 365 * DAY]

    RELATED = {"drift-staked-sol": "Drift Trade", "neutral-trade": "Drift Trade"}  # same team or direct victim

    def hacked(project):
        meta = protos.get(project) or {}
        name = (meta.get("name") or project).lower()
        pid = str(meta.get("id") or "")
        want = RELATED.get(project, "").lower()
        for h in recent_hacks:
            hn = (h.get("name") or "").lower()
            if hn and (hn == name or (pid and str(h.get("defillamaId")) == pid) or (want and hn == want)):
                amt = h.get("amount") or 0
                return {"name": h.get("name"), "amount": amt, "when": datetime.fromtimestamp(h["date"], timezone.utc).strftime("%b %Y"),
                        "technique": h.get("technique"), "material": amt >= 10e6}
        return None

    rows = []
    for p in pools:
        tvl, apy = p.get("tvlUsd") or 0, p.get("apy")
        if apy is None or apy < 1 or tvl < a.min_tvl:
            continue
        chain, proj = p.get("chain"), p.get("project")
        if chain != "Solana":
            if not (chain in OTHER_CHAINS and proj in OTHER_PROJECTS and p.get("stablecoin") and tvl >= 100e6 and p.get("exposure") == "single"):
                continue
        if apy > 400:
            continue
        kind = kind_of(p)
        meta = protos.get(proj) or {}
        row = {
            "id": p["pool"], "project": proj, "projectName": meta.get("name") or proj.replace("-", " ").title(),
            "url": meta.get("url"), "llama": f"https://defillama.com/yields/pool/{p['pool']}",
            "symbol": p["symbol"], "chain": chain, "kind": kind, "stable": bool(p.get("stablecoin")),
            "priceRisk": price_risk(p, kind), "tvl": round(tvl), "apy": round(apy, 2),
            "apyBase": round(p.get("apyBase") or 0, 2), "apyReward": round(p.get("apyReward") or 0, 2),
            "apy30d": round(p.get("apyMean30d") or 0, 2),
            "ageDays": int((NOW - meta["listedAt"]) / DAY) if meta.get("listedAt") else None,
            "audits": meta.get("audits"), "unverified": proj in UNVERIFIED, "hacked": hacked(proj),
            "what": WHAT.get(proj) or WHAT_BY_KIND[kind], "exit": EXIT[kind],
        }
        rows.append(tier_of(row))

    # keep the volatile LP list short: the biggest 40 pools
    lp = sorted([r for r in rows if r["kind"] == "lp-volatile"], key=lambda r: -r["tvl"])[:40]
    rows = [r for r in rows if r["kind"] != "lp-volatile"] + lp

    # ---------- custom rows ----------
    print("prices, JLP, HLP, Hylo")
    prices = fetch("https://api.coingecko.com/api/v3/simple/price?ids=solana,jupiter-exchange-solana,hyperliquid,"
                   "jupiter-perpetuals-liquidity-provider-token&vs_currencies=usd&include_24hr_change=true") or {}
    pr = {"SOL": (prices.get("solana") or {}).get("usd"), "JUP": (prices.get("jupiter-exchange-solana") or {}).get("usd"),
          "HYPE": (prices.get("hyperliquid") or {}).get("usd"), "JLP": (prices.get("jupiter-perpetuals-liquidity-provider-token") or {}).get("usd")}
    extras, notes = [], {}

    fees = fetch("https://api.llama.fi/summary/fees/jupiter-perpetual-exchange") or {}
    jlp_tvl = fetch("https://api.llama.fi/tvl/jupiter-perpetual-exchange")
    if fees.get("total30d") and isinstance(jlp_tvl, (int, float)) and jlp_tvl > 0:
        fee_apy = 0.75 * fees["total30d"] * 12 / jlp_tvl * 100
        notes["jlpFees30d"] = fees["total30d"]
        extras.append(tier_of({
            "id": "custom-jlp", "project": "jupiter-perpetual-exchange", "projectName": "Jupiter Perps (JLP)", "url": "https://jup.ag/perps-earn",
            "llama": "https://defillama.com/protocol/jupiter-perpetual-exchange", "symbol": "JLP", "chain": "Solana", "kind": "perps-lp",
            "stable": False, "priceRisk": "mixed", "tvl": round(jlp_tvl), "apy": round(fee_apy, 2), "apyBase": round(fee_apy, 2), "apyReward": 0,
            "apy30d": round(fee_apy, 2), "ageDays": None, "audits": None, "unverified": False, "hacked": None,
            "what": f"You are the house for Jupiter leverage traders. Holds SOL, ETH, BTC, USDC. Fee yield = 75% of fees (${fees['total30d']/1e6:.1f}M last 30 days) over the pool; trader wins and the basket price move it up or down.",
            "exit": EXIT["perps-lp"], "price": pr["JLP"]}))

    hlp = fetch("https://api.hyperliquid.xyz/info", data=json.dumps({"type": "vaultDetails", "vaultAddress": "0xdfc24b077bc1425ad1dea75bcb6f8158e10df303"}).encode())
    if hlp and hlp.get("apr") is not None:
        acct = None
        for per, v in hlp.get("portfolio", []):
            if per == "allTime" and v.get("accountValueHistory"):
                acct = float(v["accountValueHistory"][-1][1])
        month_pnl = None
        for per, v in hlp.get("portfolio", []):
            if per == "month" and v.get("pnlHistory"):
                month_pnl = float(v["pnlHistory"][-1][1])
        notes["hlpMonthPnl"] = month_pnl
        extras.append(tier_of({
            "id": "custom-hlp", "project": "hyperliquid-hlp", "projectName": "Hyperliquid HLP", "url": "https://app.hyperliquid.xyz/vaults/0xdfc24b077bc1425ad1dea75bcb6f8158e10df303",
            "llama": "https://defillama.com/protocol/hyperliquid", "symbol": "HLP", "chain": "Hyperliquid L1", "kind": "perps-lp", "stable": False,
            "priceRisk": "mixed", "tvl": round(acct or 0), "apy": round(float(hlp["apr"]) * 100, 2), "apyBase": round(float(hlp["apr"]) * 100, 2),
            "apyReward": 0, "apy30d": round(float(hlp["apr"]) * 100, 2), "ageDays": None, "audits": None, "unverified": False, "hacked": None,
            "what": f"You are the house for Hyperliquid traders. Last 30 days: {'+' if (month_pnl or 0) >= 0 else ''}${(month_pnl or 0)/1e6:.2f}M profit on ${(acct or 0)/1e6:.0f}M. 4-day wait to withdraw. Not on Solana.",
            "exit": "Leave after two losing months in a row. Remember the 4-day withdraw wait."}))

    hy = fetch("https://api.hylo.so/stats") or {}
    ex, sp = hy.get("exchangeStats") or {}, hy.get("stabilityPoolStats") or {}
    if ex:
        notes["hyloCollateralRatio"] = ex.get("collateralRatio")
        notes["hyloMode"] = ex.get("stabilityMode")
        extras.append(tier_of({
            "id": "custom-hylo", "project": "hylo", "projectName": "Hylo hyUSD stability pool (sHYUSD)", "url": "https://app.hylo.so",
            "llama": "https://defillama.com/protocol/hylo", "symbol": "sHYUSD", "chain": "Solana", "kind": "synthetic", "stable": True, "priceRisk": "none",
            "tvl": round(sp.get("stablecoinInPool") or 0), "apy": None, "apyBase": 0, "apyReward": 0, "apy30d": None, "ageDays": None, "audits": None,
            "unverified": False, "hacked": None,
            "what": f"Dollar coin backed by staked SOL; the leverage coin xSOL takes the price risk. Collateral ratio {ex.get('collateralRatio', 0):.2f}, mode {ex.get('stabilityMode')}, protocol TVL ${(ex.get('totalValueLocked') or 0)/1e6:.0f}M. Yield is not published by the API (was 5-8% in Oct 2026; the '18%' from 2025 is gone).",
            "exit": "Leave if the collateral ratio drops under 1.3 or the mode leaves Neutral."}))

    if pr.get("JUP"):
        staked = 1.1e9  # staked JUP, from Oct 2026 reports; update by hand when a new number is public
        jup_apy = 50e6 * 4 / staked * 100
        extras.append(tier_of({
            "id": "custom-jup", "project": "jupiter-staking", "projectName": "JUP staking (ASR)", "url": "https://vote.jup.ag",
            "llama": "https://defillama.com/protocol/jupiter", "symbol": "JUP", "chain": "Solana", "kind": "stake-gov", "stable": False, "priceRisk": "coin",
            "tvl": round(staked * pr["JUP"]), "apy": round(jup_apy, 1), "apyBase": round(jup_apy, 1), "apyReward": 0, "apy30d": round(jup_apy, 1),
            "ageDays": None, "audits": None, "unverified": False, "hacked": None, "price": pr["JUP"],
            "what": f"Stake JUP and vote; 50M JUP a quarter is split among about {staked/1e9:.1f}B staked JUP. Paid in JUP (${pr['JUP']:.3f}), so you win only if JUP stops falling. 30-day unstake.",
            "exit": EXIT["stake-gov"]}))
    rows += extras

    # ---------- history and alerts ----------
    def point_at(series, days_back):
        target = NOW - days_back * DAY
        best = None
        for ts, apy, tvl in series:
            if ts <= target + 0.5 * DAY and (best is None or abs(ts - target) < abs(best[0] - target)):
                best = (ts, apy, tvl)
        return best

    alerts, seen_alerts = [], set()
    for r in rows:
        s = hist.get(r["id"], [])
        if not s or NOW - s[-1][0] >= 5 * 3600:
            s.append([int(NOW), r["apy"], r["tvl"]])
        s = [x for x in s if x[0] > NOW - 15 * DAY]
        hist[r["id"]] = s
        old = point_at(s, 7)
        r["apy7dAgo"] = old[1] if old else None
        r["tvl7dAgo"] = old[2] if old else None
        al = []
        label = f"{r['projectName']} {r['symbol']}"
        if r.get("hacked"):
            h = r["hacked"]
            lvl = "danger" if h.get("material") else "info"
            size = f"${h['amount']/1e6:.0f}M" if h.get("material") else f"small, ${(h.get('amount') or 0)/1e6:.1f}M"
            al.append((lvl, f"{h['name']} hacked {h['when']} ({size}, {h.get('technique') or 'unknown'})."))
        if r.get("unverified"):
            al.append(("warn", "No readable docs or team found. Unverified."))
        if r["apy"] is not None and r["apy30d"] and r["apy"] > 2.5 * r["apy30d"] and r["apy"] > 8:
            al.append(("warn", f"Yield {r['apy']:.1f}% is a spike; 30-day average is {r['apy30d']:.1f}%."))
        if old and old[1] and r["apy"] is not None and r["apy"] < 0.6 * old[1]:
            al.append(("warn", f"Yield fell from {old[1]:.1f}% to {r['apy']:.1f}% in 7 days."))
        if old and old[2] and r["tvl"] < 0.7 * old[2]:
            al.append(("danger", f"Pool shrank from ${old[2]/1e6:.1f}M to ${r['tvl']/1e6:.1f}M in 7 days. People are leaving."))
        if r["stable"] and r["kind"] in ("lend", "synthetic") and r["apy"] is not None and 0 < r["apy"] < 3 and r["tier"] == "Low":
            al.append(("info", f"Yield under 3% ({r['apy']:.1f}%). Money does better elsewhere."))
        if r["id"] == "custom-jlp" and notes.get("jlpFees30d") and notes["jlpFees30d"] < 2e6:
            al.append(("danger", f"Jupiter perps fees fell under $2M a month (${notes['jlpFees30d']/1e6:.1f}M). Exit rule hit."))
        if r["id"] == "custom-hylo" and (notes.get("hyloCollateralRatio") or 9) < 1.3:
            al.append(("danger", f"Hylo collateral ratio {notes['hyloCollateralRatio']:.2f} is under 1.3."))
        if r["id"] == "custom-hlp" and (notes.get("hlpMonthPnl") or 0) < 0:
            al.append(("warn", f"HLP lost ${-notes['hlpMonthPnl']/1e6:.2f}M in the last 30 days."))
        r["alerts"] = [{"level": lv, "text": tx} for lv, tx in al]
        for lv, tx in al:
            key = (r["project"], tx) if ("hacked" in tx or "Unverified" in tx) else (r["id"], tx)
            if key in seen_alerts:
                continue
            seen_alerts.add(key)
            alerts.append({"id": r["id"], "product": r["projectName"] if key[0] == r["project"] else label, "tier": r["tier"], "level": lv, "text": tx})
    # drop history of pools no longer seen for 15 days
    hist = {k: v for k, v in hist.items() if v and v[-1][0] > NOW - 15 * DAY}

    order = {"danger": 0, "warn": 1, "info": 2}
    alerts.sort(key=lambda x: (order[x["level"]], x["product"]))
    rows.sort(key=lambda r: (-(r["tvl"] or 0)))
    sol_hacks = [{"name": h.get("name"), "amount": h.get("amount"), "when": datetime.fromtimestamp(h["date"], timezone.utc).strftime("%Y-%m-%d"),
                  "technique": h.get("technique")} for h in sorted(recent_hacks, key=lambda h: -(h.get("amount") or 0)) if "Solana" in (h.get("chain") or [])][:12]

    out = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "prices": pr, "notes": notes,
        "counts": {t: sum(1 for r in rows if r["tier"] == t) for t in ("Low", "Mid", "High")},
        "rows": rows, "alerts": alerts, "solanaHacks12m": sol_hacks,
        "rules": {
            "Low": "Big (over $50M), single-asset pools on trusted lenders, savers or SOL staking. Yield at most 12% and close to its 30-day average. No hack in the last year.",
            "Mid": "Smaller or younger pools, real-world-asset tokens, perps pools (JLP, HLP), stable-stable LP, pools where most of the yield is reward tokens.",
            "High": "Volatile LP pools (impermanent loss), 20%+ a year, pools under $5M, leverage, yield spikes above 2.5x the 30-day average, anything hacked in the last year.",
        },
    }
    json.dump(out, open(os.path.join(a.out, "yields.json"), "w"), separators=(",", ":"))
    json.dump(hist, open(hist_path, "w"), separators=(",", ":"))
    print(f"{len(rows)} pools: {out['counts']}, {len(alerts)} alerts. SOL ${pr.get('SOL')}, JUP ${pr.get('JUP')}")


if __name__ == "__main__":
    main()
