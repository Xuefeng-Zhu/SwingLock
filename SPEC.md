# Strategy Specification: SMA200 Trend Filter + 20-Day Breakout

## Metadata

| Field | Value |
|---|---|
| Strategy name | Trend-Following Breakout |
| Version | 2.0 |
| Type | Swing trading, long-only |
| Asset class | US ETFs |
| Timeframe | Daily close-to-close |
| Holding period | 2–20 trading days |
| Status | Research phase |

---

## Architecture & Tradeoffs (Before Coding)

### Why three backtest engines?

| Engine | Speed | Transparency | Best for |
|---|---|---|---|
| **vectorbt** | ~1ms/strategy | Low (vectorized) | Prototyping, parameter sweeps |
| **backtesting.py** | ~1s/strategy | High (event-driven) | Teaching, signal validation, debugging |
| **Lean (QuantConnect)** | ~100ms | High | Serious institutional backtesting |

**Our approach:** Keep vectorbt for speed, backtesting.py for transparency. If they disagree on a signal direction, stop and investigate before proceeding.

### Why not LEAN/QuantConnect?

- LEAN is designed for hedge funds and requires cloud deployment or local compiler setup
- Overkill for a retail trader doing strategy research on a laptop
- QuantConnect has good data but adds platform lock-in
- vectorbt + backtesting.py gives 95% of capability at 5% of complexity

### Why not backtesting.py only?

- It is single-threaded and slow for parameter optimization
- Good for validation, not for discovery

### Key design decisions

1. **No lookahead bias** — all signals lag 1 bar. Price at close can't fire entry for same bar.
2. **No live broker in research** — `alpaca-py` paper mode requires explicit opt-in with env vars set
3. **No leverage, no shorts, no options** — 1x exposure, long-only
4. **No aggressive optimization** — parameters fixed for 6-month out-of-sample validation before any change

---

## Universe

| Ticker | Name | Included |
|---|---|---|
| SPY | SPDR S&P 500 ETF | ✓ |
| QQQ | Invesco QQQ (Nasdaq 100) | ✓ |
| IWM | iShares Russell 2000 ETF | ✓ |

**Liquidity filter:** 20-day average dollar volume > $1B
**Hard exclusions:** leveraged ETFs, IPOs < 12 months, stocks < $20

---

## Timeframe

- **Primary:** daily candles (close-to-close)
- **Entry timing:** market close (no intraday)
- **Exit timing:** market close or stop trigger
- **Review frequency:** once per day at ~4:05 PM ET
- **Holding period:** 2–20 days (hard cap)

---

## Indicators

| Indicator | Source | Parameters |
|---|---|---|
| SMA(200) | daily close | lookback = 200 |
| SMA(50) | daily close | lookback = 50 |
| High20 | daily high | rolling max, period = 20 |
| Low20 | daily low | rolling min, period = 20 |
| ATR(14) | high/low/close | period = 14 |
| VolSMA20 | volume | period = 20 |
| RS vs SPY | 20-day return diff | stock_return - SPY_return |

All indicators computed on **closed candles only** — no intraday lookahead.

---

## Entry Rules

Enter LONG when **ALL** conditions are met:

```
1. TREND FILTER:
   SPY close > SPY SMA(200)          [market in long-term uptrend]

2. BREAKOUT:
   stock close > stock high20         [1-bar lagged to avoid lookahead]
   → uses high20 from prior bar, not current bar

3. VOLUME CONFIRMATION:
   volume > 1.5 × vol_sma20           [1-bar lagged]

4. NOT OVEREXTENDED:
   daily gain ≤ 8%

5. RELATIVE STRENGTH:
   stock_20d_return > SPY_20d_return  [stock outperforming market]

6. EARNINGS SAFE:
   no earnings within next 5 calendar days
```

Skip ALL entries when SPY < SPY SMA(200) (bearish backdrop — no new longs).

---

## Exit Rules

Exit LONG when **ANY** condition triggers:

```
1. STOP-LOSS (hard exit, priority 1):
   low ≤ stop_price  OR  open ≤ stop_price
   → exit full position at next open or at stop_price

2. TARGET (partial exit, priority 2):
   R-multiple ≥ 2.5
   → exit 50% immediately
   → move stop to breakeven (entry price)
   → hold remaining 50% to time exit

3. TIME-BASED (hard cap):
   20 trading days from entry
   → exit 100% at close regardless of P&L

4. REGIME EXIT:
   SPY close < SPY SMA(50)            [early warning — trending down]
   → exit 100% at next close
```

---

## Stop-Loss Computation

```
atr_stop     = entry_price − 2.0 × ATR14
pct_stop     = entry_price × 0.98         [max 2% adverse move]
stop_price   = max(atr_stop, pct_stop)   [tightest stop wins]
```

---

## Position Sizing

```
max_dollar_risk  = equity × 0.005         # 0.5% hard cap per trade
distance         = entry_price − stop_price
shares           = floor(min(
                     max_dollar_risk / distance,
                     equity × 0.05 / entry_price   # hard cap: 5% notional
                   ))
```

**Max exposure per ticker:** 5% of equity
**Max open positions:** 3 simultaneous
**Max portfolio risk:** 2.5% of equity in open positions

---

## Risk Controls

| Limit | Value |
|---|---|
| Max risk per trade | 0.5% of equity |
| Max portfolio open risk | 2.5% of equity |
| Max single-ticker exposure | 5% of equity |
| Max open positions | 3 |
| Max drawdown cutoff | −5% from peak → stop trading |
| Max loss per day | −1.5% of equity |
| Max loss per week | −3.0% of equity |

**No-trade conditions:**
- SPY below 200-day SMA
- VIX > 30
- Earnings within 5 days on target ticker
- Account drawdown > 5% from peak
- Data appears stale or price = 0

**Data quality checks:**
- All OHLCV fields non-null and > 0
- Volume > 0
- ATR(14) > 0
- Date of all bars within 1 trading day of expected date

---

## Backtest Configuration

| Parameter | Value |
|---|---|
| Data source | Yahoo Finance (no API key) |
| Period | Jan 1, 2019 – Dec 31, 2024 |
| Starting capital | $25,000 |
| Slippage | 0.05% per side |
| Commission | $0 (zero-commission broker) |
| Position sizing | Dynamic (recalc each bar) |
| Entry price | Close of signal day |
| Exit price | Close of exit day or stop trigger |
| In-sample | 2019-01-02 – 2021-12-31 |
| Out-of-sample | 2022-01-02 – 2024-12-31 |

---

## Success Criteria (Paper → Live)

| Criterion | Threshold |
|---|---|
| Paper trades | ≥ 30 |
| Expectancy per trade | > $0 |
| Win rate | > 40% |
| Profit factor | > 1.2 |
| Max drawdown | < 10% of starting equity |
| Average R multiple | > 1.5 |
| Rule compliance rate | > 90% |
| Major rule violations | 0 occurrences |

---

## Known Limitations

1. **Survivorship bias:** Universe uses current constituents only. Past winners that later delisted are not included.
2. **VIX filter not implemented:** Hardcoded to pass. VIX spikes may correlate with drawdowns.
3. **Earnings filter not implemented:** Hardcoded to skip all entries. In production, need a calendar source.
4. **Low trade frequency:** 3 ETFs × ~2-4 qualified breakouts/year. Not statistically robust in 3-year backtest. Paper trading phase is critical.
5. **Lookahead bias mitigated** by lagging high20 and vol_sma20 1 bar, but verify in code review before live trading.