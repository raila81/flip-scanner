# Market study: paper trades vs BTC and SOL

Run 2026-10-13 07:02 UTC. Trades from Oct 06 01:33 to Oct 13 06:20 UTC. 1788 closed playbook trades, 953 closed main-portfolio buy-now trades. Costs 3%. 'Trimmed' = average after dropping the best 2% of trades. 'Solid' = trimmed average positive in both the older and newer half, with 30+ trades.

## 1. Day by day

| Day (UTC) | SOL day | BTC day | Playbook trades | Playbook P&L | Tight trail P&L | Big pool trail P&L | Portfolio P&L |
|---|---|---|---|---|---|---|---|
| 2026-10-06 | -0.2% | -0.3% | 89 | $-446 | $+0 | $+0 | $-2582 |
| 2026-10-07 | -3.5% | -2.7% | 184 | $-1958 | $+0 | $+0 | $-1841 |
| 2026-10-08 | -5.7% | -1.7% | 173 | $-433 | $+0 | $+0 | $-1095 |
| 2026-10-09 | -0.4% | +1.0% | 265 | $-1383 | $-152 | $-161 | $-1091 |
| 2026-10-10 | +0.8% | +0.5% | 195 | $-1634 | $-150 | $-166 | $-1390 |
| 2026-10-11 | +1.0% | +0.9% | 312 | $-921 | $+118 | $+118 | $-1021 |
| 2026-10-12 | -6.0% | -2.6% | 425 | $-215 | $+435 | $+370 | $-954 |
| 2026-10-13 | +3.8% | +2.7% | 145 | $-573 | $+23 | $+19 | $-8 |

## 2. Does P&L move with the market?

Correlation runs from -1 to +1. Near 0 means no link. Spearman ignores the size of outliers.

| What is compared | Trades or blocks | Pearson | Spearman |
|---|---|---|---|
| Playbook trade result vs SOL move during the trade | 1788 | +0.0 | +0.0 |
| Playbook trade result vs BTC move during the trade | 1788 | +0.0 | +0.0 |
| Playbook trade result vs SOL change in the 6h before entry | 1788 | -0.0 | -0.1 |
| Playbook trade result vs BTC change in the 24h before entry | 1788 | +0.0 | +0.1 |
| Portfolio trade result vs SOL move during the trade | 953 | -0.0 | -0.0 |
| Playbook P&L per 6-hour block vs SOL change in that block | 28 blocks | -0.1 | -0.1 |
| Playbook P&L per 6-hour block vs BTC change in that block | 28 blocks | -0.1 | +0.1 |

## 3. Would a market switch have helped?

ON = trades opened while the condition held. OFF = the rest. A switch only helps if ON is clearly better than OFF, and ON is positive in both halves.


### All playbooks pooled (1788 trades)

All trades: trimmed -12.2%, win 26%, older half -16.3%, newer half -8.2%.

| Condition at entry | Trades ON | Trimmed ON | Win ON | Older ON | Newer ON | Trades OFF | Trimmed OFF | Win OFF | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| SOL up in the last 1h | 827 | -13.3% | 24% | -20.0% | -6.0% | 961 | -11.3% | 28% | no difference |
| SOL up in the last 6h | 766 | -12.2% | 25% | -14.9% | -9.8% | 1022 | -12.1% | 27% | no difference |
| SOL up in the last 24h | 721 | -12.6% | 23% | -17.7% | -7.3% | 1067 | -11.8% | 28% | no difference |
| SOL above its 24h average | 570 | -13.8% | 23% | -17.7% | -9.8% | 1218 | -11.4% | 27% | OFF better |
| BTC up in the last 6h | 830 | -12.5% | 25% | -16.8% | -7.7% | 958 | -12.0% | 27% | no difference |
| BTC up in the last 24h | 984 | -13.1% | 23% | -19.0% | -6.9% | 804 | -11.2% | 29% | no difference |
| BTC above its 24h average | 908 | -12.7% | 24% | -18.3% | -7.0% | 880 | -11.7% | 28% | no difference |
| SOL up 1h AND above 24h average | 316 | -14.2% | 22% | -19.5% | -8.3% | 1472 | -11.7% | 27% | OFF better |

### Main portfolio, buy now (953 trades)

All trades: trimmed -20.5%, win 18%, older half -22.0%, newer half -19.2%.

| Condition at entry | Trades ON | Trimmed ON | Win ON | Older ON | Newer ON | Trades OFF | Trimmed OFF | Win OFF | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| SOL up in the last 1h | 398 | -20.4% | 17% | -23.7% | -17.1% | 555 | -20.5% | 19% | no difference |
| SOL up in the last 6h | 377 | -20.9% | 18% | -22.1% | -19.7% | 576 | -20.4% | 19% | no difference |
| SOL up in the last 24h | 320 | -21.9% | 16% | -22.0% | -21.8% | 633 | -19.7% | 19% | OFF better |
| SOL above its 24h average | 334 | -22.5% | 16% | -22.1% | -21.7% | 619 | -19.4% | 20% | OFF better |
| BTC up in the last 6h | 397 | -20.1% | 18% | -20.4% | -19.7% | 556 | -20.7% | 19% | no difference |
| BTC up in the last 24h | 416 | -20.7% | 17% | -21.0% | -20.3% | 537 | -20.3% | 19% | no difference |
| BTC above its 24h average | 406 | -21.2% | 17% | -22.5% | -19.8% | 547 | -19.9% | 19% | no difference |
| SOL up 1h AND above 24h average | 162 | -24.8% | 14% | -31.7% | -20.1% | 791 | -19.6% | 19% | OFF better |

### v2 Tight trail (199 trades)

All trades: trimmed -2.1%, win 30%, older half -6.9%, newer half +2.8%.

| Condition at entry | Trades ON | Trimmed ON | Win ON | Older ON | Newer ON | Trades OFF | Trimmed OFF | Win OFF | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| SOL up in the last 1h | 88 | -3.0% | 27% | -7.7% | +1.7% | 111 | -1.4% | 32% | no difference |
| SOL up in the last 6h | 74 | -2.4% | 24% | -14.0% | +4.1% | 125 | -0.5% | 33% | no difference |
| SOL up in the last 24h | 103 | -4.3% | 24% | -9.0% | +1.0% | 96 | +0.3% | 35% | OFF better |
| SOL above its 24h average | 69 | -3.6% | 25% | -11.5% | +1.5% | 130 | -1.3% | 32% | OFF better |
| BTC up in the last 6h | 98 | -0.4% | 30% | -10.8% | +11.7% | 101 | -3.1% | 30% | ON better, not solid |
| BTC up in the last 24h | 143 | -4.0% | 26% | -9.4% | +4.0% | 56 | +2.8% | 39% | OFF better |
| BTC above its 24h average | 125 | -3.0% | 26% | -8.7% | +3.2% | 74 | +1.5% | 35% | OFF better |
| SOL up 1h AND above 24h average | 38 | -9.5% | 18% | -20.9% | +1.0% | 161 | -0.4% | 32% | OFF better |

### v2 Trail, big pool (172 trades)

All trades: trimmed -2.6%, win 30%, older half -9.0%, newer half +2.1%.

| Condition at entry | Trades ON | Trimmed ON | Win ON | Older ON | Newer ON | Trades OFF | Trimmed OFF | Win OFF | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| SOL up in the last 1h | 73 | -3.1% | 23% | -11.8% | +0.4% | 99 | -2.1% | 35% | no difference |
| SOL up in the last 6h | 63 | -4.9% | 22% | -17.3% | +1.3% | 109 | -1.1% | 35% | OFF better |
| SOL up in the last 24h | 89 | -6.3% | 25% | -11.6% | -0.2% | 83 | -0.5% | 36% | OFF better |
| SOL above its 24h average | 57 | -4.5% | 26% | -14.3% | +1.6% | 115 | -1.7% | 32% | OFF better |
| BTC up in the last 6h | 83 | -2.7% | 27% | -14.6% | +10.9% | 89 | -3.6% | 34% | no difference |
| BTC up in the last 24h | 121 | -4.4% | 26% | -11.9% | +3.5% | 51 | +1.7% | 41% | OFF better |
| BTC above its 24h average | 104 | -4.5% | 26% | -11.2% | +2.9% | 68 | +0.2% | 37% | OFF better |
| SOL up 1h AND above 24h average | 32 | -11.5% | 19% | -22.6% | -1.8% | 140 | -1.8% | 33% | OFF better |

### v2 2x with break-even (190 trades)

All trades: trimmed -4.5%, win 20%, older half -4.5%, newer half -4.5%.

| Condition at entry | Trades ON | Trimmed ON | Win ON | Older ON | Newer ON | Trades OFF | Trimmed OFF | Win OFF | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| SOL up in the last 1h | 82 | -9.1% | 16% | -14.3% | -3.8% | 108 | -1.0% | 23% | OFF better |
| SOL up in the last 6h | 64 | -5.2% | 19% | -15.7% | +2.1% | 126 | -4.1% | 21% | no difference |
| SOL up in the last 24h | 89 | -4.2% | 20% | -6.0% | -2.4% | 101 | -4.8% | 20% | no difference |
| SOL above its 24h average | 59 | -3.4% | 20% | -6.1% | -4.2% | 131 | -5.0% | 20% | no difference |
| BTC up in the last 6h | 85 | -2.8% | 21% | -8.8% | +3.0% | 105 | -5.9% | 19% | ON better, not solid |
| BTC up in the last 24h | 139 | -3.6% | 21% | -12.2% | +6.2% | 51 | -6.9% | 18% | ON better, not solid |
| BTC above its 24h average | 113 | -3.7% | 20% | -13.7% | +6.2% | 77 | -5.7% | 19% | ON better, not solid |
| SOL up 1h AND above 24h average | 37 | -10.1% | 16% | -21.5% | -5.1% | 153 | -3.2% | 21% | OFF better |

### Quick flip (285 trades)

All trades: trimmed -11.3%, win 32%, older half -7.2%, newer half -15.3%.

| Condition at entry | Trades ON | Trimmed ON | Win ON | Older ON | Newer ON | Trades OFF | Trimmed OFF | Win OFF | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| SOL up in the last 1h | 122 | -11.2% | 30% | -9.3% | -13.2% | 163 | -11.0% | 33% | no difference |
| SOL up in the last 6h | 124 | -12.9% | 29% | -10.9% | -14.8% | 161 | -9.7% | 34% | OFF better |
| SOL up in the last 24h | 88 | -15.7% | 26% | -13.7% | -17.8% | 197 | -9.3% | 35% | OFF better |
| SOL above its 24h average | 71 | -14.9% | 27% | -10.5% | -20.8% | 214 | -9.8% | 34% | OFF better |
| BTC up in the last 6h | 106 | -13.0% | 29% | -8.4% | -17.6% | 179 | -10.3% | 34% | OFF better |
| BTC up in the last 24h | 87 | -16.5% | 25% | -15.5% | -17.4% | 198 | -9.0% | 35% | OFF better |
| BTC above its 24h average | 98 | -15.2% | 27% | -17.9% | -12.5% | 187 | -9.2% | 35% | OFF better |
| SOL up 1h AND above 24h average | 35 | -17.6% | 26% | -23.6% | -15.7% | 250 | -10.4% | 33% | OFF better |

### Card plan as is (220 trades)

All trades: trimmed -17.0%, win 20%, older half -15.9%, newer half -18.1%.

| Condition at entry | Trades ON | Trimmed ON | Win ON | Older ON | Newer ON | Trades OFF | Trimmed OFF | Win OFF | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| SOL up in the last 1h | 103 | -15.1% | 19% | -21.1% | -9.2% | 117 | -18.7% | 20% | ON better, not solid |
| SOL up in the last 6h | 115 | -15.2% | 20% | -12.2% | -18.3% | 105 | -18.9% | 19% | ON better, not solid |
| SOL up in the last 24h | 66 | -15.8% | 18% | -19.2% | -17.6% | 154 | -17.5% | 20% | no difference |
| SOL above its 24h average | 76 | -23.5% | 14% | -26.3% | -20.7% | 144 | -14.7% | 22% | OFF better |
| BTC up in the last 6h | 106 | -19.1% | 18% | -12.9% | -25.3% | 114 | -14.9% | 21% | OFF better |
| BTC up in the last 24h | 93 | -22.6% | 15% | -28.9% | -16.2% | 127 | -14.2% | 23% | OFF better |
| BTC above its 24h average | 105 | -17.9% | 18% | -20.3% | -15.3% | 115 | -16.2% | 21% | no difference |
| SOL up 1h AND above 24h average | 39 | -22.4% | 15% | -43.1% | -12.5% | 181 | -16.6% | 20% | OFF better |

## 4. Verdict

Conditions that pass the solid test (ON positive in both halves, 30+ trades, beats OFF by over 2 points per trade):

- Big coins (unproven): BTC up in the last 6h. 37 trades ON, trimmed +2.3% vs -9.0% OFF.
- Big coins (unproven): BTC up in the last 24h. 33 trades ON, trimmed +8.1% vs -13.7% OFF.
