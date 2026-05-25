"""
backtest_best.py
Run best params through backtest_vbt with 5-ticker universe and produce full metrics.
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

# Best params from sweep
BREAKOUT_LB = 15
ATR_MULT    = 2.0
VOL_THRESH  = 1.5
HOLD_CAP    = 10


def rolling_max(arr, window):
    return pd.Series(arr).rolling(window=window, min_periods=window).max().values

def rolling_mean(arr, window):
    return pd.Series(arr).rolling(window=window, min_periods=window).mean().values


def build_signals(data, breakout_lb, vol_thresh):
    signals = {}
    spy_df = data["SPY"]
    for ticker, df in data.items():
        close  = df["close"]
        high   = df["high"]
        volume = df["volume"]
        spy_close = spy_df["close"].values
        spy_sma   = spy_df["sma200"].values
        spy_trend = spy_close > spy_sma

        high_lb     = rolling_max(high.values, breakout_lb)
        vol_sma20    = rolling_mean(volume.values, 20)  # vol SMA always 20d per SPEC

        lag_high_lb    = pd.Series(high_lb).shift(1).values
        lag_vol_sma20  = pd.Series(vol_sma20).shift(1).values

        cond_breakout = close.values > lag_high_lb
        cond_volume   = volume.values > vol_thresh * lag_vol_sma20

        entry = cond_breakout & cond_volume & spy_trend
        entry = pd.Series(entry, index=df.index).fillna(False).astype(bool)
        signals[ticker] = entry
    return signals


def run_backtest(data, signals, atr_mult, hold_cap_days, breakout_lb, capital=CAPITAL):
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

                warmup = breakout_lb + 50
                if i < warmup:
                    continue
                if pd.isna(df_t["sma200"].iloc[i]) or pd.isna(df_t["atr14"].iloc[i]) or df_t["atr14"].iloc[i] == 0:
                    continue

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
    ann_return   = total_return / capital
    n_trades     = len(trades_df)
    n_wins       = len(wins)
    win_rate     = n_wins / n_trades if n_trades else 0
    avg_win      = wins["pnl"].mean() if len(wins) else 0
    avg_loss     = loss["pnl"].mean() if len(loss) else 0
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
        "total_return":    round(total_return, 2),
        "ann_return":      round(ann_return, 4),
        "capital":         capital,
        "n_trades":        n_trades,
        "win_rate":        round(win_rate, 4),
        "avg_win":         round(avg_win, 2),
        "avg_loss":        round(avg_loss, 2),
        "profit_factor":   round(profit_factor, 4),
        "max_drawdown":    max_drawdown,
        "sharpe":          sharpe,
    }


def main():
    repo_root = Path(__file__).parent.parent.resolve()
    data_dir  = repo_root / "data" / "processed"

    print("=== SwingLock Best Params — Full Backtest ===")
    print(f"  Universe: {TICKERS}")
    print(f"  Params: breakout_lb={BREAKOUT_LB}, atr_mult={ATR_MULT}, vol_thresh={VOL_THRESH}, hold_days={HOLD_CAP}")
    print()

    # Load data
    data = {}
    for t in TICKERS:
        p = data_dir / f"{t}.csv"
        df = pd.read_csv(p, parse_dates=["date"], index_col="date")
        data[t] = df

    # Build signals
    signals = build_signals(data, BREAKOUT_LB, VOL_THRESH)

    # Run backtest
    trades, equity_curve = run_backtest(data, signals, ATR_MULT, HOLD_CAP, BREAKOUT_LB, CAPITAL)

    # Save trades + equity
    out_dir = repo_root / "backtest" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    trades.to_csv(out_dir / "trades_best.csv", index=False)
    equity_curve.to_csv(out_dir / "equity_best.csv", index=False)

    # Compute full-period metrics
    metrics_full = compute_metrics(trades, equity_curve, CAPITAL)

    # IS
    trades_is = trades[trades["date"] <= IS_END]
    equity_is = equity_curve[equity_curve["date"] <= IS_END]
    metrics_is = compute_metrics(trades_is, equity_is, CAPITAL)
    metrics_is["start_date"] = START
    metrics_is["end_date"]   = IS_END

    # OOS
    trades_oos = trades[trades["date"] >= OOS_START]
    equity_oos = equity_curve[equity_curve["date"] >= OOS_START]
    metrics_oos = compute_metrics(trades_oos, equity_oos, CAPITAL)
    metrics_oos["start_date"] = OOS_START
    metrics_oos["end_date"]   = END

    print("--- FULL PERIOD ---")
    for k, v in metrics_full.items():
        print(f"  {k:20s}: {v}")

    print("\n--- IN-SAMPLE (2019-2021) ---")
    for k, v in metrics_is.items():
        print(f"  {k:20s}: {v}")

    print("\n--- OUT-OF-SAMPLE (2022-2024) ---")
    for k, v in metrics_oos.items():
        print(f"  {k:20s}: {v}")

    # Save
    with open(out_dir / "metrics_best_is.json", "w") as f:
        json.dump(metrics_is, f, indent=2)
    with open(out_dir / "metrics_best_oos.json", "w") as f:
        json.dump(metrics_oos, f, indent=2)
    with open(out_dir / "metrics_best_full.json", "w") as f:
        json.dump(metrics_full, f, indent=2)

    # SPEC check
    print("\n=== SPEC Criteria Check ===")
    spec_checks = {
        "n_trades ≥ 30":       (metrics_full["n_trades"] >= 30, metrics_full["n_trades"]),
        "expectancy/trade > $0": (trades["pnl"].mean() > 0, round(trades["pnl"].mean(), 2)),
        "win rate > 40%":     (metrics_full["win_rate"] > 0.40, f"{metrics_full['win_rate']*100:.1f}%"),
        "profit factor > 1.2": (metrics_oos["profit_factor"] > 1.2, metrics_oos["profit_factor"]),
        "max drawdown < 10%": (metrics_full["max_drawdown"] < 0.10, f"{metrics_full['max_drawdown']*100:.2f}%"),
    }
    all_pass = True
    for criterion, (val, result) in spec_checks.items():
        status = "PASS" if val else "FAIL"
        if not val:
            all_pass = False
        print(f"  [{status}] {criterion}: {result}")

    print(f"\nOverall: {'ALL PASS' if all_pass else 'SOME FAIL'}")


if __name__ == "__main__":
    main()