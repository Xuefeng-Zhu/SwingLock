"""
run_backtest.py
Orchestrate the full backtest: load data, run strategy, compute metrics, print report.
Stdlib only.
"""
import csv
import os
import math
from datetime import datetime
from typing import List, Dict, Optional

# ── Import project modules ──────────────────────────────────────────────────────
import sys
sys.path.insert(0, os.path.dirname(__file__))

from indicators import compute_spy_sma50
from signals import check_entry, check_exit, HOLD_DAYS_MAX
from report import compute_metrics, print_report

# ── Strategy constants ─────────────────────────────────────────────────────────
TICKERS        = ["SPY", "QQQ", "IWM", "NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "TSLA"]
DATA_DIR       = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "processed")
RESULTS_DIR    = os.path.join(os.path.dirname(os.path.dirname(__file__)), "results")
STARTING_CAPITAL = 100_000.0
MAX_POSITIONS    = 5

os.makedirs(RESULTS_DIR, exist_ok=True)


# ── Data loading helpers ───────────────────────────────────────────────────────

def load_ticker_csv(ticker: str) -> List[Dict]:
    path = os.path.join(DATA_DIR, f"{ticker}.csv")
    rows = []
    with open(path) as f:
        for r in csv.DictReader(f):
            r["close"]  = float(r["close"])
            r["open"]   = float(r["open"])
            r["high"]   = float(r["high"])
            r["low"]    = float(r["low"])
            r["volume"] = int(r["volume"])
            for col in ("high_20", "low_20", "vol_sma20", "atr14"):
                val = r.get(col, "")
                r[col] = float(val) if val not in ("", "None", None) else None
            rows.append(r)
    return rows


def load_all_tickers() -> Dict[str, List[Dict]]:
    return {t: load_ticker_csv(t) for t in TICKERS}


# ── Benchmark (SPY) total return ───────────────────────────────────────────────

def benchmark_return(starting_capital: float) -> float:
    spy = load_ticker_csv("SPY")
    if len(spy) < 2:
        return 0.0
    first_close = spy[0]["close"]
    last_close  = spy[-1]["close"]
    return (last_close - first_close) / first_close


# ── Core backtest loop ────────────────────────────────────────────────────────

def run_backtest():
    all_tickers_data = load_all_tickers()
    tickers = list(all_tickers_data.keys())

    # ── Pre-compute SPY SMA50 ─────────────────────────────────────────────────
    spy_sma50 = compute_spy_sma50(DATA_DIR)

    # ── Align all tickers on common dates ─────────────────────────────────────
    # Find intersection of all date ranges
    date_sets = []
    for ticker, rows in all_tickers_data.items():
        date_sets.append(set(r["date"] for r in rows))
    common_dates = set.intersection(*date_sets) if date_sets else set()
    all_dates = sorted(common_dates)
    print(f"[INFO] {len(all_dates)} common trading days found.")

    # Build lookup: ticker -> {date: row}
    lookup = {}
    for ticker, rows in all_tickers_data.items():
        lookup[ticker] = {r["date"]: r for r in rows}

    # ── Build QQQ close-20d-ago lookup ─────────────────────────────────────────
    qqq_rows = all_tickers_data.get("QQQ", [])
    qqq_by_date = {r["date"]: r for r in qqq_rows}
    qqq_closes_20d = {}
    for i, r in enumerate(qqq_rows):
        if i >= 20:
            qqq_closes_20d[r["date"]] = qqq_rows[i - 20]["close"]

    # SPY close lookup
    spy_rows = all_tickers_data.get("SPY", [])
    spy_by_date = {r["date"]: r for r in spy_rows}

    # ── Backtest state ─────────────────────────────────────────────────────────
    equity      = STARTING_CAPITAL
    equity_curve = [equity]
    dates_curve  = [all_dates[0] if all_dates else ""]

    cash    = equity
    positions = {}   # ticker -> {shares, entry_price, stop_price, target_price,
                     #           entry_date, atr14, day_count}
    closed_trades = []

    # ── Open trade tracking ────────────────────────────────────────────────────
    for date in all_dates[1:]:   # skip first date (no signals until day 21)
        # ── Current bar for each ticker ───────────────────────────────────────
        spy_close_today = spy_by_date.get(date, {}).get("close", 0)
        spy_sma50_today = spy_sma50.get(date, None)

        # ── Evaluate open positions ───────────────────────────────────────────
        to_close = []
        for ticker, pos in positions.items():
            bar = lookup[ticker].get(date)
            if not bar:
                continue
            pos["day_count"] = pos.get("day_count", 0) + 1

            should_exit, reason, exit_price = check_exit(pos, bar, pos["day_count"])

            if should_exit:
                pnl = (exit_price - pos["entry_price"]) * pos["shares"]
                equity += pnl
                cash   += pnl
                closed_trades.append({
                    "ticker":      ticker,
                    "entry_date":  pos["entry_date"],
                    "exit_date":   date,
                    "entry_price": pos["entry_price"],
                    "exit_price":  exit_price,
                    "shares":      pos["shares"],
                    "pnl":         round(pnl, 2),
                    "reason":      reason,
                    "atr14":       pos.get("atr14", 0),
                    "return_pct":  round((exit_price - pos["entry_price"]) / pos["entry_price"], 4),
                })
                to_close.append(ticker)

        for ticker in to_close:
            del positions[ticker]

        # ── Entry signals ─────────────────────────────────────────────────────
        if len(positions) < MAX_POSITIONS:
            # price at least 20 days in data
            ticker_rows = {t: all_tickers_data[t] for t in tickers if t not in positions}
            for ticker in tickers:
                if ticker in positions or len(positions) >= MAX_POSITIONS:
                    break
                bar = lookup[ticker].get(date)
                if not bar:
                    continue
                # skip if not enough history for indicator
                if bar.get("high_20") is None or bar.get("vol_sma20") is None:
                    continue

                # build extended bar with QQQ and SPY context
                qqq_close_today = qqq_by_date.get(date, {}).get("close", 0)
                qqq_20d_ago     = qqq_closes_20d.get(date, 0)

                # close_20d_ago for stock
                stock_rows = all_tickers_data[ticker]
                bar_idx = next((i for i, r in enumerate(stock_rows) if r["date"] == date), None)
                close_20d_ago = stock_rows[bar_idx - 20]["close"] if bar_idx is not None and bar_idx >= 20 else 0

                extended_bar = dict(bar)
                extended_bar["qqq_close"]       = qqq_close_today
                extended_bar["qqq_close_20d_ago"] = qqq_20d_ago
                extended_bar["spy_close"]      = spy_close_today
                extended_bar["close_20d_ago"]  = close_20d_ago

                # ── LAG INDICATORS BY 1 DAY ─────────────────────────────────────
                # The CSV stores high_20[i] = max(highs[0..i]) — includes today.
                # Using today to enter today is lookahead bias.
                # For a signal at close on date i, yesterday's 20d high/low (i-1)
                # is the confirmed breakout threshold.
                bar_idx = next((i for i, r in enumerate(stock_rows) if r["date"] == date), None)
                if bar_idx is not None and bar_idx >= 1:
                    prev_row = stock_rows[bar_idx - 1]
                    extended_bar["high_20"] = prev_row.get("high_20") if prev_row.get("high_20") is not None else bar.get("high_20")
                    extended_bar["low_20"]  = prev_row.get("low_20")  if prev_row.get("low_20")  is not None else bar.get("low_20")
                # Also carry forward prev_close for the overextended filter
                extended_bar["prev_close"] = bar.get("prev_close") or (stock_rows[bar_idx - 1]["close"] if bar_idx and bar_idx >= 1 else bar["close"])

                sig = check_entry(ticker, extended_bar, spy_sma50_today,
                                  qqq_20d_ago, set())
                if sig:
                    # position sizing: risk = min(0.5% equity, 1.5*ATR-based stop)
                    risk_per_trade = equity * 0.005
                    atr14  = sig["atr14"]
                    stop   = sig["stop_price"]
                    dist   = sig["distance"]   # entry - stop

                    if dist <= 0:
                        continue

                    # shares = risk / dist  (capped at 5% of equity)
                    max_shares_by_cap = int(equity * 0.05 / bar["close"])
                    shares_by_risk    = int(risk_per_trade / dist)
                    shares = min(max_shares_by_cap, shares_by_risk, 500)  # reasonable cap

                    if shares < 1:
                        continue

                    cost = shares * bar["close"]
                    if cost > cash:
                        shares = int(cash / bar["close"])

                    positions[ticker] = {
                        "shares":      shares,
                        "entry_price": bar["close"],
                        "stop_price":  sig["stop_price"],
                        "target_price": sig["target_price"],
                        "entry_date":  date,
                        "atr14":       atr14,
                        "day_count":   0,
                        "reason":      sig["reason"],
                    }
                    cash -= shares * bar["close"]

        # ── Record daily equity (end-of-day, AFTER all processing) ──────────────
        # equity = cash (realized P&L only) + Σ unrealized P&L on open positions
        # unrealized = (current_close - entry_price) × shares
        # This avoids double-counting entry costs that are already deducted from cash
        pos_value = sum(
            (lookup[t].get(date, {}).get("close", pos["entry_price"]) - pos["entry_price"])
            * pos["shares"]
            for t, pos in positions.items()
        )
        equity = cash + pos_value
        equity_curve.append(equity)
        dates_curve.append(date)

    # ── Close any remaining positions at last close ────────────────────────────
    last_date = all_dates[-1] if all_dates else ""
    for ticker, pos in list(positions.items()):
        bar = lookup[ticker].get(last_date) or lookup[ticker].get(date)
        if bar:
            exit_price = bar["close"]
        else:
            exit_price = pos["entry_price"]
        pnl = (exit_price - pos["entry_price"]) * pos["shares"]
        equity += pnl
        cash   += pnl
        closed_trades.append({
            "ticker":      ticker,
            "entry_date":  pos["entry_date"],
            "exit_date":   last_date,
            "entry_price": pos["entry_price"],
            "exit_price":  exit_price,
            "shares":      pos["shares"],
            "pnl":         round(pnl, 2),
            "reason":      "eod_close",
            "atr14":       pos.get("atr14", 0),
            "return_pct":  round((exit_price - pos["entry_price"]) / pos["entry_price"], 4),
        })
    positions.clear()

    return equity_curve, dates_curve, closed_trades


# ── Save CSVs ─────────────────────────────────────────────────────────────────

def save_results(equity_curve, dates_curve, trades):
    eq_path = os.path.join(RESULTS_DIR, "equity.csv")
    with open(eq_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "equity"])
        for d, e in zip(dates_curve, equity_curve):
            w.writerow([d, round(e, 2)])
    print(f"[OK] equity.csv saved  ({len(equity_curve)} rows)")

    tr_path = os.path.join(RESULTS_DIR, "trades.csv")
    fieldnames = ["ticker", "entry_date", "exit_date", "entry_price", "exit_price",
                  "shares", "pnl", "reason", "return_pct", "atr14"]
    with open(tr_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(trades)
    print(f"[OK] trades.csv saved  ({len(trades)} trades)")


# ── Main ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  BREAKOUT / MOMENTUM STRATEGY — BACKTEST")
    print("=" * 60)
    print(f"  Starting capital : ${STARTING_CAPITAL:,.0f}")
    print(f"  Results dir      : {RESULTS_DIR}")
    print()

    bm_return = benchmark_return(STARTING_CAPITAL)
    print(f"[INFO] SPY benchmark total return: {bm_return*100:+.2f}%")
    print()

    equity_curve, dates_curve, trades = run_backtest()

    # Update metrics with dates
    metrics = compute_metrics(equity_curve, trades, STARTING_CAPITAL, bm_return)
    if dates_curve:
        metrics["start_date"] = dates_curve[0]
        metrics["end_date"]   = dates_curve[-1]

    save_results(equity_curve, dates_curve, trades)

    print()
    print(print_report(metrics))

    # Save metrics JSON
    import json
    metrics_path = os.path.join(RESULTS_DIR, "metrics.json")
    with open(metrics_path, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"\n[OK] metrics.json saved")