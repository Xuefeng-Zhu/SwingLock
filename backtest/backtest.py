"""
backtest.py
Breakout Momentum strategy — backtest engine.
Pure Python stdlib only.
Outputs: results/trades.csv, results/equity.csv, results/summary.txt
"""
import csv
import math
import os
from datetime import datetime

# ── Project layout ──────────────────────────────────────────────────────────────
BASE  = "/home/azureuser/workspace/trading/backtest"
INDIR = f"{BASE}/data/processed"
os.makedirs(f"{BASE}/results", exist_ok=True)

TICKERS = ["IWM", "NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "TSLA"]
BENCH  = "QQQ"
INITIAL_EQUITY = 100_000.0

# ── Strategy constants (from signals.py) ────────────────────────────────────────
from scripts.signals import (
    MAX_RISK_PCT, MAX_POSITIONS, MAX_SINGLE_POS_PCT,
    HOLD_DAYS_MAX, check_entry, check_exit,
)

# ── Rolling helpers (mirrors indicators.py) ────────────────────────────────────
def _rolling_sma(values: list, n: int) -> list:
    out = []
    for i in range(len(values)):
        if i < n - 1:
            out.append(None)
        else:
            out.append(sum(values[i - n + 1 : i + 1]) / n)
    return out

def _rolling_max(values: list, n: int) -> list:
    out = []
    for i in range(len(values)):
        if i < n - 1:
            out.append(None)
        else:
            out.append(max(values[i - n + 1 : i + 1]))
    return out

def _lag(values: list, n: int = 1) -> list:
    """Shift list right by n: prepends None, drops last n elements."""
    if n >= len(values):
        return [None] * len(values)
    return [None] * n + values[: -n]

# ── Data loading ────────────────────────────────────────────────────────────────
def load_ticker(ticker: str) -> list[dict]:
    rows = []
    with open(f"{INDIR}/{ticker}.csv") as f:
        for r in csv.DictReader(f):
            r["close"]    = float(r["close"])
            r["open"]     = float(r["open"])
            r["high"]     = float(r["high"])
            r["low"]      = float(r["low"])
            r["volume"]   = int(r["volume"])
            r["high_20"]  = float(r["high_20"])  if r.get("high_20")  and r["high_20"]  != "" else None
            r["low_20"]   = float(r["low_20"])   if r.get("low_20")   and r["low_20"]   != "" else None
            r["vol_sma20"] = float(r["vol_sma20"]) if r.get("vol_sma20") and r["vol_sma20"] != "" else None
            r["atr14"]    = float(r["atr14"])    if r.get("atr14")    and r["atr14"]    != "" else None
            rows.append(r)
    return rows


def enrich_with_lagged_indicators(rows: list) -> list:
    """
    Add properly-lagged (non-look-ahead) indicators to each row.

    The processed CSV stores rolling_max(highs, 20) WHICH INCLUDES today.
    For entry we need yesterday's 20-day high — i.e. the 20d high as of the
    close of the prior trading day.  We achieve this by lagging the stored
    high_20, vol_sma20, and atr14 by 1 row.

    Also adds prev_close and close_20d_ago.
    """
    closes  = [r["close"]  for r in rows]
    highs   = [r["high"]   for r in rows]
    lows    = [r["low"]    for r in rows]
    volumes = [r["volume"] for r in rows]

    # Stored (look-ahead) indicators
    high_20    = _rolling_max(highs, 20)
    low_20     = _rolling_max(lows, 20)    # low_20 unused in signals but keep
    vol_sma20  = _rolling_sma(volumes, 20)

    # ATR14 (computed with Wilder smoothing — same as indicators.py)
    def _true_range(h, l, prev):
        return max(h - l, abs(h - prev), abs(l - prev))

    trs = []
    for i, r in enumerate(rows):
        prev = float(rows[i - 1]["close"]) if i > 0 else float(r["close"])
        trs.append(_true_range(float(r["high"]), float(r["low"]), prev))

    atr14 = [None] * len(trs)
    period = 14
    if len(trs) >= period:
        sma = sum(trs[:period]) / period
        atr14[period - 1] = sma
        for i in range(period, len(trs)):
            sma = (sma * (period - 1) + trs[i]) / period
            atr14[i] = sma

    # Lag by 1 to prevent look-ahead bias:
    # high_20_lagged[i] = yesterday's 20-day rolling max = high_20[i-1]
    lag_high_20   = _lag(high_20, 1)
    lag_vol_sma20 = _lag(vol_sma20, 1)
    lag_atr14     = _lag(atr14, 1)

    out = []
    for i, r in enumerate(rows):
        r2 = dict(r)
        r2["high_20"]    = round(lag_high_20[i], 4)   if lag_high_20[i]   is not None else None
        r2["low_20"]     = r.get("low_20")                       # not used in signals
        r2["vol_sma20"]  = round(lag_vol_sma20[i], 2) if lag_vol_sma20[i] is not None else None
        r2["atr14"]      = round(lag_atr14[i], 4)     if lag_atr14[i]     is not None else None
        r2["prev_close"] = closes[i - 1] if i > 0 else closes[i]
        r2["close_20d_ago"] = closes[i - 20] if i >= 20 else None
        out.append(r2)
    return out


# ── Market-regime maps ───────────────────────────────────────────────────────────
def compute_spy_sma50_map(spy_rows: list[dict]) -> dict[str, float]:
    closes = [r["close"] for r in spy_rows]
    sma50  = _rolling_sma(closes, 50)
    return {spy_rows[i]["date"]: sma50[i] for i in range(len(spy_rows)) if sma50[i] is not None}


def compute_qqq_20d_return_map(qqq_rows: list[dict]) -> dict[str, float]:
    """Return {date: qqq_20d_return} for each date where it's computable."""
    result = {}
    for i, r in enumerate(qqq_rows):
        if i >= 20:
            prev = qqq_rows[i - 20]["close"]
            curr = r["close"]
            result[r["date"]] = (curr - prev) / prev if prev > 0 else 0.0
    return result


# ── Backtest core ───────────────────────────────────────────────────────────────
def run_backtest():
    # ── Load raw processed data ────────────────────────────────────────────────
    print("Loading data ...")
    spy_rows  = load_ticker("SPY")
    qqq_rows  = load_ticker(BENCH)
    ticker_rows = {t: load_ticker(t) for t in TICKERS}
    print(f"  SPY: {len(spy_rows)} rows  |  QQQ: {len(qqq_rows)} rows")
    for t, rows in ticker_rows.items():
        print(f"  {t}: {len(rows)} rows")

    # ── Enrich stock bars with properly-lagged indicators ───────────────────────
    ticker_enriched = {}
    for t, rows in ticker_rows.items():
        ticker_enriched[t] = enrich_with_lagged_indicators(rows)
        n_valid = sum(1 for r in ticker_enriched[t] if r["high_20"] is not None)
        print(f"  {t}: {n_valid} rows with lagged high_20")

    # ── Build date maps ────────────────────────────────────────────────────────
    def date_map(rows):  return {r["date"]: r for r in rows}

    spy_date_map   = date_map(spy_rows)
    qqq_date_map   = date_map(qqq_rows)
    stock_date_map = {t: date_map(rows) for t, rows in ticker_enriched.items()}

    # ── Regime maps ────────────────────────────────────────────────────────────
    spy_sma50_map    = compute_spy_sma50_map(spy_rows)
    qqq_20d_ret_map  = compute_qqq_20d_return_map(qqq_rows)
    spy_close_map    = {r["date"]: r["close"] for r in spy_rows}
    qqq_close_map    = {r["date"]: r["close"] for r in qqq_rows}
    # QQQ close 20 days ago
    qqq_close_20d_ago_map = {qqq_rows[i]["date"]: qqq_rows[i - 20]["close"] if i >= 20 else None
                              for i, r in enumerate(qqq_rows)}

    # ── Trading dates: from first day SPY has sma50 through last date ──────────
    first_trade_date = sorted(spy_sma50_map.keys())[0]
    last_date        = max(r["date"] for rows in [spy_rows, qqq_rows] + list(ticker_enriched.values()) for r in rows)
    all_dates = sorted(set(
        r["date"] for rows in [spy_rows, qqq_rows] + list(ticker_enriched.values()) for r in rows
        if r["date"] >= first_trade_date
    ))
    print(f"\nBacktest window: {all_dates[0]} → {all_dates[-1]}  ({len(all_dates)} trading days)\n")

    # ── Backtest state ─────────────────────────────────────────────────────────
    equity       = INITIAL_EQUITY
    cash         = equity
    open_trades  = []    # {ticker, entry_date, entry_price, stop_price, target_price, shares, atr14, day_count}
    closed_trades = []
    equity_curve  = []
    trade_id      = 1

    print("Running backtest ...")
    for date in all_dates:
        # ── Market regime for today ─────────────────────────────────────────────
        spy_sma50         = spy_sma50_map.get(date)
        spy_close_today   = spy_close_map.get(date)
        qqq_close_today   = qqq_close_map.get(date)
        qqq_20d_ago_price = qqq_close_20d_ago_map.get(date)
        qqq_20d_ret       = qqq_20d_ret_map.get(date)

        # ── Exit check (before scanning for new entries) ────────────────────────
        still_open = []
        for trade in open_trades:
            ticker = trade["ticker"]
            bar    = stock_date_map[ticker].get(date)
            if bar is None:
                still_open.append(trade)
                continue

            day_count = trade.get("day_count", 0) + 1
            should_exit, reason, exit_price = check_exit(trade, bar, day_count)

            if should_exit:
                shares    = trade["shares"]
                pnl       = (exit_price - trade["entry_price"]) * shares
                equity   += pnl
                r_mult    = (exit_price - trade["entry_price"]) / (trade["entry_price"] - trade["stop_price"]) \
                            if (trade["entry_price"] - trade["stop_price"]) > 0 else 0.0
                closed_trades.append({
                    "trade_id":    trade["trade_id"],
                    "ticker":      ticker,
                    "entry_date":  trade["entry_date"],
                    "exit_date":   date,
                    "days_held":   day_count,
                    "shares":      shares,
                    "entry_price": trade["entry_price"],
                    "exit_price":  exit_price,
                    "stop_price":  trade["stop_price"],
                    "target_price": trade["target_price"],
                    "atr14":       trade["atr14"],
                    "pnl":         round(pnl, 2),
                    "pnl_pct":     round(pnl / equity * 100, 4) if equity > 0 else 0,
                    "r_multiple":  round(r_mult, 2),
                    "exit_reason": reason,
                })
                equity_curve.append({"date": date, "equity": round(equity, 2)})
            else:
                trade["day_count"] = day_count
                still_open.append(trade)

        open_trades = still_open

        # ── New entry scan ─────────────────────────────────────────────────────
        if len(open_trades) < MAX_POSITIONS:
            for ticker in TICKERS:
                if len(open_trades) >= MAX_POSITIONS:
                    break
                if any(t["ticker"] == ticker for t in open_trades):
                    continue

                bar = stock_date_map[ticker].get(date)
                if bar is None:
                    continue

                # Inject market context into bar for this tick
                bar["spy_close"]     = spy_close_today
                bar["qqq_close"]     = qqq_close_today
                bar["qqq_20d_ret"]   = qqq_20d_ret

                signal = check_entry(
                    ticker,
                    bar,
                    spy_sma50,
                    qqq_20d_ago_price,
                    earnings_dates=set(),
                )
                if signal is None:
                    continue

                # Risk-based position sizing
                risk_amount = equity * MAX_RISK_PCT
                stop_dist   = signal["distance"]
                shares      = int(risk_amount / stop_dist) if stop_dist > 0 else 0
                max_shares  = int((equity * MAX_SINGLE_POS_PCT) / bar["close"])
                shares      = min(shares, max_shares)
                if shares <= 0:
                    continue

                cost = shares * bar["close"]
                if cost > cash:
                    shares = int(cash / bar["close"])
                if shares <= 0:
                    continue

                open_trades.append({
                    "trade_id":     trade_id,
                    "ticker":       ticker,
                    "entry_date":   date,
                    "entry_price":  bar["close"],
                    "stop_price":   signal["stop_price"],
                    "target_price": signal["target_price"],
                    "atr14":        signal["atr14"],
                    "shares":       shares,
                    "day_count":    0,
                })
                cash    -= shares * bar["close"]
                trade_id += 1

        # ── EOD equity record ──────────────────────────────────────────────────
        if not any(e["date"] == date for e in equity_curve):
            equity_curve.append({"date": date, "equity": round(equity, 2)})

    # ── Flush any positions still open at end of dataset ─────────────────────
    last_date = all_dates[-1]
    for trade in open_trades:
        ticker   = trade["ticker"]
        bar      = stock_date_map[ticker].get(last_date)
        if bar is None:
            bar = stock_date_map[ticker][list(stock_date_map[ticker].keys())[-1]]
        day_count  = trade.get("day_count", 0)
        exit_price = bar["close"]
        shares     = trade["shares"]
        pnl        = (exit_price - trade["entry_price"]) * shares
        equity    += pnl
        closed_trades.append({
            "trade_id":     trade["trade_id"],
            "ticker":       ticker,
            "entry_date":   trade["entry_date"],
            "exit_date":    last_date,
            "days_held":    day_count,
            "shares":       shares,
            "entry_price":  trade["entry_price"],
            "exit_price":   exit_price,
            "stop_price":   trade["stop_price"],
            "target_price": trade["target_price"],
            "atr14":        trade["atr14"],
            "pnl":          round(pnl, 2),
            "pnl_pct":      round(pnl / equity * 100, 4) if equity > 0 else 0,
            "r_multiple":   0.0,
            "exit_reason":  "eof",
        })

    print(f"Backtest complete.  {len(closed_trades)} trades closed.")

    return closed_trades, equity_curve, all_dates


# ── Metrics ────────────────────────────────────────────────────────────────────
def compute_metrics(trades, equity_curve) -> dict:
    if not trades:
        return {}

    winning = [t for t in trades if t["pnl"] > 0]
    losing  = [t for t in trades if t["pnl"] <= 0]

    equity_end = equity_curve[-1]["equity"] if equity_curve else INITIAL_EQUITY
    total_ret  = equity_end - INITIAL_EQUITY
    total_ret_pct = total_ret / INITIAL_EQUITY * 100

    # Drawdown
    peak, mdd_dollar = INITIAL_EQUITY, 0.0
    for row in equity_curve:
        if row["equity"] > peak:
            peak = row["equity"]
        dd = peak - row["equity"]
        if dd > mdd_dollar:
            mdd_dollar = dd
    mdd_pct = mdd_dollar / peak * 100 if peak > 0 else 0.0

    # Sharpe (daily returns)
    daily_rets = []
    for i in range(1, len(equity_curve)):
        prev = equity_curve[i - 1]["equity"]
        curr = equity_curve[i]["equity"]
        if prev > 0:
            daily_rets.append((curr - prev) / prev)

    if daily_rets and len(daily_rets) > 1:
        mean_r = sum(daily_rets) / len(daily_rets)
        std_r  = math.sqrt(sum((r - mean_r) ** 2 for r in daily_rets) / (len(daily_rets) - 1))
        sharpe = (mean_r / std_r * math.sqrt(252)) if std_r > 0 else 0.0
    else:
        sharpe = 0.0

    gross_win  = sum(t["pnl"] for t in winning)
    gross_loss = abs(sum(t["pnl"] for t in losing))
    prof_fac   = gross_win / gross_loss if gross_loss > 0 else float("inf") if gross_win > 0 else 0.0

    return {
        "start_equity":       INITIAL_EQUITY,
        "end_equity":         round(equity_end, 2),
        "total_return_pct":  round(total_ret_pct, 2),
        "total_return_dollar": round(total_ret, 2),
        "num_trades":        len(trades),
        "win_rate":          round(len(winning) / len(trades) * 100, 2),
        "avg_win":           round(gross_win / len(winning), 2) if winning else 0.0,
        "avg_loss":          round(gross_loss / len(losing), 2) if losing else 0.0,
        "max_drawdown_pct":  round(mdd_pct, 2),
        "max_drawdown_dollar": round(mdd_dollar, 2),
        "avg_hold_days":     round(sum(t["days_held"] for t in trades) / len(trades), 2),
        "profit_factor":    round(prof_fac, 3),
        "sharpe_ratio":      round(sharpe, 3),
    }


# ── Output writers ──────────────────────────────────────────────────────────────
def save_results(trades, equity_curve, metrics):
    # trades.csv
    tpath = f"{BASE}/results/trades.csv"
    tfields = ["trade_id","ticker","entry_date","exit_date","days_held","shares",
               "entry_price","exit_price","stop_price","target_price","atr14",
               "pnl","pnl_pct","r_multiple","exit_reason"]
    with open(tpath, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=tfields, extrasaction="ignore")
        w.writeheader()
        w.writerows(trades)
    print(f"  Saved {tpath}  ({len(trades)} trades)")

    # equity.csv
    epath = f"{BASE}/results/equity.csv"
    efields = ["date", "equity"]
    with open(epath, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=efields)
        w.writeheader()
        w.writerows(equity_curve)
    print(f"  Saved {epath}  ({len(equity_curve)} rows)")

    # summary.txt
    spath = f"{BASE}/results/summary.txt"
    with open(spath, "w") as f:
        f.write("=" * 60 + "\n")
        f.write("BACKTEST RESULTS — Breakout / Momentum Strategy\n")
        f.write("=" * 60 + "\n\n")
        if metrics:
            f.write(f"Start Equity         : ${metrics['start_equity']:>14,.2f}\n")
            f.write(f"End Equity           : ${metrics['end_equity']:>14,.2f}\n")
            f.write(f"Total Return        :  {metrics['total_return_pct']:>11,.2f} %\n")
            f.write(f"Total Return ($)    : ${metrics['total_return_dollar']:>14,.2f}\n")
            f.write(f"Sharpe Ratio        :  {metrics['sharpe_ratio']:>11,.3f}\n")
            f.write(f"Max Drawdown        :  {metrics['max_drawdown_pct']:>11,.2f} %\n")
            f.write(f"Max Drawdown ($)    : ${metrics['max_drawdown_dollar']:>14,.2f}\n")
            f.write(f"Profit Factor       :  {metrics['profit_factor']:>11,.3f}\n")
            f.write(f"\n--- Trade Statistics -----------------------------------------\n")
            f.write(f"# Closed Trades     :  {metrics['num_trades']:>11}\n")
            f.write(f"Win Rate            :  {metrics['win_rate']:>11,.2f} %\n")
            f.write(f"Avg Win             : ${metrics['avg_win']:>14,.2f}\n")
            f.write(f"Avg Loss            : ${metrics['avg_loss']:>14,.2f}\n")
            f.write(f"Avg Hold Days       :  {metrics['avg_hold_days']:>11,.2f}\n")
        else:
            f.write("No trades were taken during the backtest period.\n")
    print(f"  Saved {spath}")


# ── Entry point ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    trades, equity_curve, all_dates = run_backtest()
    metrics = compute_metrics(trades, equity_curve)
    save_results(trades, equity_curve, metrics)

    print("\n" + "=" * 60)
    print("BACKTEST SUMMARY")
    print("=" * 60)
    if metrics:
        for k, v in metrics.items():
            print(f"  {k:<26}: {v}")
    else:
        print("  No trades generated.")