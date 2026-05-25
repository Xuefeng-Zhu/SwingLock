"""
parameter_sweep.py
Run a full parameter sweep for the SwingLock breakout strategy.
Tests combinations of breakout lookback, ATR mult, vol threshold, holding days.
Universe: SPY, QQQ, IWM, XLK, XLF
"""

import sys, json, argparse
from pathlib import Path
import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from strategies import atr_stop_price


TICKERS = ["SPY", "QQQ", "IWM", "XLK", "XLF"]
START  = "2019-01-02"
END    = "2024-12-31"
CAPITAL = 25_000.0
MAX_POSITIONS = 3
IS_END   = "2021-12-31"
OOS_START = "2022-01-02"


def load_data(tickers, data_dir="data/processed"):
    out = {}
    for t in tickers:
        p = Path(data_dir) / f"{t}.csv"
        df = pd.read_csv(p, parse_dates=["date"], index_col="date")
        out[t] = df
    return out


def rolling_max(arr, window):
    return pd.Series(arr).rolling(window=window, min_periods=window).max().values

def rolling_min(arr, window):
    return pd.Series(arr).rolling(window=window, min_periods=window).min().values

def rolling_mean(arr, window):
    return pd.Series(arr).rolling(window=window, min_periods=window).mean().values

def true_range(high, low, prev_close):
    return np.maximum(high - low, np.abs(high - prev_close), np.abs(low - prev_close))

def compute_atr14(high, low, close, period=14):
    tr = true_range(high, low, np.roll(close, 1))
    tr[0] = high[0] - low[0]
    atr = np.zeros_like(tr, dtype=float)
    atr[period - 1] = tr[:period].mean()
    for i in range(period, len(tr)):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    return atr


def build_signals_for_params(data, breakout_lb, vol_thresh):
    """
    Build entry signals for custom breakout lookback and volume threshold.
    breakout_lb: days for rolling high (lookback window)
    vol_thresh: multiplier for volume SMA
    """
    signals = {}
    spy_df = data["SPY"]

    for ticker, df in data.items():
        close = df["close"]
        high  = df["high"]
        volume = df["volume"]

        # Compute rolling indicators on-the-fly with custom lookback
        high_lb     = rolling_max(high.values, breakout_lb)
        vol_sma_lb  = rolling_mean(volume.values, 20)  # vol SMA always 20d per SPEC

        # Lag by 1 bar for no-lookahead
        lag_high_lb   = pd.Series(high_lb).shift(1).values
        lag_vol_sma_lb = pd.Series(vol_sma_lb).shift(1).values

        # Trend filter using SPY
        spy_close = spy_df["close"].values
        spy_sma   = spy_df["sma200"].values
        spy_trend = spy_close > spy_sma

        # Breakout + volume confirmation
        cond_breakout = close.values > lag_high_lb
        cond_volume   = volume.values > vol_thresh * lag_vol_sma_lb

        entry = cond_breakout & cond_volume & spy_trend
        entry = pd.Series(entry, index=df.index).fillna(False).astype(bool)
        signals[ticker] = entry

    return signals


def run_backtest(data, signals, atr_mult, hold_cap_days, breakout_lb, capital=CAPITAL):
    """Custom backtest runner that accepts atr_mult and hold_cap_days."""
    all_dates = sorted(set().union(*[df.index for df in data.values()]))
    all_dates = [d for d in all_dates if d.year >= 2019]

    open_pos = {}
    portfolio_equity = capital
    peak_equity = capital
    records = []
    equity_log = []

    def close_pos(ticker, date, price, reason):
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

    for date in all_dates:
        for ticker, pos in list(open_pos.items()):
            if ticker in data and date in data[ticker].index:
                close_price = data[ticker]["close"].loc[date]
                if close_price <= pos["stop_price"]:
                    close_pos(ticker, date, close_price, "stop")
                    continue
                pos["days_held"] += 1
                if pos["days_held"] >= hold_cap_days:
                    close_pos(ticker, date, close_price, "time")

        equity_log.append({"date": str(date.date()), "equity": round(portfolio_equity, 2)})

        if len(open_pos) < MAX_POSITIONS:
            for ticker, sig in signals.items():
                if ticker in open_pos or ticker not in data:
                    continue
                if date not in data[ticker].index:
                    continue
                df_t = data[ticker]
                i = df_t.index.get_loc(date)

                warmup = breakout_lb + 50  # dynamic warmup based on lookback
                if i < warmup:
                    continue
                if pd.isna(df_t["sma200"].iloc[i]) or pd.isna(df_t["atr14"].iloc[i]) or df_t["atr14"].iloc[i] == 0:
                    continue

                # Trend filter
                spy_close = data["SPY"]["close"].iloc[i]
                spy_sma   = data["SPY"]["sma200"].iloc[i]
                if pd.isna(spy_close) or pd.isna(spy_sma) or spy_close <= spy_sma:
                    continue

                if i < 1:
                    continue
                if not sig.iloc[i - 1]:
                    continue

                entry_price = float(df_t["close"].iloc[i])
                atr_val     = float(df_t["atr14"].iloc[i])
                stop_price  = atr_stop_price(entry_price, atr_val, atr_mult)
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

    # Force-close at end
    for ticker, pos in list(open_pos.items()):
        if ticker in data:
            last_date = data[ticker].index[-1]
            last_price = data[ticker]["close"].loc[last_date]
            close_pos(ticker, last_date, last_price, "eof")
        else:
            del open_pos[ticker]

    trades = pd.DataFrame(records) if records else pd.DataFrame(columns=[
        "ticker","date","action","price","shares","pnl","reason","equity_after"])
    equity_curve = pd.DataFrame(equity_log) if equity_log else pd.DataFrame(columns=["date","equity"])
    return trades, equity_curve


def compute_metrics(trades_df, equity_curve, capital):
    if trades_df.empty:
        return {}
    wins = trades_df[trades_df["pnl"] > 0]
    loss = trades_df[trades_df["pnl"] <= 0]
    total_return = trades_df["pnl"].sum()
    n_trades = len(trades_df)
    n_wins = len(wins)
    win_rate = n_wins / n_trades if n_trades else 0
    avg_win = wins["pnl"].mean() if len(wins) else 0
    avg_loss = loss["pnl"].mean() if len(loss) else 0
    profit_factor = abs(wins["pnl"].sum() / loss["pnl"].sum()) if loss["pnl"].sum() != 0 else float("inf")

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

    if not equity_curve.empty and "equity" in equity_curve.columns:
        eq = equity_curve["equity"].values
        if len(eq) > 1:
            returns = np.diff(eq) / eq[:-1]
            ret_mean = returns.mean()
            ret_std = returns.std()
            if ret_std > 0:
                sharpe = round(ret_mean / ret_std * np.sqrt(252), 4)
            else:
                sharpe = 0.0
        else:
            sharpe = 0.0
    else:
        sharpe = 0.0

    return {
        "total_return": round(total_return, 2),
        "n_trades": n_trades,
        "win_rate": round(win_rate, 4),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "profit_factor": round(profit_factor, 4),
        "max_drawdown": max_drawdown,
        "sharpe": sharpe,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--breakout_lb", nargs="+", type=int, default=[10, 15, 20, 25])
    parser.add_argument("--atr_mult", nargs="+", type=float, default=[1.5, 2.0, 2.5, 3.0])
    parser.add_argument("--vol_thresh", nargs="+", type=float, default=[1.2, 1.5, 2.0])
    parser.add_argument("--hold_days", nargs="+", type=int, default=[10, 15, 20])
    parser.add_argument("--data", default="data/processed")
    args = parser.parse_args()

    repo_root = Path(__file__).parent.parent.resolve()
    data_dir = repo_root / args.data

    print("Loading data for 5-ticker universe...")
    data = load_data(TICKERS, data_dir)
    for t, df in data.items():
        print(f"  {t}: {len(df)} rows")

    results = []

    total = (len(args.breakout_lb) * len(args.atr_mult) *
             len(args.vol_thresh) * len(args.hold_days))
    print(f"\nRunning {total} parameter combinations...")

    for breakout_lb in args.breakout_lb:
        for atr_mult in args.atr_mult:
            for vol_thresh in args.vol_thresh:
                for hold_days in args.hold_days:
                    # Build signals for these params
                    signals = build_signals_for_params(data, breakout_lb, vol_thresh)

                    # Run backtest
                    trades, equity_curve = run_backtest(
                        data, signals, atr_mult, hold_days, breakout_lb, CAPITAL
                    )

                    if trades.empty:
                        results.append({
                            "breakout_lb": breakout_lb, "atr_mult": atr_mult,
                            "vol_thresh": vol_thresh, "hold_days": hold_days,
                            "n_trades_is": 0, "n_trades_oos": 0, "n_trades_total": 0,
                            "pf_is": 0, "pf_oos": 0, "pf_full": 0, "sharpe_oos": 0,
                            "max_dd": 0, "win_rate_oos": 0,
                        })
                        continue

                    # Split IS / OOS
                    trades_is = trades[trades["date"] <= IS_END]
                    trades_oos = trades[trades["date"] >= OOS_START]
                    equity_is = equity_curve[equity_curve["date"] <= IS_END]
                    equity_oos = equity_curve[equity_curve["date"] >= OOS_START]

                    metrics_is  = compute_metrics(trades_is, equity_is, CAPITAL)
                    metrics_oos  = compute_metrics(trades_oos, equity_oos, CAPITAL)
                    metrics_full = compute_metrics(trades, equity_curve, CAPITAL)

                    results.append({
                        "breakout_lb": breakout_lb,
                        "atr_mult": atr_mult,
                        "vol_thresh": vol_thresh,
                        "hold_days": hold_days,
                        "n_trades_is": metrics_is.get("n_trades", 0),
                        "n_trades_oos": metrics_oos.get("n_trades", 0),
                        "n_trades_total": metrics_is.get("n_trades", 0) + metrics_oos.get("n_trades", 0),
                        "pf_is": metrics_is.get("profit_factor", 0),
                        "pf_oos": metrics_oos.get("profit_factor", 0),
                        "pf_full": metrics_full.get("profit_factor", 0),
                        "sharpe_oos": metrics_oos.get("sharpe", 0),
                        "max_dd": metrics_full.get("max_drawdown", 0),
                        "win_rate_oos": metrics_oos.get("win_rate", 0),
                    })

    df_results = pd.DataFrame(results)

    out_dir = repo_root / "backtest" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "sweep_results.csv"
    df_results.to_csv(out_path, index=False)
    print(f"\nSweep results saved: {out_path}")
    print(f"Shape: {df_results.shape}")

    # Print top 10 by OOS Pf with n_trades >= 30
    df_pass = df_results[df_results["n_trades_total"] >= 30]
    if not df_pass.empty:
        df_sorted = df_pass.sort_values("pf_oos", ascending=False).head(10)
        print("\nTop 10 combos (n_trades >= 30) by OOS profit factor:")
        print(df_sorted[["breakout_lb","atr_mult","vol_thresh","hold_days",
                          "n_trades_total","pf_oos","sharpe_oos","max_dd"]].to_string(index=False))
    else:
        print("\nNo combos with n_trades >= 30 found. Best efforts:")
        df_sorted = df_results.sort_values("pf_oos", ascending=False).head(5)
        print(df_sorted[["breakout_lb","atr_mult","vol_thresh","hold_days",
                          "n_trades_total","pf_oos","sharpe_oos"]].to_string(index=False))


if __name__ == "__main__":
    main()