# Strategy Specification: Breakout Momentum

## Metadata
| Field | Value |
|---|---|
| Strategy name | Breakout Momentum |
| Version | 1.0 |
| Type | Swing trading, long-only |
| Asset class | US equities (ETFs + large-cap stocks) |
| Timeframe | Daily close-to-close |
| Holding period | 2–12 trading days (hard cap) |
| Status | Backtested; paper trading pending |

---

## Universe

| Ticker | Name | Included |
|---|---|---|
| SPY | SPDR S&P 500 ETF | ✓ |
| QQQ | Invesco QQQ (Nasdaq 100) | ✓ |
| IWM | iShares Russell 2000 ETF | ✓ |
| NVDA | NVIDIA | ✓ |
| MSFT | Microsoft | ✓ |
| AAPL | Apple | ✓ |
| AMZN | Amazon | ✓ |
| GOOGL | Alphabet | ✓ |
| META | Meta Platforms | ✓ |
| TSLA | Tesla | ✓ |

**Liquidity filter:** 20-day average dollar volume > $500M
**Hard exclusions:** options, crypto, leveraged ETFs, IPOs < 12 months, stocks < $10, earnings within 5 calendar days

---

## Timeframe
- Primary: daily candles (close-to-close)
- Entry timing: market close (no intraday)
- Exit timing: market close or stop trigger
- Review frequency: once per day at ~4:10 PM ET
- Holding period: 2–12 days (hard cap = 12)

---

## Indicators

| Indicator | Source | Parameters |
|---|---|---|
| 20-day rolling high | daily high | lookback = 20 |
| 20-day rolling low | daily low | lookback = 20 |
| 20-day volume SMA | volume | period = 20 |
| ATR(14) | high/low/close | period = 14 |
| SPY 50-day SMA | SPY close | period = 50 |
| QQQ 20-day return | QQQ close | lookback = 20 |
| Stock 20-day return | stock close | lookback = 20 |
| VIX close | ^VIX | daily |

All indicators computed on **closed candles only** — no intraday lookahead.

---

## Entry Rules

Enter LONG when ALL conditions are met:

```
1. BREAKOUT:
   close > low_20  (price in upper half of 20-day range)

2. VOLUME:
   volume > 1.5 × vol_sma20

3. RELATIVE STRENGTH:
   stock_20d_return > QQQ_20d_return

4. MARKET REGIME:
   SPY close > SPY SMA(50)

5. NOT OVEREXTENDED:
   (close - prev_close) / prev_close ≤ 8%

6. EARNINGS SAFE:
   no earnings within next 5 calendar days

7. LIQUIDITY:
   20-day avg dollar volume > $500M
```

Skip when SPY < SPY SMA(50) (bearish backdrop — no new entries).

---

## Exit Rules

Exit LONG when ANY condition triggers (in priority order):

```
1. STOP-LOSS (hard exit):
   low < stop_price  OR  open_price < stop_price < close
   → exit full position at next open / at stop_price

2. TARGET:
   R-multiple ≥ 2.5
   → exit 50% immediately, move stop to breakeven
   → hold remaining 50% to time exit

3. TIME-BASED (hard cap):
   calendar day 12 from entry
   → exit 100% at close regardless of P&L

4. MARKET REGIME EXIT:
   SPY close < SPY SMA(50)
   → exit 100% at next close
```

---

## Position Sizing

```
max_dollar_risk  = equity × 0.005           # 0.5% hard cap
distance         = entry_price − stop_price
shares           = floor(min(
                     max_dollar_risk / distance,
                     equity × 0.05 / entry_price   # hard cap: 5% notional
                   ))
shares           = floor(shares)             # no fractional shares
```

**Max exposure per ticker:** 10% of equity
**Max open positions:** 5 simultaneous
**Max portfolio risk:** 3% of equity in open positions

---

## Risk Controls

| Limit | Value |
|---|---|
| Max risk per trade | 0.5% of equity |
| Max portfolio open risk | 3.0% of equity |
| Max single-ticker exposure | 10% of equity |
| Max drawdown cutoff | −5% from peak → stop trading |
| Max risk per day | −1.0% of equity |
| Max risk per week | −2.0% of equity |
| Max open positions | 5 |

**No-trade conditions:**
- SPY below 50-day SMA
- VIX > 28 (skip if no VIX data)
- Earnings within 5 days on target ticker
- Account drawdown > 5% from peak
- Data appears stale or missing

**Data quality checks:**
- All OHLCV fields non-null and > 0
- Volume > 0
- ATR(14) > 0
- Date of all bars confirmed as today's date or within 1 trading day

---

## Backtest Settings

| Parameter | Value |
|---|---|
| Data source | Yahoo Finance (v8 chart API) |
| Period | Jan 1, 2019 – Dec 31, 2024 |
| Starting capital | $25,000 |
| Slippage | 0.05% per side (entry + exit) |
| Commission | $0 (zero-commission broker) |
| Position sizing | Dynamic (recalc each bar using current equity) |
| Entry price | Close of signal day |
| Exit price | Close of exit day or stop_price if stopped |
| In-sample | 2019-01-02 – 2021-12-31 |
| Out-of-sample | 2022-01-01 – 2024-12-31 |

---

## Success Criteria (Paper → Live)

| Criterion | Threshold |
|---|---|
| Paper trades | ≥ 30 |
| Expectancy per trade | > $0 |
| Win rate | > 35% |
| Profit factor | > 1.3 |
| Max drawdown | < 5% of starting equity |
| Average R multiple | > 1.5 |
| Rule compliance rate | > 90% |
| Major rule violations | 0 occurrences |

---

## Known Limitations

1. **Survivorship bias:** Universe uses current constituents only. Past winners that later delisted are not included.
2. **No VIX data:** VIX filter is hardcoded to pass. VIX spikes may correlate with drawdowns.
3. **Earnings filter:** Hardcoded to skip all entries (no earnings calendar available). This is conservative.
4. **Low trade frequency:** ~3.5 qualified trades/year — not statistically robust in backtest. Paper trading phase is critical.
5. **Lookahead bias mitigated** by lagging all indicators 1 day, but verify in code review before live trading.