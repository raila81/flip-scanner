#!/usr/bin/env python3
"""Flip Scanner, fast loop (netcup VPS, every ~90 seconds, since Oct 6 2026).

The GitHub scan runs every 30 minutes and takes 10-15 minutes, so a coin was paper-bought up to 45 minutes
after it passed, mostly after its run (Oct 6 2026: the average paper buy sat 44% under the 6-hour high).
This loop reads only the short lists, checks coins it has not seen, and paper-buys at the minute it checks.

Writes (committed and pushed to the repo, the page reads them from GitHub Pages):
  data/fast.json   the coins found in the last hours, same shape as latest.json
  data/books.json  the playbooks: 7 complete bot setups paper-traded side by side (scanner/playbooks.py)
  data/track.json  the paper portfolio (the GitHub scan no longer touches it: --no-track)
State outside the repo (--state): seen.json, which coins were checked when.

Usage: python3 scanner/fast.py [--loop] [--once] [--no-git] [--state /var/lib/flip-scanner] [--out data]
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scan as S  # noqa: E402
import playbooks as PB  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S.PAUSE = 5              # GeckoTerminal says 30 calls a minute, but 3.5 s still drew "slow down" (30 s lost each); 5 s is faster overall
S.CONTROL_PER_RUN = 2    # the control group grows slowly here, a cycle is short
S.CONTROL_OPEN_MAX = 60
S.CHECK_BUDGET_S = 300
CYCLE_S = 90
MAX_NEW_PER_CYCLE = 6
RECHECK_S = 3600         # a coin that did not pass is looked at again after an hour (it may pass once it is older)
CHECK_EVERY_S = 900      # open paper positions are re-checked every 15 minutes
KEEP_PASSED_H, KEEP_FAILED_H = 6, 2
FAST_SOURCES = ["fresh", "pumpfun", "survivors", "movers", "small"]  # Robinhood stays with the GitHub scan (slow chain, no limit orders)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def load(path, default):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def save(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(obj, fh, separators=(",", ":"))
    os.replace(tmp, path)


def code_hash():
    h = hashlib.sha256()
    for name in sorted(os.listdir(os.path.dirname(os.path.abspath(__file__)))):
        if name.endswith(".py"):
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), name), "rb") as fh:
                h.update(fh.read())
    return h.hexdigest()


# ---------- the survivors list: slow coins, read every 10 minutes and reused between ----------
SURV_EVERY_S = 600
SURV = {"t": 0.0, "pools": []}


def survivor_pools():
    """PumpSwap pools that are busy or trending today: the candidates for the survivors lane (coins 6-48h old)."""
    if time.time() - SURV["t"] < SURV_EVERY_S and SURV["pools"]:
        return SURV["pools"]
    feeds = [(f"busiest PumpSwap p{p}", f"{S.GT}/solana/dexes/pumpswap/pools?sort=h24_tx_count_desc&page={p}") for p in (1, 2, 3, 4)]
    feeds += [(f"volume PumpSwap p{p}", f"{S.GT}/solana/dexes/pumpswap/pools?sort=h24_volume_usd_desc&page={p}") for p in (1, 2)]
    feeds += [("trending 6h", f"{S.GT}/solana/trending_pools?duration=6h&page=1"), ("trending 24h", f"{S.GT}/solana/trending_pools?duration=24h&page=1")]
    pools = {}
    for name, url in feeds:
        try:
            for p in S.get_slow(url).get("data") or []:
                if p.get("attributes", {}).get("pool_created_at") and p["relationships"]["dex"]["data"]["id"] == "pumpswap":
                    pools.setdefault(p["id"], p)
        except Exception as e:
            S.say(f"survivors list {name} failed ({e})")
        time.sleep(S.PAUSE)
    if pools:
        SURV["t"], SURV["pools"] = time.time(), list(pools.values())
        S.say(f"survivors list refreshed: {len(pools)} PumpSwap pools")
    return SURV["pools"]


# ---------- the short lists ----------
def fetch_lists():
    feeds = [
        ("just graduated (pump.fun)", lambda: S.pumpfun_fresh(1, 2.5)[0]),
        ("trending 5m", lambda: S.get_slow(f"{S.GT}/solana/trending_pools?duration=5m&page=1").get("data") or []),
        ("trending 1h", lambda: S.get_slow(f"{S.GT}/solana/trending_pools?duration=1h&page=1").get("data") or []),
        ("busiest PumpSwap", lambda: S.get_slow(f"{S.GT}/solana/dexes/pumpswap/pools?sort=h24_tx_count_desc&page=1").get("data") or []),
    ]
    pools, read = {}, 0
    for name, fn in feeds:
        try:
            for p in fn():
                if p.get("attributes", {}).get("pool_created_at"):
                    pools.setdefault(p["id"], p)
            read += 1
        except Exception as e:
            S.say(f"list {name} failed ({e})")
        time.sleep(S.PAUSE)
    return list(pools.values()), read, len(feeds)


# ---------- one coin, the same checks as the GitHub scan ----------
def check_one(k, src):
    p = S.find_pair(k["token"], src["dexChain"])
    if not p:
        return None
    c = S.check(p, tiny_ok=src.get("tinyOk", False))
    c["tpb"], c["buyers24"] = k["tpb"], k["buyers24"]
    if k["tpb"] and k["tpb"] > 10:
        c["fails"].append(f"{k['tpb']:.0f} buys per buyer in 24h: run by bots")
        c["verdict"] = "FAIL"
    elif k["tpb"] and k["tpb"] > 3.5:
        c["warns"].append(f"{k['tpb']:.1f} buys per buyer in 24h: looks like bot churn")
    if k["buyers24"] and k["buyers24"] < 300 and c["mc"] > 1e6:
        c["fails"].append(f"Only {k['buyers24']} real buyers in 24h for a {S.money(c['mc'])} coin")
        c["verdict"] = "FAIL"
    if c["verdict"] == "PASS" and c["warns"]:
        c["verdict"] = "PASS WITH WARNINGS"
    return c


def big_lane(rejected, seen, now):
    """Safe coins the scanner rejects only for a market cap over $5M, for the "Big coins" playbook. Up to 2 per cycle."""
    cards, done = [], 0
    for r in sorted(rejected, key=lambda r: r["ageH"]):
        if done >= 2:
            break
        if not r["reason"].startswith("market cap over"):
            continue
        st = seen.get(r["token"])
        if st and now - st.get("last", 0) < RECHECK_S:
            continue
        seen.setdefault(r["token"], {"first": now, "firstAgeH": round(r["ageH"], 2)})
        seen[r["token"]].update(last=now, status="big")
        done += 1
        src = S.SOURCES["pumpfun"]
        S.say(f"Big coins: checking {r['symbol']} ({r['ageH']:.1f}h old, {S.money(r['mc'])})")
        try:
            c = check_one(dict(r, tpb=None, buyers24=0), src)
        except Exception as e:
            S.say(f"{r['symbol']}: check failed ({e})")
            c = None
        time.sleep(1)
        if not c:
            continue
        c["fast"], c["firstSeenAgeH"], c["checkedAt"] = True, round(r["ageH"], 2), now_iso()
        if S.is_pass(c):
            S.add_info(c, src)
            time.sleep(S.PAUSE)
            S.add_big_trades(c, src)
            if S.is_pass(c):
                time.sleep(S.PAUSE)
                S.add_levels(c, src, 100)
            if c["verdict"] == "PASS" and c["warns"]:
                c["verdict"] = "PASS WITH WARNINGS"
            time.sleep(S.PAUSE)
        cards.append(c)
    return cards


def cycle(state, track, fast, books, out):
    """One pass: read the lists, check the coins not seen yet, paper-buy the passes. Returns True if files changed."""
    t0 = time.time()
    S.FEED_CACHE.clear()
    S.TAKEN.clear()
    pools, read, planned = fetch_lists()
    surv_pools = survivor_pools()
    seen = state.setdefault("seen", {})
    now = time.time()
    changed = False
    res = {"hours": 6, "started": now_iso(), "auto": True, "fast": True, "sources": []}
    for key in FAST_SOURCES:
        src = S.SOURCES[key]
        limits = dict(src["limits"], skipSeen=True)  # a coin counts once, for the first source that takes it
        src_pools = surv_pools if key == "survivors" else pools
        keep, dropped, rejected = S.prefilter(src_pools, 6, limits)
        S.TAKEN.update(k["token"] for k in keep)
        todo = []
        for k in sorted(keep, key=lambda k: k["ageH"]):  # newest first: timing is the point of this loop
            tok = k["token"]
            if key == "survivors":
                # A coin that passed as a fresh graduate and is still alive at 6+ hours is exactly a survivor: it gets its own
                # entry here. Only the survivor playbooks' own trades count as "done" for this lane.
                if f"surv_swing:{tok}" in books.get("trades", {}):
                    continue
            elif tok in track:
                seen.setdefault(tok, {})["status"] = "passed"
                continue
            st = seen.get(("S:" if key == "survivors" else "") + tok)
            if st and (st.get("status") == "passed" or now - st.get("last", 0) < RECHECK_S):
                continue
            todo.append(k)
        todo = todo[:MAX_NEW_PER_CYCLE]
        cards = []
        for k in todo:
            sk = ("S:" if key == "survivors" else "") + k["token"]
            seen.setdefault(sk, {"first": now, "firstAgeH": round(k["ageH"], 2)})
            seen[sk]["last"] = now
            seen[sk]["status"] = "unchecked"
            S.say(f"{src['label']}: checking {k['symbol']} ({k['ageH']:.1f}h old)")
            try:
                c = check_one(k, src)
            except Exception as e:
                S.say(f"{k['symbol']}: check failed ({e})")
                c = None
            time.sleep(1)
            if not c:
                continue
            c["fast"], c["firstSeenAgeH"], c["checkedAt"] = True, seen[sk].get("firstAgeH", round(k["ageH"], 2)), now_iso()
            if S.is_pass(c):
                S.add_info(c, src)
                time.sleep(S.PAUSE)
                S.add_big_trades(c, src)
                if S.is_pass(c):
                    time.sleep(S.PAUSE)
                    S.add_levels(c, src, S.PAPER.get(key, 250))
                if c["verdict"] == "PASS" and c["warns"]:
                    c["verdict"] = "PASS WITH WARNINGS"
                time.sleep(S.PAUSE)
            seen[sk]["status"] = "passed" if S.is_pass(c) else "failed" if c["verdict"] == "FAIL" else "unchecked"
            cards.append(c)
        failed_safety = [dict(token=c["token"], symbol=c["symbol"], name=c["name"], reason="failed safety: " + c["fails"][0],
                              pair=c["pair"], price=c["price"], liq=c["liq"], mc=c["mc"], ageH=c["age_h"]) for c in cards if c["verdict"] == "FAIL"]
        res["sources"].append(dict(key=key, label="Fast: " + src["label"], looked=len(src_pools), pagesRead=read, pagesPlanned=planned,
                                   rejected=failed_safety + rejected, dropped=[list(x) for x in dropped],
                                   passed=[c for c in cards if S.is_pass(c)], unchecked=[c for c in cards if c["verdict"] == "NOT CHECKED"],
                                   failed=[c for c in cards if c["verdict"] == "FAIL"]))
    # Big-coin lane: rejected only for size, checked for safety, paper traded by the "Big coins" playbook only
    big_rej = {r["token"]: r for s in res["sources"] if s["key"] != "survivors" for r in s["rejected"] if r["reason"].startswith("market cap over")}
    big_cards = big_lane(list(big_rej.values()), seen, now)
    res["finished"] = now_iso()
    opened = PB.consider(books, [(c, s["key"]) for s in res["sources"] for c in s["passed"]] + [(c, "big") for c in big_cards if S.is_pass(c)])
    added = S.log_passed(track, res)
    for s in res["sources"]:
        for c in s["passed"]:
            for k in (c["token"], "dip:" + c["token"]):
                if k in track and track[k].get("source") == s["key"]:  # not an older trade of the same coin from another source
                    track[k]["features"].update(fast=True, firstSeenAgeH=c["firstSeenAgeH"])
    ctl = S.log_control(track, res)
    changed = changed or added or ctl
    res["sources"].append(dict(key="big", label="Fast: Big coins (over $5M market cap, safe)", looked=len(big_rej), pagesRead=read, pagesPlanned=planned,
                               rejected=[], dropped=[], passed=[c for c in big_cards if S.is_pass(c)],
                               unchecked=[c for c in big_cards if c["verdict"] == "NOT CHECKED"], failed=[c for c in big_cards if c["verdict"] == "FAIL"]))
    # Rolling view for the page: passes of the last 6 hours, fails of the last 2
    cut_p, cut_f = time.time() - KEEP_PASSED_H * 3600, time.time() - KEEP_FAILED_H * 3600
    old = {s["key"]: s for s in fast.get("sources", [])}
    for s in res["sources"]:
        s.pop("rejected", None)
        prev = old.get(s["key"], {})
        s["passed"] = s["passed"] + [c for c in prev.get("passed", []) if S.ts_of(c["checkedAt"]) > cut_p and c["token"] not in {x["token"] for x in s["passed"]}]
        for part, cut in (("failed", cut_f), ("unchecked", cut_f)):
            s[part] = s[part] + [c for c in prev.get(part, []) if S.ts_of(c["checkedAt"]) > cut and c["token"] not in {x["token"] for x in s[part]}]
    fast.clear()
    fast.update(res)
    n_pass = sum(len(s["passed"]) for s in res["sources"])
    S.say(f"cycle done in {time.time() - t0:.0f}s: {len(pools)} pools, {added} new paper trades, {ctl} control, {opened} playbook trades, {n_pass} passes shown")
    return True  # fast.json changes every cycle (the finished time), track.json when trades were added


# ---------- git: pull the GitHub scan's latest.json and code, push our two files ----------
def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=180)


def pull():
    r = git("pull", "--rebase", "--autostash", "origin", "main")
    if r.returncode:
        S.say(f"git pull failed: {(r.stderr or r.stdout).strip()[:200]}")
        git("rebase", "--abort")
        return False
    return True


def push(files):
    git("add", *files)
    if git("diff", "--cached", "--quiet").returncode == 0:
        return True
    r = git("commit", "-q", "-m", f"Fast scan {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC")
    if r.returncode:
        S.say(f"git commit failed: {(r.stderr or r.stdout).strip()[:200]}")
        return False
    for attempt in range(3):
        r = git("push", "-q", "origin", "main")
        if r.returncode == 0:
            return True
        S.say(f"git push failed (try {attempt + 1}): {(r.stderr or r.stdout).strip()[:160]}")
        time.sleep(5)
        pull()
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--no-git", action="store_true")
    ap.add_argument("--state", default=os.path.join(ROOT, "data"))
    ap.add_argument("--out", default=os.path.join(ROOT, "data"))
    args = ap.parse_args()
    os.makedirs(args.state, exist_ok=True)
    os.makedirs(args.out, exist_ok=True)
    state_path, track_path, fast_path = os.path.join(args.state, "seen.json"), os.path.join(args.out, "track.json"), os.path.join(args.out, "fast.json")
    books_path = os.path.join(args.out, "books.json")
    code0 = code_hash()
    last_check = 0
    while True:
        started = time.time()
        if not args.no_git:
            pull()
            if code_hash() != code0:
                S.say("scanner code changed: restarting")
                sys.exit(0)  # systemd starts us again with the new code
        state, track, fast, books = load(state_path, {}), load(track_path, {}), load(fast_path, {}), load(books_path, {})
        try:
            cycle(state, track, fast, books, args.out)
        except Exception as e:
            S.say(f"cycle failed ({e})")
        if time.time() - last_check > CHECK_EVERY_S:
            cache = {}
            try:
                n = S.check_results(track, cache)
                S.say(f"{n} paper positions re-checked")
            except Exception as e:
                S.say(f"re-check failed ({e})")
            try:
                n = PB.check_books(books, cache)
                S.say(f"{n} playbook trades re-checked")
            except Exception as e:
                S.say(f"playbook re-check failed ({e})")
            last_check = time.time()
        # forget coins not seen for a day, so the state file stays small
        cut = time.time() - 86400
        state["seen"] = {k: v for k, v in state.get("seen", {}).items() if v.get("last", 0) > cut}
        save(state_path, state)
        save(track_path, track)
        save(fast_path, fast)
        save(books_path, books)
        if not args.no_git:
            push([os.path.relpath(track_path, ROOT), os.path.relpath(fast_path, ROOT), os.path.relpath(books_path, ROOT)])
        if args.once or not args.loop:
            break
        time.sleep(max(20, CYCLE_S - (time.time() - started)))


if __name__ == "__main__":
    main()
