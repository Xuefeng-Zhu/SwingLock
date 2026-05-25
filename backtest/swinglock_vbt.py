"""
SwingLock Breakout Momentum - VectorBT v1.0.0 Backtest
LONG ONLY strategy with risk-based position sizing
"""

import numpy as np
import pandas as pd
import vectorbt as vbt
import json
import warnings
warnings.filterwarnings('ignore')

# ── Config ──────────────────────────────────────────────────────────────────
DATA_DIR   = "/home/azureuser/workspace/SwingLock/backtest/data/processed"
OUT_DIR    = "/home/azureuser/workspace/SwingLock/backtest/results"
START_IS   = "2019-01-01"
END_IS     = "2021-12-31"
START_OOS  = "2022-01-01"
END_OOS    = "2024-12-31"
INIT_CASH  = 100_000.0
RISK_PER_TRADE   = 500.0
MAX_POS_SIZE_PCT = 0.05
MAX_POSITIONS    = 5
SLIPPAGE_BPS     = 10
FEES_BPS         = 10
MAX_DAILY_GAIN   = 0.08
MAX_HOLD_DAYS    = 20

# ── Load Data ────────────────────────────────────────────────────────────────
files = {
    "AAPL":"AAPL.csv","AMZN":"AMZN.csv","GOOGL":"GOOGL.csv",
    "IWM":"IWM.csv","META":"META.csv","MSFT":"MSFT.csv",
    "NVDA":"NVDA.csv","QQQ":"QQQ.csv","SPY":"SPY.csv","TSLA":"TSLA.csv",
}
tickers = list(files.keys())

# Load all tickers into a dict
raw = {}
for ticker, fname in files.items():
    df = pd.read_csv(f"{DATA_DIR}/{fname}", parse_dates=["date"])
    df = df.dropna(subset=["high_20"])   # drop warmup rows
    df = df.set_index("date").sort_index()
    raw[ticker] = df

# Build aligned wide DataFrames (date index, ticker columns)
def build_series(key):
    return pd.DataFrame({t: raw[t][key] for t in tickers}, index=raw["SPY"].index)

close     = build_series("close")
high      = build_series("high")
low       = build_series("low")
volume    = build_series("volume")
high_20   = build_series("high_20")
low_20    = build_series("low_20")
vol_sma20 = build_series("vol_sma20")
atr14     = build_series("atr14")

# SPY and QQQ helpers
SPY_close = close["SPY"]
QQQ_close = close["QQQ"]
SPY_sma50 = SPY_close.rolling(50, min_periods=50).mean()
SPY_above = (SPY_close > SPY_sma50).reindex(close.index)
QQQ_ret20 = QQQ_close.pct_change(20).reindex(close.index)

print(f"Loaded {len(tickers)} tickers, {len(close)} rows")
print(f"Date range: {close.index[0].date()} → {close.index[-1].date()}")

# ── Build entry / exit signals ───────────────────────────────────────────────
def build_signals(c, h, l, vol, h20, l20, vs20, atr,
                  spy_above, qqq_ret, start_dt, end_dt):
    """Build entry/exit boolean DataFrames for a given period."""

    # Slice period
    mask = (c.index >= start_dt) & (c.index <= end_dt)
    c  = c.loc[mask]
    h  = h.loc[mask]
    l  = l.loc[mask]
    vol = vol.loc[mask]
    h20 = h20.loc[mask]
    l20 = l20.loc[mask]
    vs20 = vs20.loc[mask]
    atr = atr.loc[mask]
    spy_ok = spy_above.loc[mask]
    qqq_r  = qqq_ret.loc[mask]

    n = len(c)

    # Entry conditions
    cond_breakout = (c > h20)
    cond_volume   = (vol > vs20)

    # RS: stock 20d return > QQQ 20d return
    stock_ret20 = c.pct_change(20)
    # Broadcast qqq_r across columns
    cond_rs = stock_ret20.values > qqq_r.values[:, None]
    cond_rs = pd.DataFrame(cond_rs, index=c.index, columns=c.columns)

    # SPY > SMA50
    spy_ok_vals = spy_ok.values.ravel()  # 1D array (n_bars,)
    cond_spy = pd.DataFrame(
        np.tile(spy_ok_vals.reshape(-1, 1), (1, len(tickers))),
        index=c.index, columns=c.columns
    )

    # Daily gain <= 8%
    daily_gain = c.pct_change()
    cond_daily = daily_gain <= MAX_DAILY_GAIN

    # Combined entry
    entries = cond_breakout & cond_volume & cond_rs & cond_spy & cond_daily
    entries = entries.fillna(False).astype(bool)

    # Stop & target prices
    stop_base  = c - 2.0 * atr
    stop_floor = l20 * 0.98
    stop_px    = stop_base.where(stop_base < stop_floor, stop_floor)

    distance   = c - stop_px
    target_px  = c + 2.0 * distance

    # Exits
    exits_stop   = (l < stop_px).fillna(False).astype(bool)
    exits_target = (c >= target_px).fillna(False).astype(bool)

    # 20-day hold exit: we handle by recording entry bars and exiting at bar+20
    # Build time-exit mask using shift-based logic
    # Create a mask: exit when 20 bars have passed since entry
    # Efficient approach: for each bar t, if any entry occurred at t-20, exit at t
    # We approximate with a rolling count approach

    # Actually: use vectorbt's group selection with call_seq to limit max duration
    # Simpler: add a time-exit mask based on bar index difference

    # Build entry bar index per position: for each ticker, track when entry occurred
    entry_bar = pd.DataFrame(np.nan, index=c.index, columns=c.columns)

    for col in c.columns:
        bars = np.where(entries[col].values)[0]
        for bar in bars:
            entry_bar.iloc[bar, entry_bar.columns.get_loc(col)] = bar

    # For time-based exit: exit at bar = entry_bar + 20
    time_exit = pd.DataFrame(False, index=c.index, columns=c.columns, dtype=bool)
    for col in c.columns:
        bars = np.where(entries[col].values)[0]
        for bar in bars:
            exit_bar = int(bar + MAX_HOLD_DAYS)
            if exit_bar < n:
                time_exit.iloc[exit_bar, time_exit.columns.get_loc(col)] = True

    # Combined exits: stop OR target OR time
    exits = exits_stop | exits_target | time_exit
    exits = exits.fillna(False).astype(bool)

    # ── Position sizing ──────────────────────────────────────────────────────
    # size_arr = min(floor(500/dist), floor(0.05*equity/close))
    equity_approx = INIT_CASH
    risk_size = np.floor(RISK_PER_TRADE / np.maximum(distance.values, 0.001))
    cap_size  = np.floor(equity_approx * MAX_POS_SIZE_PCT / np.maximum(c.values, 0.001))
    size_arr  = np.minimum(risk_size, cap_size)
    size_df   = pd.DataFrame(size_arr, index=c.index, columns=c.columns)

    return entries, exits, size_df, stop_px, target_px, c


def run_period(close_df, high_df, low_df, volume_df,
               high_20_df, low_20_df, vol_sma20_df, atr14_df,
               spy_above, qqq_ret20,
               period_start, period_end, label):
    """Run vectorbt backtest for one period."""

    entries, exits, size_df, stop_px, target_px, close_p = build_signals(
        close_df, high_df, low_df, volume_df,
        high_20_df, low_20_df, vol_sma20_df, atr14_df,
        spy_above, qqq_ret20, period_start, period_end
    )

    n_bars = len(close_p)
    n_syms = len(tickers)

    # ── Compute equity (cash) evolution using vectorbt-like sizing ───────────
    # We pre-compute shares per entry signal and then run vectorbt portfolio

    # First pass: run with just stop + target exits
    pf1 = vbt.Portfolio.from_signals(
        close       = close_p,
        high        = high_df.loc[close_p.index],
        low         = low_df.loc[close_p.index],
        entries     = entries,
        exits       = exits,   # includes time exits
        direction   = 'longonly',
        size        = size_df.values,
        size_type   = 'value',
        fees        = FEES_BPS / 10000,
        slippage    = SLIPPAGE_BPS / 10000,
        init_cash   = INIT_CASH,
        allow_partial = True,
        raise_errors   = False,
        max_orders  = None,
    )

    return pf1, close_p, entries, exits, size_df


def compute_metrics(pf, close_p, label):
    """Compute metrics from portfolio object."""

    # Equity: use value (total portfolio value across all tickers)
    equity = pf.value()
    if equity.ndim > 1:
        equity = equity.sum(axis=1)  # sum across tickers if multi-column

    total_return = (equity.iloc[-1] / equity.iloc[0] - 1) * 100
    n_days = (equity.index[-1] - equity.index[0]).days
    cagr = ((1 + total_return/100) ** (365/max(n_days,1)) - 1) * 100

    # Drawdown
    cummax = equity.cummax()
    drawdown = (equity - cummax) / cummax * 100
    max_dd = drawdown.min()

    # Daily returns for Sharpe/Sortino
    daily_ret = equity.pct_change().dropna()
    std_daily = daily_ret.std()
    std_down  = daily_ret[daily_ret < 0].std()
    sharpe  = (daily_ret.mean() / std_daily * np.sqrt(252)) if std_daily > 0 else 0.0
    sortino = (daily_ret.mean() / std_down  * np.sqrt(252)) if std_down  > 0 else 0.0

    # Trade stats
    trades = pf.trades
    if len(trades) > 0:
        wins   = trades[trades['return'] > 0]
        losses = trades[trades['return'] <= 0]
        win_rate     = len(wins)   / len(trades) * 100
        avg_win      = wins['return'].mean()   * 100   if len(wins)   > 0 else 0.0
        avg_loss     = losses['return'].mean() * 100   if len(losses)  > 0 else 0.0
        profit_factor = abs(wins['return'].sum() / losses['return'].sum()) if losses['return'].sum() != 0 else 999.0
        avg_hold     = (trades['exit_idx'] - trades['entry_idx']).mean()
        n_trades     = len(trades)
    else:
        win_rate = avg_win = avg_loss = profit_factor = avg_hold = n_trades = 0.0

    # SPY benchmark (buy-and-hold)
    spy_c = close_p["SPY"]
    spy_equity = (spy_c / spy_c.iloc[0]) * INIT_CASH
    spy_tr = (spy_equity.iloc[-1] / INIT_CASH - 1) * 100
    spy_cagr = ((1 + spy_tr/100) ** (365/max(n_days,1)) - 1) * 100
    spy_max_dd = ((spy_equity - spy_equity.cummax()) / spy_equity.cummax() * 100).min()

    return {
        "label"        : label,
        "cagr"         : round(cagr, 2),
        "total_return" : round(total_return, 2),
        "max_drawdown" : round(max_dd, 2),
        "sharpe"       : round(sharpe, 3),
        "sortino"      : round(sortino, 3),
        "win_rate"     : round(win_rate, 1),
        "profit_factor": round(profit_factor, 2),
        "avg_win_pct"  : round(avg_win, 2),
        "avg_loss_pct" : round(avg_loss, 2),
        "n_trades"     : int(n_trades),
        "avg_hold_days": round(avg_hold, 1),
        "spy_cagr"      : round(spy_cagr, 2),
        "spy_total_return": round(spy_tr, 2),
        "spy_max_drawdown": round(spy_max_dd, 2),
    }, equity, trades


# ── Main ─────────────────────────────────────────────────────────────────────
print("\n" + "="*65)
print("  SWINGLOCK BREAKOUT MOMENTUM — VECTORBT v1.0.0 BACKTEST")
print("="*65)

results_all = {}
equity_results = {}

periods = [(START_IS, END_IS, "In_Sample"), (START_OOS, END_OOS, "Out_of_Sample")]

for period_start, period_end, label in periods:
    lbl = label.replace("_", " ")
    print(f"\n{'─'*65}")
    print(f"  {lbl}:  {period_start} → {period_end}")
    print(f"{'─'*65}")

    pf1, close_p, entries, exits, size_df = run_period(
        close, high, low, volume, high_20, low_20, vol_sma20, atr14,
        SPY_above, QQQ_ret20, period_start, period_end, label
    )

    metrics, equity, trades = compute_metrics(pf1, close_p, label)
    results_all[label] = metrics
    equity_results[label] = equity

    print(f"\n  {'Metric':<20}  {'Strategy':>12}  {'SPY B&H':>12}")
    print(f"  {'─'*44}")
    print(f"  {'CAGR':.<20}  {metrics['cagr']:>11.2f}%  {metrics['spy_cagr']:>11.2f}%")
    print(f"  {'Total Return':.<20}  {metrics['total_return']:>11.2f}%  {metrics['spy_total_return']:>11.2f}%")
    print(f"  {'Max Drawdown':.<20}  {metrics['max_drawdown']:>11.2f}%  {metrics['spy_max_drawdown']:>11.2f}%")
    print(f"  {'Sharpe Ratio':.<20}  {metrics['sharpe']:>12.3f}")
    print(f"  {'Sortino Ratio':.<20}  {metrics['sortino']:>12.3f}")
    print(f"  {'Win Rate':.<20}  {metrics['win_rate']:>11.1f}%")
    print(f"  {'Profit Factor':.<20}  {metrics['profit_factor']:>12.2f}")
    print(f"  {'Avg Win':.<20}  {metrics['avg_win_pct']:>11.2f}%")
    print(f"  {'Avg Loss':.<20}  {metrics['avg_loss_pct']:>11.2f}%")
    print(f"  {'# Trades':.<20}  {metrics['n_trades']:>12d}")
    print(f"  {'Avg Hold Days':.<20}  {metrics['avg_hold_days']:>12.1f}")

    # Save outputs
    eq_save = equity.to_frame("equity")
    eq_save.to_csv(f"{OUT_DIR}/equity_vbt_{label}.csv")

    if len(trades) > 0:
        trades_df = trades.reset_index(drop=False)
        trades_df.columns = [c if c != 'level_0' else 'bar' for c in trades_df.columns]
        trades_df.to_csv(f"{OUT_DIR}/trades_vbt_{label}.csv", index=False)

# Save metrics JSON
with open(f"{OUT_DIR}/metrics_vbt.json", "w") as f:
    json.dump(results_all, f, indent=2)

print(f"\n{'='*65}")
print(f"  OUTPUT FILES → {OUT_DIR}/")
print(f"  equity_vbt_In_Sample.csv   trades_vbt_In_Sample.csv")
print(f"  equity_vbt_Out_of_Sample.csv  trades_vbt_Out_of_Sample.csv")
print(f"  metrics_vbt.json")
print(f"{'='*65}")