# Real-price strategy study (Oct 27 2026)

Replays Season 2 coins on the live feed's real pool prices (data/feed on the VPS, not in git).

1. `rsync -az bewertungsdoc-vps:/opt/flip-scanner/data/feed/ feed/` and copy data/books.json, data/track.json next to it.
2. `python3 prep.py` merges price paths per pool and the scanner's buy signals (coins.json, paths.pkl).
3. Holder rebuild (on the VPS, needs FEED_RPC): `python3 drain.py drainin.json`, then `python3 featdrain.py` (drainfeat.json).
   drain.py costs about 10 Helius credits per pool-history call; 241 coins took about 1.5 hours and roughly 50K credits.
4. `python3 grid.py <wait_min> <buy_delay_s> [drain]` runs about 800 exit rules per coin; `python3 score.py grid_W0.0_L2.0.pkl [drain]`
   ranks rules x buy filters on the older 60% and reports the newer 40%.

Result: no rule green on all coins (best -4.3% a trade). Calm coins (not famous, at most 2,000 buyers in 24h) with
"stop 20%, sell all at 2x, out after 10 minutes" made +9.4% a trade on 79 coins; now forward-tested as books calm10 / calm10_safe.
