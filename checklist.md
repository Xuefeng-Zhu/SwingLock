# Pre-Trade Checklist
## Trend-Following Breakout Strategy | Daily Review — 4:05 PM ET

---

### Account Mode
- [ ] Mode confirmed: _____________ (paper / research)

---

### Data Freshness
- [ ] SPY data date verified: _____________ (must be today or prior trading day)
- [ ] Target ticker data date verified: _____________
- [ ] Volume > 0 on all feeds
- [ ] ATR(14) > 0 for target ticker
- [ ] All OHLCV fields non-null
- [ ] No null values in SMA200, High20, VolSMA20 columns

---

### Market Regime
- [ ] SPY close > SPY SMA(200)? Today: _____________ / SMA: _____________
- [ ] If SPY below SMA(200): **NO NEW ENTRIES** — skip this ticker
- [ ] VIX < 30 (or no VIX data — skip if unavailable)
- [ ] Market not in extreme gap open (> 3%)

---

### Relative Strength Check
- [ ] Stock 20d return: _____________%
- [ ] SPY 20d return: _____________%
- [ ] Stock outperforming SPY? (must be true to enter)

---

### Ticker Entry Check
- [ ] Today's close > prior bar's High20? Close: ________ / High20: ________
- [ ] Prior bar volume > 1.5 × prior bar's VolSMA20? Vol: ________ / SMA20: ________
- [ ] Day gain ≤ 8%? Gain: ________
- [ ] No existing position in this ticker
- [ ] < 3 open positions in portfolio
- [ ] Stock price > $20

---

### Earnings Filter
- [ ] No earnings for this ticker within next 5 calendar days
- [ ] Next earnings date (if known): _____________

---

### Portfolio Risk Check
- [ ] This entry's planned risk: $________ (0.5% × equity = $________)
- [ ] Total portfolio open risk: $________ / $________ (2.5% limit)
- [ ] Notional of this position: $________ (≤ 5% of equity)
- [ ] Single-ticker exposure: $________ (≤ 5% of equity)

---

### Position Sizing
- [ ] Entry price: ________
- [ ] ATR14: ________
- [ ] ATR stop: entry − 2 × ATR14 = ________
- [ ] 2% stop: entry × 0.98 = ________
- [ ] Stop price (tightest): ________
- [ ] Stop distance: entry − stop = ________
- [ ] Shares = floor(min($125 / $________, $1,250 / $________)) = _______
- [ ] Hard cap check (5% notional): shares × $________ ≤ $1,250? _______
- [ ] Max dollar risk used = $________

---

### Order Entry
- [ ] Order type: LIMIT
- [ ] Entry price: ________ (today's close)
- [ ] Stop price: ________
- [ ] Target price: ________ (entry + 2.5 × distance)
- [ ] Quantity: ________ shares
- [ ] Time in force: DAY
- [ ] Estimated slippage (0.05% × 2 sides): $________

---

### Confirmation
- [ ] **Paper trading only** — this is not a live order
- [ ] Max planned loss in dollars: $________
- [ ] Max loss as % of equity: ________%
- [ ] I will record this trade in journal/paper_trades.csv within 24 hours

**APPROVE ORDER:** ________ (type "yes" to confirm)

---

### Post-Trade (within 24 hours)
- [ ] Trade recorded in journal/paper_trades.csv
- [ ] Stop-loss order confirmed with broker
- [ ] Entry price matched planned entry: _______
- [ ] Rule followed (Y/N): _______
- [ ] Mistake noted (if any): ________
- [ ] Screenshot or notes saved