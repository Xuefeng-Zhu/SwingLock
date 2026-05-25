# Alpaca Paper Trading Setup — SwingLock

## Overview

This guide explains how to connect SwingLock to Alpaca's paper trading platform so you can validate the strategy with real broker mechanics (orders, fills, stops) before going live.

**Safety first:** Paper trading is always `ALPACA_PAPER=true`. Real orders are never submitted unless you explicitly change this flag.

---

## Prerequisites

- Alpaca account (free at [app.alpaca.markets](https://app.alpaca.markets))
- Python ≥ 3.10
- `pip install alpaca-py python-dotenv yfinance pandas numpy`

---

## Step 1 — Get Alpaca API Keys

1. Go to [app.alpaca.markets](https://app.alpaca.markets) → **Paper Trading** tab
2. Click **Generate New API Key**
3. Copy the **API Key** and **Secret Key**
4. Keys look like: `PKXXXXXXXXXXXXXXXX` and `XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX`

> **Important:** These are paper trading keys only. They cannot execute real orders.

---

## Step 2 — Configure `.env`

Copy the template and fill in your keys:

```bash
cp .env.example .env
```

Edit `.env`:

```ini
ALPACA_API_KEY=PKXXXXXXXXXXXXXXXX
ALPACA_SECRET_KEY=XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
ALPACA_PAPER=true           # ← MUST be true for paper trading
```

> **Never set `ALPACA_PAPER=false`** unless you have explicitly reviewed the consequences and have a funded live account.

The `.env.example` already has `ALPACA_PAPER=true` as the default safety flag.

---

## Step 3 — Verify Connectivity

```bash
cd SwingLock
python -c "
from alpaca.trading.client import TradingClient
import os, dotenv
dotenv.load_dotenv('.env')
client = TradingClient(os.getenv('ALPACA_API_KEY'), os.getenv('ALPACA_SECRET_KEY'), paper=True)
account = client.get_account()
print(f'Account equity: \${account.equity}')
print(f'Paper trading:  {client.get_account().account_blocked == False}')
"
```

You should see your paper account equity (starts at $25,000 by default on new Alpaca accounts).

---

## Step 4 — Run a Dry-Run Scan

Before placing any orders, verify the signal logic without trading:

```bash
python scripts/paper_trade_alpaca.py --dry-run --date 2024-06-01
```

This will:
- Fetch the latest data for SPY, QQQ, IWM, XLK, XLF
- Compute indicators (15-day breakout high, ATR14, 20-day volume SMA, 200-day SMA)
- Print any signals without placing orders

Sample output:
```
SIGNAL: QQQ  entry=$445.20  stop=$438.50  shares=28  risk=$187.60 (0.75%)
```

If you see `No signals.`, that means the market conditions didn't trigger any entries that day.

---

## Step 5 — Run the Daily Paper Trading Scan

Run **once per trading day, at ~4:05 PM ET** (after market close, before 4 PM cut-off):

```bash
python scripts/paper_trade_alpaca.py
```

### What it does each run:

| Step | Action |
|------|--------|
| 1 | Fetch latest OHLCV for SPY, QQQ, IWM, XLK, XLF via Yahoo Finance |
| 2 | Check trend filter: SPY close > SPY SMA(200) (lagged 1 bar) |
| 3 | Scan each ticker for breakout: close > 15d high (lagged 1 bar) + volume > 1.5× vol_sma20 |
| 4 | Calculate position size: risk $0.5% equity per trade, stop = entry − 2× ATR14 |
| 5 | Submit buy order + linked stop-loss for each signal |
| 6 | Check existing positions for time-based exit (hold ≥ 10 days) |
| 7 | Log all trades to `journal/paper_trades.csv` |

---

## Step 6 — Automate with `cron` (optional)

Add to your crontab (`crontab -e`):

```cron
# Run paper trading scan Mon–Fri at 4:10 PM ET
10 16 * * 1-5  cd /path/to/SwingLock && /usr/bin/python3 scripts/paper_trade_alpaca.py >> logs/paper_trade.log 2>&1
```

---

## Interpreting the Trade Journal

The journal lives at `journal/paper_trades.csv`:

| Column | Description |
|--------|-------------|
| `date` | Trade date |
| `ticker` | ETF symbol |
| `action` | `entry` or `exit` |
| `entry_price` | Fill price on entry |
| `exit_price` | Fill price on exit |
| `shares` | Number of shares |
| `stop_price` | Stop-loss price at entry |
| `pnl` | Realized P&L in dollars |
| `reason` | `breakout` (entry), `stop` or `time N` (exit) |
| `rule_violation` | `Y` if a strategy rule was broken |
| `atr14` | ATR14 at entry (for post-trade analysis) |
| `dollar_risk` | Risk $ at entry (shares × distance to stop) |
| `pct_risk` | Risk as % of equity |
| `order_id` | Alpaca order ID |
| `notes` | Any observations |

---

## Strategy Parameters Summary

| Parameter | Value | Source |
|-----------|-------|--------|
| Breakout lookback | 15 days | Best OOS params |
| Volume threshold | 1.5× vol_sma20 | Best OOS params |
| ATR stop multiplier | 2.0× ATR14 | Best OOS params |
| Hold days | 10 | Best OOS params |
| Trend filter | SPY close > SMA(200) | SPEC.md |
| Max open positions | 3 | SPEC.md |
| Max risk / trade | 0.5% equity | SPEC.md |
| Max notional / position | 5% equity | SPEC.md |

---

## Before Going Live — Checklist

Paper trading is a prerequisite, not a guarantee. Before switching to live:

- [ ] ≥ 30 paper trades completed
- [ ] Expectancy per trade > $0
- [ ] Win rate > 40%
- [ ] Profit factor > 1.2
- [ ] Max drawdown < 10% of starting equity
- [ ] No major rule violations (all trades logged, `rule_violation=N`)
- [ ] Both backtest engines (vectorbt + backtesting.py) agree on direction
- [ ] You've reviewed the journal and understand every trade
- [ ] You have read the Alpaca documentation on pattern day trading rules ($25k minimum for day trading)

---

## Common Issues

| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| `ALPACA_PAPER is not set` | `.env` not loaded | Run from repo root, or `dotenv.load_dotenv('.env')` |
| `403 Forbidden` on orders | Paper trading disabled on account | Log into alpaca.markets → Paper Trading → enable |
| `No signals` every day | Trend filter failing (SPY below SMA200) | This is correct behavior in bear markets — wait for uptrend |
| Stale data warnings | Market closed or yfinance rate limit | Check market calendar; run again next trading day |
| Position not closing at hold_days | Order already filled or manually closed | Check journal for existing entry record |

---

## Going Live (After Paper Validation)

When paper criteria are met and you want to go live:

1. Fund your Alpaca account with real money
2. Change `ALPACA_PAPER=false` in `.env` **only after** double-checking
3. Review all paper trades — every mistake you would have made is in the journal
4. Start with small notional until you trust the execution

> **Warning:** `ALPACA_PAPER=false` enables real order execution. Real trades can lose real money.
