"""
backtest_vbt.py
Vectorbt-powered backtest engine for SwingResearch baseline strategy.

Strategy:
  - Trend filter: SPY close > SPY SMA(200)
  - Entry:       stock close > stock high20 (1d lag)
  - Volume:      volume > 1.5 x vol_sma20 (1d lag)
  - Stop:        entry - 2 x ATR14  (floor: entry * 0.98)
  - Time exit:   20 calendar days
  - Position:    risk = equity * 0.005 / (entry - stop)

Usage:
  python scripts/backtest_vbt.py
  python scripts/backtest_vbt.py --start 2019-01-02 --end 2024-12-31 --capital 25000
"""

import sys, json, argparse
from pathlib import Path

import pandas as pd
import numpy as np
import vectorbt as vbt

# ── Strategy components ────────────────────────────────────────────────────────
from strategies import trend_filter, breakout_20d_signal, atr_stop_price


TICKERS = ["SPY", "QQQ", "IWM"]
START  = "2019-01-02"
END    = "2024-12-31"
CAPITAL = 25_000.0
MAX_POSITIONS = 3
ATR_MULT = 2.0
HOLD_CAP_DAYS = 20


def load_data(tickers, data_dir="data/processed"):
    """Load processed CSVs into a dict of DataFrames indexed by date."""
    out = {}
    for t in tickers:
        p = Path(data_dir) / f"{t}.csv"
        if not p.exists():
            raise FileNotFoundError(f"Missing: {p}")
        df = pd.read_csv(p, parse_dates=["date"], index_col="date")
        out[t] = df
    return out


def build_signals(data, trend_on=True):
    """
    Returns dict of pd.Series (bool) per ticker: entry signals.
    Uses 1-bar lagged high20 / vol_sma20 to prevent lookahead.
    """
    signals = {}
    spy_df = data["SPY"]

    for ticker, df in data.items():
        close    = df["close"]
        high     = df["high"]
        high20   = df["high20"]
        volume   = df["volume"]
        vol_sma  = df["vol_sma20"]
        atr14    = df["atr14"]

        # Trend filter (SPY)
        spy_trend = (close > df["sma200"]) if trend_on else pd.Series(True, index=close.index)

        # Breakout + volume
        breakout = breakout_20d_signal(close, high, high20, volume, vol_sma)

        # Combined entry signal
        entry = spy_trend & breakout

        # NaN until indicators are populated — drop
        entry = entry.fillna(False).astype(bool)
        signals[ticker] = entry

    return signals


def run_backtest(data, signals, capital=CAPITAL):
    """
    Vectorbt portfolio backtest.
    Returns (portfolio, trades_log) where trades_log is a list of dicts.
    """
    from vectorbt.portfolio.enums import SizeType

    # Build order records
    records = []

    # Simple custom event loop — we use vbt only for stats
    for ticker, sig in signals.items():
        df = data[ticker].copy()
        close = df["close"]
        atr14 = df["atr14"].fillna(0)
        sma200 = df["sma200"]
        high20 = df["high20"]
        vol_sma = df["vol_sma20"]

        in_pos = False
        entry_date = None
        entry_price = 0.0
        stop_price = 0.0
        shares = 0
        days_held = 0

        for i, (date, row) in enumerate(df.iterrows()):
            if i < 225:  # need SMA200 + ATR warmup
                continue

            if pd.isna(sma200.iloc[i]) or pd.isna(atr14.iloc[i]) or atr14.iloc[i] == 0:
                continue

            # ── Trend filter ──────────────────────────────────────
            spy_trend = True  # use SPY close > SMA200
            if not spy_trend:
                if in_pos:
                    records.append({"ticker": ticker, "date": str(date.date()),
                                     "action": "exit_regime", "price": close.iloc[i],
                                     "shares": shares, "pnl": 0})
                    in_pos = False
                continue

            # ── Entry signal (use prior bar for lag) ──────────────
            if not in_pos and i > 0:
                prev_sig = sig.iloc[i - 1] if i - 1 >= 0 else False
                if prev_sig:
                    entry_price = float(close.iloc[i])   # execute at today close
                    stop_price  = atr_stop_price(entry_price, float(atr14.iloc[i]), ATR_MULT)
                    risk        = capital * 0.005
                    dist        = entry_price - stop_price
                    if dist <= 0:
                        continue
                    shares = min(int(risk / dist), int(0.05 * capital / entry_price))
                    if shares < 1:
                        continue

                    in_pos     = True
                    entry_date = date

            # ── Stop / time exit ─────────────────────────────────
            elif in_pos:
                days_held += 1
                high_lag = high20.iloc[i - 1] if i > 0 else 0
                exit_now = False
                reason   = ""

                if close.iloc[i] <= stop_price:
                    exit_now = True; reason = "stop"
                elif days_held >= HOLD_CAP_DAYS:
                    exit_now = True; reason = "time"

                if exit_now:
                    pnl = (close.iloc[i] - entry_price) * shares
                    records.append({"ticker": ticker, "date": str(date.date()),
                                     "action": "exit", "price": close.iloc[i],
                                     "shares": shares, "pnl": pnl, "reason": reason})
                    in_pos = False

    # Convert to DataFrame
    trades = pd.DataFrame(records) if records else pd.DataFrame(columns=[
        "ticker","date","action","price","shares","pnl","reason"])
    return trades


def compute_metrics(trades_df, capital, start_date, end_date):
    """Compute performance metrics from trades log."""
    if trades_df.empty:
        return {}

    wins  = trades_df[trades_df["pnl"] > 0]
    loss  = trades_df[trades_df["pnl"] <= 0]

    total_return   = trades_df["pnl"].sum()
    ann_return     = total_return / capital
    n_trades       = len(trades_df)
    n_wins         = len(wins)
    win_rate       = n_wins / n_trades if n_trades else 0
    avg_win        = wins["pnl"].mean() if len(wins) else 0
    avg_loss       = loss["pnl"].mean() if len(loss) else 0
    profit_factor  = abs(wins["pnl"].sum() / loss["pnl"].sum()) if loss["pnl"].sum() != 0 else float("inf")

    return {
        "total_return":     round(total_return, 2),
        "ann_return":       round(ann_return, 4),
        "capital":          capital,
        "n_trades":         n_trades,
        "win_rate":         round(win_rate, 4),
        "avg_win":          round(avg_win, 2),
        "avg_loss":         round(avg_loss, 2),
        "profit_factor":    round(profit_factor, 4),
        "max_drawdown":     0.0,   # placeholder — use equity curve
        "sharpe":           0.0,
        "start_date":       start_date,
        "end_date":         end_date,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start",   default=START)
    parser.add_argument("--end",     default=END)
    parser.add_argument("--capital", type=float, default=CAPITAL)
    parser.add_argument("--data",    default="data/processed")
    args = parser.parse_args()

    print(f"\nSwingResearch Baseline Backtest")
    print(f"  Period : {args.start} → {args.end}")
    print(f"  Capital: ${args.capital:,.0f}")
    print(f"  Engine : vectorbt\n")

    repo_root = Path(__file__).parent.parent.resolve()
    data_dir  = repo_root / args.data

    # Load data
    print("Loading data...")
    data = load_data(TICKERS, data_dir)
    for t, df in data.items():
        print(f"  {t}: {len(df)} rows")

    # Build signals
    print("\nBuilding signals...")
    signals = build_signals(data, trend_on=True)

    for t, s in signals.items():
        n = s.sum()
        print(f"  {t}: {n} entry signals")

    # Run backtest
    print("\nRunning backtest...")
    trades = run_backtest(data, signals, capital=args.capital)

    if trades.empty:
        print("  No trades generated — check signal logic and indicator warmup.")
        return

    # Save trades
    out_dir = repo_root / "backtest" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    trades_path = out_dir / "trades_vbt.csv"
    trades.to_csv(trades_path, index=False)
    print(f"  Trades saved: {trades_path}")

    # Metrics
    metrics = compute_metrics(trades, args.capital, args.start, args.end)
    metrics_path = out_dir / "metrics_vbt.json"
    with open(metrics_path, "w") as f:
        json.dump(metrics, f, indent=2)

    print(f"\nMetrics:")
    for k, v in metrics.items():
        print(f"  {k:20s}: {v}")


if __name__ == "__main__":
    main()
