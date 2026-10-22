#!/usr/bin/env python3
"""
Live price feed for open paper positions (Oct 22 2026): step one of the bot.

Watches the pool of every open Tight trail / Famous exact paper trade on Solana in real time, so we learn what a
real sell would have fetched at the moment the paper stop fired (the paper book only sees 1-minute candles,
minutes late, and fills a stop at the candle low minus 10%).

How:
  - scanner/playbooks.py writes data/feed/watch.json the moment it opens or closes one of these paper trades.
  - This service subscribes to the pool's two vault accounts (token and SOL) over a Solana WebSocket
    (accountSubscribe, commitment processed), so every swap in the pool shows up within a second as new reserves.
  - Each tick is kept in memory; every 20 s a summary is written to data/feed/<book>_<token>.json: chain price at
    the paper buy (entry staleness), the price path, and after the close the real fill a $25 sell would have had
    at the paper stop level 0, 2, 5, 10 and 30 s after the trigger (constant product, 0.3% fee).
  - fast.py attaches that summary to the trade record (e["feed"]) when the trade closes.

Runs as systemd service flip-feed on the VPS, next to flip-fast. Restarts itself when this file changes.
Env: FEED_WS (default public Solana WebSocket), FEED_RPC (HTTP for the vault lookup), FEED_DATA (data dir).
"""
import asyncio, hashlib, json, os, sys, time, urllib.request
import websockets

WS = os.environ.get("FEED_WS", "wss://api.mainnet-beta.solana.com")
RPC = os.environ.get("FEED_RPC", "https://api.mainnet-beta.solana.com")
DATA = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("FEED_DATA", "data")
FEED_DIR = os.path.join(DATA, "feed")
WATCH = os.path.join(FEED_DIR, "watch.json")
WSOL = "So11111111111111111111111111111111111111112"
FEE = 0.003
LAGS = (0, 2, 5, 10, 30)
KEEP_AFTER_CLOSE = 240     # seconds of ticks kept after the paper close
MAX_WATCH_S = 4 * 3600     # drop a watch after 4 hours whatever happened
UA = {"User-Agent": "flip-feed/1.0 (github.com/raila81/flip-scanner)", "Content-Type": "application/json"}


def say(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def rpc(method, params):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(RPC, data=body, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read()).get("result")


def fname(key):
    return os.path.join(FEED_DIR, key.replace(":", "_").replace("/", "_") + ".json")


def save(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(obj, fh, separators=(",", ":"))
    os.replace(tmp, path)


class Watch:
    def __init__(self, key, w):
        self.key, self.w = key, w
        self.pool, self.token = w["pair"], w["token"]
        self.started = time.time()
        self.base_vault = self.quote_vault = None
        self.base = self.quote = None
        self.ticks = []          # [t_ms, slot, base_ui, quote_ui]
        self.status = "new"
        self.subs = {}           # subscription id -> "base"/"quote"
        self.last_write = 0
        self.closed_at = None

    def price_sol(self):
        return (self.quote / self.base) if self.base and self.quote else None


class Feed:
    def __init__(self):
        self.watches = {}
        self.sol_usd, self.sol_t = 0.0, 0
        self.ws = None
        self.req_id = 0
        self.pending = {}        # request id -> vault account being subscribed
        self.sub_owner = {}      # subscription id -> vault account
        self.acct_sid = {}       # vault account -> subscription id
        self.watchers = {}       # vault account -> [(watch, side)]: two books on the same coin share one subscription
        # (Oct 23 2026: subscribing the same account twice returns one subscription id, so one watch lost a side and its price ran wild)
        self.watch_mtime = 0

    # ---------- the watch list written by the playbooks ----------
    def load_watch(self):
        try:
            m = os.path.getmtime(WATCH)
        except OSError:
            return
        if m == self.watch_mtime:
            return
        self.watch_mtime = m
        try:
            items = json.load(open(WATCH))
        except Exception:
            return
        now = time.time()
        for key, w in items.items():
            if w.get("chain") != "solana" or not w.get("entryT"):
                continue
            if key not in self.watches:
                if now - w["entryT"] > 1800 and not w.get("closedAt"):
                    continue  # too old to be useful (we would miss the first minutes anyway)
                if w.get("closedAt") and now - w["closedAt"] > KEEP_AFTER_CLOSE:
                    continue
                self.watches[key] = Watch(key, w)
                say(f"watch {w.get('symbol')} ({key})")
            else:
                self.watches[key].w = w
                if w.get("closedAt") and not self.watches[key].closed_at:
                    self.watches[key].closed_at = w["closedAt"]
                    say(f"closed on paper: {w.get('symbol')} {w.get('outcome')}")

    # ---------- SOL price ----------
    def refresh_sol(self):
        if time.time() - self.sol_t < 60:
            return
        try:
            req = urllib.request.Request(f"https://api.dexscreener.com/tokens/v1/solana/{WSOL}", headers={"User-Agent": UA["User-Agent"]})
            d = json.load(urllib.request.urlopen(req, timeout=15))
            for p in d:
                if p.get("baseToken", {}).get("address") == WSOL and float(p.get("priceUsd") or 0) > 10:
                    self.sol_usd = float(p["priceUsd"])
                    break
        except Exception as e:
            say(f"SOL price failed ({e})")
        self.sol_t = time.time()

    # ---------- vaults ----------
    def find_vaults(self, wt):
        try:
            b = rpc("getTokenAccountsByOwner", [wt.pool, {"mint": wt.token}, {"encoding": "jsonParsed"}])
            q = rpc("getTokenAccountsByOwner", [wt.pool, {"mint": WSOL}, {"encoding": "jsonParsed"}])
        except Exception as e:
            wt.status = f"vault lookup failed: {e}"
            return False
        bv, qv = (b or {}).get("value") or [], (q or {}).get("value") or []
        if not bv or not qv:
            wt.status = "unsupported pool (vaults not owned by the pool)"
            return False
        amt = lambda a: float(a["account"]["data"]["parsed"]["info"]["tokenAmount"]["uiAmount"] or 0)
        b0, q0 = max(bv, key=amt), max(qv, key=amt)  # a pool can own extra small accounts (fees); the reserve is the biggest
        wt.base_vault, wt.quote_vault = b0["pubkey"], q0["pubkey"]
        wt.base, wt.quote = amt(b0), amt(q0)
        if len(bv) > 1 or len(qv) > 1:
            say(f"{wt.w.get('symbol')}: pool owns {len(bv)} token and {len(qv)} SOL accounts, using the biggest")
        wt.ticks.append([int(time.time() * 1000), 0, wt.base, wt.quote])
        wt.status = "live"
        return True

    async def send(self, method, params, tag=None):
        self.req_id += 1
        if tag:
            self.pending[self.req_id] = tag
        await self.ws.send(json.dumps({"jsonrpc": "2.0", "id": self.req_id, "method": method, "params": params}))

    async def subscribe(self, wt):
        for side, acct in (("base", wt.base_vault), ("quote", wt.quote_vault)):
            lst = self.watchers.setdefault(acct, [])
            if not any(w is wt for w, _ in lst):
                lst.append((wt, side))
            if acct not in self.acct_sid and acct not in self.pending.values():
                await self.send("accountSubscribe", [acct, {"encoding": "jsonParsed", "commitment": "processed"}], acct)

    async def unsubscribe(self, wt):
        for acct in (wt.base_vault, wt.quote_vault):
            if not acct:
                continue
            lst = [(w, sd) for w, sd in self.watchers.get(acct, []) if w is not wt]
            if lst:
                self.watchers[acct] = lst
                continue
            self.watchers.pop(acct, None)
            sid = self.acct_sid.pop(acct, None)
            if sid is not None:
                self.sub_owner.pop(sid, None)
                try:
                    await self.send("accountUnsubscribe", [sid])
                except Exception:
                    pass

    # ---------- summaries ----------
    def summary(self, wt, final=False):
        w = wt.w
        entry_usd = w.get("entry") or 0
        sol = self.sol_usd or 0
        t0 = wt.ticks[0] if wt.ticks else None
        chain_entry_sol = (t0[3] / t0[2]) if t0 and t0[2] else None
        out = {"key": wt.key, "book": w.get("book"), "symbol": w.get("symbol"), "token": wt.token, "pool": wt.pool,
               "startedAt": int(wt.started), "paperEntryT": w.get("entryT"), "paperEntry": entry_usd, "solUsd": sol,
               "feedDelayS": round(wt.started - (w.get("entryT") or wt.started), 1), "status": wt.status, "ticksN": len(wt.ticks),
               "chainEntrySol": chain_entry_sol, "chainEntryUsd": (chain_entry_sol * sol) if (chain_entry_sol and sol) else None,
               "entryStale": round(chain_entry_sol * sol / entry_usd, 4) if (chain_entry_sol and sol and entry_usd) else None,
               "closedAt": wt.closed_at, "outcome": w.get("outcome"), "stopLevel": w.get("stopLevel"), "final": final}
        if wt.ticks:
            lo = min(wt.ticks, key=lambda t: t[3] / t[2] if t[2] else 1e9)
            out["minPriceUsd"] = (lo[3] / lo[2] * sol) if lo[2] and sol else None
            out["lastPriceUsd"] = (wt.ticks[-1][3] / wt.ticks[-1][2] * sol) if wt.ticks[-1][2] and sol else None
        # the stop test: first tick at or under the paper stop level after the paper buy, then what a $25 sell gets L seconds later
        level_usd = w.get("stopLevel")
        if level_usd and sol and entry_usd and wt.ticks:
            level_sol = level_usd / sol
            tokens = 25.0 / entry_usd
            entry_ms = (w.get("entryT") or wt.started) * 1000
            start_ms = entry_ms
            if (w.get("best") or 1) >= 1.2:
                # a trailing stop: its level sits under the peak, so the trigger can only come after the peak
                exit_ms = ((w.get("exit") or w.get("closedAt") or time.time()) + 60) * 1000
                run = [t for t in wt.ticks if entry_ms <= t[0] <= exit_ms and t[2]]
                if run:
                    start_ms = max(run, key=lambda t: t[3] / t[2])[0]
            trig = next((t for t in wt.ticks if t[0] >= start_ms and t[2] and t[3] / t[2] <= level_sol), None)
            if trig:
                fills = {}
                for lag in LAGS:
                    at = trig[0] + lag * 1000
                    last = [t for t in wt.ticks if t[0] <= at]
                    b, q = (last[-1] if last else trig)[2], (last[-1] if last else trig)[3]
                    got = q - (b * q) / (b + tokens * (1 - FEE))
                    fills[str(lag)] = round((got / tokens) / level_sol, 4)
                out["stop"] = {"triggerT": trig[0] / 1000, "trailing": (w.get("best") or 1) >= 1.2, "triggerAfterEntryS": round(trig[0] / 1000 - (w.get("entryT") or 0), 1),
                               "fillVsLevel": fills, "ticksAfter30s": sum(1 for t in wt.ticks if trig[0] < t[0] <= trig[0] + 30000)}
            else:
                out["stop"] = {"triggerT": None, "note": "level never touched on chain"}
        # path: all ticks in the first 3 minutes and around the trigger, else one per 5 s; capped
        path, last_t = [], 0
        trig_ms = (out.get("stop") or {}).get("triggerT")
        trig_ms = trig_ms * 1000 if trig_ms else None
        for t in wt.ticks:
            dense = (t[0] - wt.ticks[0][0] < 180000) or (trig_ms and abs(t[0] - trig_ms) < 90000)
            if dense or t[0] - last_t >= 5000:
                path.append([t[0] // 1000, round(t[3] / t[2] * sol, 10) if t[2] and sol else None, round(t[3], 3)])
                last_t = t[0]
        if len(path) > 900:
            step = len(path) // 900 + 1
            path = path[::step]
        out["path"] = path
        return out

    def write_summaries(self, force=False):
        now = time.time()
        for key, wt in list(self.watches.items()):
            done = (wt.closed_at and now - wt.closed_at > KEEP_AFTER_CLOSE) or (now - wt.started > MAX_WATCH_S) or wt.status.startswith("unsupported")
            if force or done or now - wt.last_write >= 20:
                try:
                    save(fname(key), self.summary(wt, final=bool(done)))
                except Exception as e:
                    say(f"write failed {key}: {e}")
                wt.last_write = now
            if done:
                say(f"done {wt.w.get('symbol')}: {wt.status}, {len(wt.ticks)} ticks")
                asyncio.ensure_future(self.unsubscribe(wt))
                self.watches.pop(key, None)

    # ---------- main loop ----------
    async def run(self):
        os.makedirs(FEED_DIR, exist_ok=True)
        code0 = hashlib.sha256(open(__file__, "rb").read()).hexdigest()
        while True:
            try:
                async with websockets.connect(WS, ping_interval=20, ping_timeout=20, max_size=2**23, compression=None) as ws:
                    self.ws = ws
                    say(f"connected {WS.split('?')[0]}")  # never log the API key
                    # re-subscribe whatever we were watching
                    self.sub_owner, self.pending, self.acct_sid = {}, {}, {}
                    for wt in self.watches.values():
                        if wt.status == "live":
                            await self.subscribe(wt)
                    last_house = 0
                    while True:
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=2)
                            self.on_message(json.loads(raw))
                        except asyncio.TimeoutError:
                            pass
                        now = time.time()
                        if now - last_house >= 2:
                            last_house = now
                            self.load_watch()
                            self.refresh_sol()
                            for wt in list(self.watches.values()):
                                if wt.status == "new":
                                    if self.find_vaults(wt):
                                        await self.subscribe(wt)
                                    else:
                                        say(f"{wt.w.get('symbol')}: {wt.status}")
                                        wt.status = wt.status if wt.status.startswith("unsupported") else "unsupported: " + wt.status
                            self.write_summaries()
                            if int(now) % 60 < 2 and hashlib.sha256(open(__file__, "rb").read()).hexdigest() != code0:
                                say("feed code changed: restarting")
                                self.write_summaries(force=True)
                                sys.exit(0)
            except SystemExit:
                raise
            except Exception as e:
                say(f"websocket error ({e}), reconnecting in 5 s")
                await asyncio.sleep(5)

    def on_message(self, m):
        if "id" in m and m["id"] in self.pending:
            acct = self.pending.pop(m["id"])
            if "result" in m and isinstance(m["result"], int):
                self.sub_owner[m["result"]] = acct
                self.acct_sid[acct] = m["result"]
            elif "error" in m:
                say(f"subscribe failed for {acct}: {m['error']}")
            return
        if m.get("method") != "accountNotification":
            return
        p = m.get("params") or {}
        acct = self.sub_owner.get(p.get("subscription"))
        if not acct:
            return
        try:
            amt = float(p["result"]["value"]["data"]["parsed"]["info"]["tokenAmount"]["uiAmount"] or 0)
            slot = p["result"]["context"]["slot"]
        except Exception:
            return
        now_ms = int(time.time() * 1000)
        for wt, side in self.watchers.get(acct, []):
            if side == "base":
                wt.base = amt
            else:
                wt.quote = amt
            if wt.base and wt.quote:
                wt.ticks.append([now_ms, slot, wt.base, wt.quote])


if __name__ == "__main__":
    asyncio.run(Feed().run())
