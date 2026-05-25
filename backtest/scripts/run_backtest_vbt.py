#!/usr/bin/env python3
"""Vectorbt-based backtester for 20-day breakout swing trading strategy."""

import os
import json
import math
import pandas as pd
import numpy as np
import vectorbt as vbt

from report import compute_metrics, print_report

# ── Constants ──────────────────────────────────────────────────────────────────
STARTING_CAPITAL = 100000.0
MAX_POSITIONS = 5
MAX_RISK_PCT = 0.005
MAX_POS_PCT = 0.05
HOLD_DAYS_MAX = 20
STOP_ATR_MULT = 1.5
TARGET_R_MULT = 2.5
VOL_MULTIPLIER = 1.5
MAX_DAY_GAIN_SKIP = 0.08

TICKERS = ["SPY", "QQQ", "IWM", "NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "TSLA"]
DATA_DIR = "/home/azureuser/workspace/SwingLock/backtest/data/processed"
RESULTS_DIR = "/home/azureuser/workspace/SwingLock/backtest/results"


def load_data(ticker: str) -> pd.DataFrame:
    """Load CSV for a ticker and return raw OHLCV DataFrame with date index."""
    path = os.path.join(DATA_DIR, f"{ticker}.csv")
    df = pd.read_csv(path, parse_dates=["date"], index_col="date")
    df = df[["open", "high", "low", "close", "volume"]].astype(float)
    df.sort_index(inplace=True)
    return df


def compute_atr14(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """Standard ATR(14): rolling 14-period mean of True Range."""
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(14).mean()


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add rolling indicators to a raw OHLCV DataFrame (in-place copy)."""
    df = df.copy()
    df["high_20"] = df["high"].rolling(20).max()
    df["low_20"] = df["low"].rolling(20).min()
    df["vol_sma20"] = df["volume"].rolling(20).mean()
    df["atr14"] = compute_atr14(df["high"], df["low"], df["close"])
    df["daily_gain"] = df["close"] / df["close"].shift(1) - 1.0
    df["ret_20d"] = df["close"] / df["close"].shift(20) - 1.0
    # 1-bar lagged versions for entry rules
    df["high_20_prev"] = df["high_20"].shift(1)
    df["vol_sma20_prev"] = df["vol_sma20"].shift(1)
    df["atr14_prev"] = df["atr14"].shift(1)
    return df


def run_backtest() -> None:
    os.makedirs(RESULTS_DIR, exist_ok=True)

    # 1. Load & compute indicators for every ticker
    data = {}
    for t in TICKERS:
        raw = load_data(t)
        data[t] = compute_indicators(raw)

    # SPY-specific: 50-day SMA
    data["SPY"]["sma50"] = data["SPY"]["close"].rolling(50).mean()

    # 2. Align on common date index
    common = None
    for t in TICKERS:
        idx = set(data[t].index)
        common = idx if common is None else common & idx
    common_index = sorted(common)

    if len(common_index) < 50:
        print("ERROR: fewer than 50 common trading days — cannot run backtest.")
        return

    # 3. Manual day-by-day portfolio simulation
    cash = STARTING_CAPITAL
    positions: dict = {}       # ticker -> position dict
    closed_trades: list = []
    equity_curve: list = [STARTING_CAPITAL]
    equity_dates: list = [common_index[0]]

    for current_date in common_index:
        date_str = current_date.strftime("%Y-%m-%d")

        # ── Step A: Process exits (stop, target, time) ──────────────────────
        to_remove = []
        for ticker, pos in positions.items():
            row = data[ticker].loc[current_date]
            pos["day_count"] += 1

            exit_price = None
            reason = None

            # Stop-loss (intraday low triggers stop)
            if row["low"] < pos["stop_price"]:
                exit_price = pos["stop_price"]
                reason = "stop_loss"
            # Target hit
            elif row["high"] >= pos["target_price"]:
                exit_price = pos["target_price"]
                reason = "target"
            # Maximum holding period reached
            elif pos["day_count"] >= HOLD_DAYS_MAX:
                exit_price = row["close"]
                reason = "time_exit"

            if reason is not None:
                pnl = (exit_price - pos["entry_price"]) * pos["shares"]
                cash += exit_price * pos["shares"]
                closed_trades.append({
                    "ticker": ticker,
                    "entry_date": pos["entry_date"],
                    "exit_date": date_str,
                    "entry_price": pos["entry_price"],
                    "exit_price": exit_price,
                    "shares": pos["shares"],
                    "pnl": round(pnl, 2),
                    "reason": reason,
                })
                to_remove.append(ticker)

        for t in to_remove:
            del positions[t]

        # ── Step B: Check entry signals ─────────────────────────────────────
        available_slots = MAX_POSITIONS - len(positions)
        if available_slots > 0:
            # Compute current equity (cash + mark-to-market of open positions)
            equity_before_entry = cash
            for t, p in positions.items():
                equity_before_entry += p["shares"] * data[t].loc[current_date]["close"]

            candidates = []
            for ticker in TICKERS:
                if ticker in positions:
                    continue
                row = data[ticker].loc[current_date]

                # Skip rows with missing indicators (not enough history)
                if pd.isna(row.get("high_20_prev")):
                    continue
                if pd.isna(row.get("atr14_prev")):
                    continue

                # Condition 1: breakout above prior-day 20-day high
                if not (row["close"] > row["high_20_prev"]):
                    continue

                # Condition 2: volume > 1.5 * prior-day vol SMA20
                if pd.isna(row.get("vol_sma20_prev")):
                    continue
                if not (row["volume"] > VOL_MULTIPLIER * row["vol_sma20_prev"]):
                    continue

                # Condition 3: stock 20d return > QQQ 20d return
                qqq_ret = data["QQQ"].loc[current_date]["ret_20d"]
                if pd.isna(qqq_ret) or pd.isna(row.get("ret_20d")):
                    continue
                if not (row["ret_20d"] > qqq_ret):
                    continue

                # Condition 4: SPY close above its 50-day SMA
                spy_row = data["SPY"].loc[current_date]
                if pd.isna(spy_row.get("sma50")):
                    continue
                if not (spy_row["close"] > spy_row["sma50"]):
                    continue

                # Condition 5: skip days with extreme gains (>8%)
                if pd.isna(row.get("daily_gain")):
                    continue
                if row["daily_gain"] >= MAX_DAY_GAIN_SKIP:
                    continue

                # RS strength for ranking (highest 20d return wins)
                rs_strength = row["ret_20d"]
                candidates.append((ticker, rs_strength, row["close"]))

            # Rank descending by RS strength
            candidates.sort(key=lambda x: x[1], reverse=True)

            for ticker, rs_val, close_price in candidates[:available_slots]:
                if ticker in positions:
                    continue
                if cash <= 0:
                    break

                row = data[ticker].loc[current_date]
                atr_val = row["atr14_prev"]
                if pd.isna(atr_val) or atr_val <= 0:
                    continue

                stop_price = max(
                    close_price - STOP_ATR_MULT * atr_val,
                    close_price * 0.98,
                )
                target_price = close_price + TARGET_R_MULT * (close_price - stop_price)
                dist = close_price - stop_price
                if dist <= 0:
                    continue

                # Position sizing
                shares_by_risk = int((equity_before_entry * MAX_RISK_PCT) / dist)
                shares_by_pos = int((equity_before_entry * MAX_POS_PCT) / close_price)
                shares_by_cash = int(cash / close_price)
                shares = min(shares_by_risk, shares_by_pos, shares_by_cash)

                if shares <= 0:
                    continue

                cost = shares * close_price
                if cost > cash:
                    continue

                cash -= cost
                positions[ticker] = {
                    "entry_date": date_str,
                    "entry_price": close_price,
                    "shares": shares,
                    "stop_price": stop_price,
                    "target_price": target_price,
                    "day_count": 0,
                }

        # ── Step C: Record equity curve snapshot ────────────────────────────
        portfolio_value = cash
        for ticker, pos in positions.items():
            portfolio_value += pos["shares"] * data[ticker].loc[current_date]["close"]
        equity_curve.append(round(portfolio_value, 2))
        equity_dates.append(current_date)

    # ── Force-close any remaining positions on the final bar ─────────────────
    last_date = common_index[-1]
    last_date_str = last_date.strftime("%Y-%m-%d")
    for ticker, pos in list(positions.items()):
        exit_price = data[ticker].loc[last_date]["close"]
        pnl = (exit_price - pos["entry_price"]) * pos["shares"]
        cash += exit_price * pos["shares"]
        closed_trades.append({
            "ticker": ticker,
            "entry_date": pos["entry_date"],
            "exit_date": last_date_str,
            "entry_price": pos["entry_price"],
            "exit_price": exit_price,
            "shares": pos["shares"],
            "pnl": round(pnl, 2),
            "reason": "end_of_backtest",
        })
    positions.clear()
    # Final equity update
    equity_curve[-1] = round(cash, 2)

    # ── Compute metrics ──────────────────────────────────────────────────────
    spy_start = data["SPY"]["close"].iloc[0]
    spy_end = data["SPY"]["close"].iloc[-1]
    spy_total_return = spy_end / spy_start - 1.0

    metrics = compute_metrics(equity_curve, closed_trades, STARTING_CAPITAL, spy_total_return)
    metrics["start_date"] = equity_dates[0].strftime("%Y-%m-%d")
    metrics["end_date"] = equity_dates[-1].strftime("%Y-%m-%d")

    # ── Save results ─────────────────────────────────────────────────────────
    # Equity curve CSV
    equity_df = pd.DataFrame({"date": equity_dates, "equity": equity_curve})
    equity_df.to_csv(os.path.join(RESULTS_DIR, "equity.csv"), index=False)

    # Trades CSV
    trades_df = pd.DataFrame(closed_trades)
    if not trades_df.empty:
        trades_df = trades_df[
            ["ticker", "entry_date", "exit_date", "entry_price",
             "exit_price", "shares", "pnl", "reason"]
        ]
    trades_df.to_csv(os.path.join(RESULTS_DIR, "trades.csv"), index=False)

    # Metrics JSON
    with open(os.path.join(RESULTS_DIR, "metrics.json"), "w") as f:
        json.dump(metrics, f, indent=2)

    # ── Print report ─────────────────────────────────────────────────────────
    print(print_report(metrics))
    print(f"\n  Trades CSV      : {RESULTS_DIR}/trades.csv")
    print(f"  Equity CSV      : {RESULTS_DIR}/equity.csv")
    print(f"  Metrics JSON    : {RESULTS_DIR}/metrics.json")


if __name__ == "__main__":
    run_backtest()
