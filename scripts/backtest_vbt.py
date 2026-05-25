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

        # Trend filter — use SPY data to determine market regime
        spy_close = spy_df["close"]
        spy_sma   = spy_df["sma200"]
        spy_trend = spy_close > spy_sma  # Series aligned on same index

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
    Returns (trades_df, equity_curve_df) where equity_curve_df has daily portfolio value.
    """
    # ── Portfolio-level day-by-day tracker ─────────────────────────────────────
    # We'll walk every calendar date across all tickers, maintain open positions,
    # mark-to-market daily, and record equity after each event.
    import pandas as pd

    # Collect all unique dates across all tickers
    all_dates = sorted(set().union(*[df.index for df in data.values()]))
    all_dates = [d for d in all_dates if d.year >= 2019]

    # Open positions: {ticker: {entry_date, entry_price, shares, stop_price, days_held}}
    open_pos = {}   # ticker -> position dict
    portfolio_equity = capital
    peak_equity = capital

    records = []   # trade log
    equity_log = []  # daily equity marks

    def close_pos(ticker, date, price, reason, records):
        nonlocal portfolio_equity, peak_equity
        pos = open_pos[ticker]
        pnl = (price - pos["entry_price"]) * pos["shares"]
        portfolio_equity += pnl
        peak_equity = max(peak_equity, portfolio_equity)
        records.append({
            "ticker": ticker, "date": str(date.date()),
            "action": "exit", "price": price,
            "shares": pos["shares"], "pnl": round(pnl, 2),
            "reason": reason, "equity_after": round(portfolio_equity, 2)
        })
        del open_pos[ticker]

    # Walk each date
    for date in all_dates:
        # ── Mark-to-market open positions ───────────────────────────────────
        for ticker, pos in list(open_pos.items()):
            if ticker in data and date in data[ticker].index:
                close_price = data[ticker]["close"].loc[date]
                # Stop-loss check
                if close_price <= pos["stop_price"]:
                    close_pos(ticker, date, close_price, "stop", records)
                    continue
                # Time-exit check
                pos["days_held"] += 1
                if pos["days_held"] >= HOLD_CAP_DAYS:
                    close_pos(ticker, date, close_price, "time", records)

        # ── Log equity after processing exits (before new entries) ──────────
        equity_log.append({"date": str(date.date()), "equity": round(portfolio_equity, 2)})

        # ── Entry signals ───────────────────────────────────────────────────
        if len(open_pos) < MAX_POSITIONS:
            for ticker, sig in signals.items():
                if ticker in open_pos or ticker not in data:
                    continue
                if date not in data[ticker].index:
                    continue
                df_t = data[ticker]
                i = df_t.index.get_loc(date)

                if i < 225:
                    continue
                if pd.isna(df_t["sma200"].iloc[i]) or pd.isna(df_t["atr14"].iloc[i]) or df_t["atr14"].iloc[i] == 0:
                    continue

                # Trend filter
                spy_close = data["SPY"]["close"].iloc[i]
                spy_sma   = data["SPY"]["sma200"].iloc[i]
                if pd.isna(spy_close) or pd.isna(spy_sma) or spy_close <= spy_sma:
                    continue

                # Entry on prior bar signal
                if i < 1:
                    continue
                if not sig.iloc[i - 1]:
                    continue

                entry_price = float(df_t["close"].iloc[i])
                atr_val     = float(df_t["atr14"].iloc[i])
                stop_price  = atr_stop_price(entry_price, atr_val, ATR_MULT)
                dist        = entry_price - stop_price
                if dist <= 0:
                    continue

                risk_dollar = portfolio_equity * 0.005
                shares      = min(int(risk_dollar / dist),
                                   int(0.05 * portfolio_equity / entry_price))
                if shares < 1:
                    continue

                open_pos[ticker] = {
                    "entry_date": date,
                    "entry_price": entry_price,
                    "shares": shares,
                    "stop_price": stop_price,
                    "days_held": 0
                }

    # Force-close any open positions at end
    for ticker, pos in list(open_pos.items()):
        if ticker in data:
            last_date = data[ticker].index[-1]
            last_price = data[ticker]["close"].loc[last_date]
            close_pos(ticker, last_date, last_price, "eof", records)
        else:
            del open_pos[ticker]

    # ── Convert to DataFrames ───────────────────────────────────────────────────
    trades = pd.DataFrame(records) if records else pd.DataFrame(columns=[
        "ticker","date","action","price","shares","pnl","reason","equity_after"])
    equity_curve = pd.DataFrame(equity_log) if equity_log else pd.DataFrame(columns=["date","equity"])
    return trades, equity_curve


def compute_metrics(trades_df, equity_curve, capital, start_date, end_date):
    """Compute performance metrics from trades log and equity curve."""
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

    # ── Max drawdown from equity curve ─────────────────────────────────────────
    if not equity_curve.empty and "equity" in equity_curve.columns:
        eq = equity_curve["equity"].values
        peak = eq[0]
        max_dd = 0.0
        for v in eq:
            if v > peak:
                peak = v
            dd = (peak - v) / peak if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd
        max_drawdown = round(max_dd, 4)
    else:
        max_drawdown = 0.0

    # ── Sharpe ratio from equity curve ─────────────────────────────────────────
    # Daily returns, annualize with sqrt(252), risk-free rate = 0
    if not equity_curve.empty and "equity" in equity_curve.columns:
        eq = equity_curve["equity"].values
        if len(eq) > 1:
            returns = np.diff(eq) / eq[:-1]
            ret_mean = returns.mean()
            ret_std  = returns.std()
            if ret_std > 0:
                sharpe = round(ret_mean / ret_std * np.sqrt(252), 4)
            else:
                sharpe = 0.0
        else:
            sharpe = 0.0
    else:
        sharpe = 0.0

    return {
        "total_return":     round(total_return, 2),
        "ann_return":       round(ann_return, 4),
        "capital":          capital,
        "n_trades":         n_trades,
        "win_rate":         round(win_rate, 4),
        "avg_win":          round(avg_win, 2),
        "avg_loss":         round(avg_loss, 2),
        "profit_factor":    round(profit_factor, 4),
        "max_drawdown":     max_drawdown,
        "sharpe":           sharpe,
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
    trades, equity_curve = run_backtest(data, signals, capital=args.capital)

    if trades.empty:
        print("  No trades generated — check signal logic and indicator warmup.")
        return

    # Save trades
    out_dir = repo_root / "backtest" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    trades_path = out_dir / "trades_vbt.csv"
    trades.to_csv(trades_path, index=False)
    print(f"  Trades saved: {trades_path}")

    equity_path = out_dir / "equity_vbt.csv"
    equity_curve.to_csv(equity_path, index=False)
    print(f"  Equity curve saved: {equity_path}")

    # Metrics
    metrics = compute_metrics(trades, equity_curve, args.capital, args.start, args.end)
    metrics_path = out_dir / "metrics_vbt.json"
    with open(metrics_path, "w") as f:
        json.dump(metrics, f, indent=2)

    print(f"\nMetrics:")
    for k, v in metrics.items():
        print(f"  {k:20s}: {v}")


if __name__ == "__main__":
    main()
