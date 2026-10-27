"""Rebuild who held each coin at the paper buy time (E).

Candidates = current top 20 token accounts + every wallet that made a big sell
(pool SOL drop >= 8% in one tick) after E. For each candidate token account the
balance at E comes from its last transaction at or before E.
Output: one JSON line per coin in drainout.jsonl (resumable).
"""
import json, os, sys, time, urllib.request

U = os.environ["FEED_RPC"]
last = [0.0]


def rpc(m, p, tries=6):
    for k in range(tries):
        gap = time.time() - last[0]
        if gap < 0.17:
            time.sleep(0.17 - gap)
        last[0] = time.time()
        req = urllib.request.Request(U, data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": m, "params": p}).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            r = json.load(urllib.request.urlopen(req, timeout=40))
            if "error" in r:
                if r["error"].get("code") in (-32429, 429, -32005):
                    time.sleep(2 + 2 * k)
                    continue
                return None
            return r["result"]
        except Exception:
            time.sleep(2 + 2 * k)
    return None


def keys_of(tx):
    ks = tx["transaction"]["message"]["accountKeys"]
    return [k["pubkey"] if isinstance(k, dict) else k for k in ks]


def deltas(tx, mint):
    m = tx["meta"]
    ks = keys_of(tx)
    pre = {b["accountIndex"]: b for b in m.get("preTokenBalances") or [] if b["mint"] == mint}
    post = {b["accountIndex"]: b for b in m.get("postTokenBalances") or [] if b["mint"] == mint}
    out = []
    for i in set(pre) | set(post):
        a = float((pre.get(i) or {}).get("uiTokenAmount", {}).get("uiAmount") or 0)
        b = float((post.get(i) or {}).get("uiTokenAmount", {}).get("uiAmount") or 0)
        owner = (post.get(i) or pre.get(i)).get("owner")
        out.append((ks[i], owner, a, b))
    return out


def bal_at(acct, E):
    sigs = rpc("getSignaturesForAddress", [acct, {"limit": 1000}])
    if sigs is None:
        return None
    before = [s for s in sigs if (s.get("blockTime") or 0) <= E]
    if not before:
        if len(sigs) < 1000:
            return 0.0
        return None
    s = before[0]["signature"]
    tx = rpc("getTransaction", [s, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 1}])
    if not tx:
        return None
    for b in tx["meta"].get("postTokenBalances") or []:
        if keys_of(tx)[b["accountIndex"]] == acct:
            return float(b["uiTokenAmount"]["uiAmount"] or 0)
    return 0.0


def one(c):
    mint, pool, E = c["token"], c["pool"], c["E"]
    cand = {}
    top = rpc("getTokenLargestAccounts", [mint]) or {}
    accts = [a["address"] for a in top.get("value", [])]
    if accts:
        info = rpc("getMultipleAccounts", [accts, {"encoding": "jsonParsed"}]) or {}
        for a, v in zip(accts, info.get("value") or []):
            try:
                cand[a] = {"owner": v["data"]["parsed"]["info"]["owner"], "src": "top", "now": float(v["data"]["parsed"]["info"]["tokenAmount"]["uiAmount"] or 0)}
            except Exception:
                pass
    sells = []
    for t in c["drops"]:
        tok = None
        for page in range(2):
            q = {"transactionDetails": "full", "limit": 100, "sortOrder": "asc", "encoding": "jsonParsed",
                 "maxSupportedTransactionVersion": 1, "filters": {"blockTime": {"gte": t - 3, "lte": t}}}
            if tok:
                q["paginationToken"] = tok
            r = rpc("getTransactionsForAddress", [pool, q])
            if not r:
                break
            for tx in r.get("data") or []:
                if tx["meta"].get("err"):
                    continue
                for acct, owner, a, b in deltas(tx, mint):
                    sold = a - b
                    if owner != pool and sold > 0.02 * (c["resTok"] or 1e18):
                        sells.append({"t": tx["blockTime"], "acct": acct, "owner": owner, "sold": sold, "pre": a})
                        e = cand.setdefault(acct, {"owner": owner, "src": "sell"})
                        e["sold"] = max(e.get("sold", 0), sold)
            tok = r.get("paginationToken")
            if not tok:
                break
    for acct, e in cand.items():
        if e["owner"] == pool:
            e["balE"] = None
            e["pool"] = True
            continue
        if e["src"] == "top" and e.get("now", 0) < 0.01 * (c["resTok"] or 0):
            e["balE"] = None
            e["skip"] = True
            continue
        e["balE"] = bal_at(acct, E)
    return {"token": mint, "E": E, "resTok": c["resTok"], "poolSol": c["poolSol"], "cand": cand, "sells": sells}


coins = json.load(open(sys.argv[1]))
done = set()
if os.path.exists("drainout.jsonl"):
    done = {json.loads(l)["token"] for l in open("drainout.jsonl")}
with open("drainout.jsonl", "a") as f:
    for i, c in enumerate(coins):
        if c["token"] in done:
            continue
        try:
            r = one(c)
        except Exception as e:
            r = {"token": c["token"], "error": str(e)[:200]}
        f.write(json.dumps(r) + "\n")
        f.flush()
        print(i, c["token"][:8], len(r.get("cand", {})), len(r.get("sells", [])), flush=True)
