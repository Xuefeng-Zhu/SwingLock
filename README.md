# SwingResearch

Systematic US stock/ETF swing trading strategy research platform.

**Stack:** vectorbt + backtesting.py + QuantStats + (future) alpaca-py

**Goal:** Research strategies, validate on paper, deploy with discipline. No live trading until 30+ paper trades pass criteria.

---

## Quick Start

```bash
# 1. Clone + enter repo
cd SwingResearch

# 2. Install dependencies
pip install -r requirements.txt

# 3. Fetch data
python scripts/fetch_data.py --tickers SPY QQQ IWM --start 2019-01-01 --end 2024-12-31

# 4. Run backtests
python scripts/backtest_vbt.py        # vectorbt engine (fast)
python scripts/backtest_simple.py     # backtesting.py engine (event-driven)

# 5. Generate QuantStats report
python scripts/report_quantstats.py

# 6. View results
open reports/performance.html
```

---

## Architecture

### Why three backtest engines?

| Engine | Use case | Speed |
|---|---|---|
| **vectorbt** | Signal prototyping, parameter sweeps, portfolio opt | ~1ms |
| **backtesting.py** | Event-driven validation, teaching/debugging | ~1s |
| **Live (alpaca-py)** | Paper trading + eventual live execution | real |

**Rule:** If vectorbt and backtesting.py disagree on a strategy, investigate before proceeding.

### Key design decisions

- **No Jupyter required** — all scripts run standalone from CLI
- **No live broker connections** — `ALPACA_PAPER=true` enforced; live credentials require explicit opt-in
- **No lookahead bias** — all indicators lagged 1 day; signal at close, execute next day open
- **No leverage, no shorts, no options** — long-only, 1x exposure max
- **No aggressive optimization** — parameter changes require out-of-sample re-validation

---

## Project Structure

```
SwingResearch/
├── README.md
├── requirements.txt
├── .env.example                  # API key template (no real keys committed)
├── data/
│   ├── raw/                      # raw OHLCV from Yahoo Finance
│   └── processed/                # with indicators added
├── scripts/
│   ├── fetch_data.py             # Yahoo Finance data fetcher
│   ├── compute_indicators.py     # rolling SMA, ATR, etc.
│   ├── backtest_vbt.py           # vectorbt portfolio engine
│   ├── backtest_simple.py        # backtesting.py engine
│   ├── report_quantstats.py      # QuantStats HTML report
│   └── run_all.py                # run full pipeline
├── strategies/
│   ├── __init__.py
│   ├── sma200_trendfilter.py     # 200d SMA trend filter
│   ├── breakout_20d.py            # 20d breakout entry
│   └── atr_stop.py               # ATR-based stop loss
├── notebooks/
│   └── explore_signals.ipynb     # interactive signal inspection
├── reports/                      # generated QuantStats HTML reports
│   └── performance.html
├── journal/
│   └── paper_trades.csv          # trade journal (fill in manually)
└── tests/
    ├── test_indicators.py
    └── test_strategies.py
```

---

## Baseline Strategy (SMA200 + 20d Breakout)

| Parameter | Value |
|---|---|
| Universe | SPY, QQQ, IWM |
| Timeframe | Daily close |
| Trend filter | SPY close > SMA(200) |
| Entry | Close > 20d rolling high (breakout) |
| Exit | Stop below entry − 2× ATR14, OR 20-day hard cap |
| Position sizing | equity × 0.005 / ATR distance |
| Max positions | 3 simultaneous |
| Max risk/trade | 0.5% of equity |
| Max notional | 5% of equity per position |

---

## Paper Trading Criteria (before live deployment)

- [ ] ≥ 30 paper trades completed
- [ ] Expectancy per trade > $0
- [ ] Win rate > 40%
- [ ] Profit factor > 1.2
- [ ] Max drawdown < 10% of starting equity
- [ ] No major rule violations (logging required for every trade)
- [ ] Both backtest engines agree on direction of results

---

## Data

**Source:** Yahoo Finance (no API key required)
**Ticker list:** SPY, QQQ, IWM (expandable)
**Date range:** 2019-01-01 to 2024-12-31 (6 years, includes 2 bear markets)

**Indicators computed:**

| Indicator | Description |
|---|---|
| SMA200 | 200-day simple moving average of close |
| SMA50 | 50-day simple moving average of close |
| High20 | 20-day rolling max of high |
| Low20 | 20-day rolling min of low |
| ATR14 | 14-day average true range |
| VolSMA20 | 20-day simple moving average of volume |

---

## Risk Parameters

| Limit | Value |
|---|---|
| Max risk per trade | 0.5% equity |
| Max portfolio risk | 3% equity (open positions) |
| Max single position | 5% equity |
| Max simultaneous positions | 3 |
| Max drawdown cutoff | −10% from peak → stop trading |
| Max loss per day | −2% equity |
| Max loss per week | −4% equity |

---

## Backtest Configuration

| Parameter | Value |
|---|---|
| Starting capital | $25,000 (PDT threshold) |
| Slippage | 0.05% per side (bid/ask) |
| Commission | $0 (zero-commission broker) |
| Entry price | Next-day open |
| Exit price | Close of exit day |
| In-sample | 2019-01-02 – 2021-12-31 |
| Out-of-sample | 2022-01-01 – 2024-12-31 |

---

## Development Workflow

```
1. Design strategy in strategies/
2. Compute indicators with compute_indicators.py
3. Quick test with backtest_vbt.py (seconds)
4. Validate with backtest_simple.py (slower, event-driven)
5. Generate QuantStats report
6. Review trade log, check for rule violations
7. Paper trade in journal/paper_trades.csv
8. Repeat until criteria met
9. Connect alpaca-py paper trading (future)
```