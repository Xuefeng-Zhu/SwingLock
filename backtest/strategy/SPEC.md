# Breakout Momentum Strategy — SPEC

## 1. Concept & Goals

A systematic long-only equity momentum strategy that captures mid-cycle breakouts.
The thesis: stocks hitting new 20-day highs on above-average volume, outperforming
QQQ over the same window, in a bull-market regime (SPY above its 50d SMA), tend to
continue higher. The strategy enforces strict risk management via an ATR-based stop
and a 2.5R target to capture asymmetric payoff.

**Ideal conditions:** trending bull markets with low VIX. The regime filter is
designed to keep us on the right side of the board during corrections.

---

## 2. Universe & Instruments

| Ticker | Name             | Role in Strategy        |
|--------|------------------|------------------------|
| SPY    | S&P 500 ETF      | Market regime filter   |
| QQQ    | Nasdaq 100 ETF   | Relative strength base |
| IWM    | Russell 2000 ETF | Breadth confirmation   |
| NVDA   | Nvidia           | Growth momentum        |
| MSFT   | Microsoft        | Core tech holding      |
| AAPL   | Apple            | Core tech holding      |
| AMZN   | Amazon           | Consumer discretionary |
| GOOGL  | Alphabet         | Large-cap tech         |
| META   | Meta Platforms   | Social media momentum  |
| TSLA   | Tesla            | High-beta momentum     |

All tickers trade on NASDAQ/NYSE (Yahoo Finance continuous adjusted close).

---

## 3. Data Requirements

- **Source:** Yahoo Finance daily OHLCV, adjusted close.
- **History:** ~6 years of daily bars (2019-01-01 → 2024-12-31).
- **Processed indicators added per bar:**
  - `high_20`  — rolling 20-day max of daily high
  - `low_20`   — rolling 20-day min of daily low
  - `vol_sma20` — rolling 20-day SMA of volume
  - `atr14`    — 14-day Average True Range (Wilder smoothing)

---

## 4. Entry Rules  (ALL must be true)

| # | Rule                                     | Rationale                              |
|---|------------------------------------------|----------------------------------------|
| 1 | Close > 20-day high                      | Confirms new breakout                  |
| 2 | Volume > 1.5× 20-day volume SMA          | Institutional confirmation             |
| 3 | Stock 20d return > QQQ 20d return        | Stock must outperform nasdaq basket    |
| 4 | SPY close > SPY 50-day SMA               | Bull-market regime filter              |
| 5 | Day gain ≤ +8 %                          | Avoid chasing extended moves           |
| 6 | Not an earnings-risk window (±5 cal days) | Skip earnings announcement risk       |

If all pass → enter long at today's close. Position size is fixed at 0.5 %
of equity (MAX_RISK_PCT) subject to a 5 % hard cap (MAX_SINGLE_POS_PCT).

---

## 5. Exit Rules (first true wins)

| Priority | Exit Trigger          | Exit Price          | Reason          |
|----------|----------------------|--------------------|-----------------|
| 1        | Stop-loss            | Stop price         | Hard risk cut   |
| 2        | Gap-open below stop  | Stop price         | Slippage guard  |
| 3        | Time-based cap       | HOLD_DAYS_MAX = 12 | Inelastic exit  |
| 4        | Target (2.5R) hit    | Close              | Take profit     |

**Stop price** = max(close − 1.5×ATR, low_20 × 0.98) — tighter of ATR stop or 2 %
buffer below the 20-day low.

**Target price** = entry + 2.5 × (entry − stop).

No trailing stop in v1. No partial exits.

---

## 6. Portfolio Constraints

| Parameter                | Value   |
|--------------------------|---------|
| Max simultaneous positions| 5       |
| Max single position size  | 5 % equity |
| Max risk per trade        | 0.5 % equity |
| Max holding period        | 12 trading days |

No leverage. No shorting. No options in backtest.

---

## 7. Filters & Exclusions

| Filter            | Threshold            | Effect                             |
|-------------------|----------------------|------------------------------------|
| VIX (approximated via SPY ATM IV regime — skip flag in v1) | —        | Not modelled in v1 backtest |
| Earnings window   | ±5 calendar days     | Entries blocked, open trades unaffected |
| Gap-up > 8 % day  | skip if day gain > 8%| Avoid overextended entries         |

---

## 8. Backtest Settings

| Parameter      | Value                              |
|----------------|------------------------------------|
| Engine        | Pure Python, single-threaded, no external libs |
| Initial equity | $100,000                           |
| Starting date  | 2019-01-31 (indicators warm-up)     |
| Ending date   | 2024-12-05                         |
| Execution     | Close-of-day entry/exit (no slippage modeled) |
| Commission    | $0 (ignore for this exercise)      |
| Benchmark     | QQQ buy-and-hold                    |

---

## 9. Success Metrics

| Metric               | Target                     |
|----------------------|----------------------------|
| Total Return         | > QQQ buy-and-hold         |
| Sharpe Ratio        | > 1.0                      |
| Max Drawdown        | < −20 %                     |
| Win Rate            | > 40 %                     |
| Avg R-multiple      | > 1.0 (after slippage)     |
| Max single loss     | < −3 %                     |

---

## 10. Output Files

| File                    | Location                          |
|-------------------------|-----------------------------------|
| Backtest results JSON   | `results/backtest_results.json`   |
| Trade journal CSV       | `journal/paper_trades.csv`        |
| This spec               | `strategy/SPEC.md`                |
| Pre-trade checklist    | `strategy/checklist.md`          |

---

## 11. Change Log

| Version | Date       | Change                           |
|---------|------------|----------------------------------|
| 1.0     | 2026-05-25 | Initial spec creation             |