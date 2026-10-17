# Flip Scanner

A one-page safety scanner for new coins on pump.fun (Solana) and Robinhood Chain.

Runs fully in the browser with free public data: GeckoTerminal, DexScreener, RugCheck and GoPlus. No keys, no server.

Safety scan only. A pass means no traps were found, not that the price will go up. Not financial advice.

## Yield Scanner (yields.html)

Passive-income pools sorted into Low / Mid / High risk, with alerts (hacks, yield spikes, shrinking pools) and a $5K calculator.
`yields/yields.py` runs in the same GitHub Actions chain and writes `data/yields.json` (+ a small `data/yields_history.json` for the 7-day alerts).
Data: DefiLlama (pools, protocols, hack list, fees), Hyperliquid, Hylo, CoinGecko. The tier rules live in the script; the page only shows them.
