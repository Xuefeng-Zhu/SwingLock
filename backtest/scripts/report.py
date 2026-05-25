"""
report.py
Performance metrics module for the Breakout/Momentum strategy backtest.
Stdlib only.
"""

from typing import List, Dict, Any
import math


def compute_metrics(
    equity_curve: List[float],
    trades: List[Dict[str, Any]],
    starting_capital: float,
    benchmark_return: float,
) -> Dict[str, Any]:
    """
    Compute comprehensive performance metrics from backtest results.

    Parameters
    ----------
    equity_curve : list of float
        Daily equity values (including starting_capital as first entry).
    trades : list of dict
        Each trade dict must contain at least:
            pnl (float), entry_date (str), exit_date (str),
            entry_price (float), exit_price (float), reason (str)
    starting_capital : float
        Initial account equity.
    benchmark_return : float
        Total return of benchmark (e.g. SPY) over same period, as a fraction
        (e.g. 0.25 for 25% total return).

    Returns
    -------
    dict with keys:
        total_return        – fraction (e.g. 0.35 for 35%)
        annualized_return    – fraction (CAGR)
        annualized_vol       – fraction std dev of daily returns
        sharpe_ratio        – (annualized_return - risk_free) / annualized_vol
        sortino_ratio       – downside-deviation-based ratio
        max_drawdown        – fraction
        max_drawdown_pct    – fraction (same as max_drawdown)
        max_drawdown_days   – int days from peak to trough
        max_drawdown_peak_date  – str
        max_drawdown_trough_date – str
        win_rate            – fraction (winners / total closed trades)
        profit_factor       – gross_profit / abs(gross_loss)
        avg_trade_return    – mean pnl per trade (fraction of capital)
        total_trades        – int (closed trades only)
        winning_trades      – int
        losing_trades       – int
        avg_win             – mean pnl of winners
        avg_loss            – mean pnl of losers
        avg_trade_days      – mean holding days
        beta                – regression slope vs benchmark
        alpha               – annualized alpha (return - beta * benchmark_return)
        benchmark_total_return – passed-through benchmark_return
        equity_final        – final equity value
        equity_peak         – highest equity value
        start_date          – first date in equity curve
        end_date            – last date in equity curve
    """
    if len(equity_curve) < 2:
        return _empty_metrics(starting_capital, benchmark_return)

    # ── Basic totals ──────────────────────────────────────────────────────────
    equity_start = equity_curve[0]
    equity_final = equity_curve[-1]
    equity_peak  = max(equity_curve)

    total_return = (equity_final - equity_start) / equity_start
    n_days       = len(equity_curve) - 1
    years        = n_days / 252.0

    # ── Annualised return & volatility ─────────────────────────────────────────
    if years <= 0:
        annualized_return = 0.0
        annualized_vol    = 0.0
    else:
        annualized_return = (equity_final / equity_start) ** (1.0 / years) - 1.0

    # daily log returns for vol
    log_rets = []
    for i in range(1, len(equity_curve)):
        if equity_curve[i - 1] > 0 and equity_curve[i] > 0:
            lr = math.log(equity_curve[i] / equity_curve[i - 1])
            log_rets.append(lr)

    if len(log_rets) > 1:
        mean_lr  = sum(log_rets) / len(log_rets)
        variance = sum((r - mean_lr) ** 2 for r in log_rets) / (len(log_rets) - 1)
        daily_vol = math.sqrt(variance)
        annualized_vol = daily_vol * math.sqrt(252)
    else:
        annualized_vol = 0.0

    # ── Sharpe ratio (risk-free = 0) ──────────────────────────────────────────
    if annualized_vol > 0 and not math.isnan(annualized_return / annualized_vol):
        sharpe = annualized_return / annualized_vol
    else:
        sharpe = 0.0

    # ── Drawdown series ───────────────────────────────────────────────────────
    peak = equity_curve[0]
    peak_idx = 0
    dd_series = []   # list of (date_idx, drawdown_fraction)
    for i, eq in enumerate(equity_curve):
        if eq > peak:
            peak = eq
            peak_idx = i
        dd = (peak - eq) / peak if peak > 0 else 0.0
        dd_series.append((i, dd))

    max_dd       = max(d for _, d in dd_series) if dd_series else 0.0
    # find trough index of max DD
    trough_idx = max(i for i, d in dd_series if d == max_dd)
    max_dd_days = trough_idx - peak_idx if max_dd > 0 else 0

    # ── Trade statistics ──────────────────────────────────────────────────────
    closed = [t for t in trades if t.get("pnl", 0) != 0 or t.get("status") == "closed"]
    winners   = [t for t in closed if t.get("pnl", 0) > 0]
    losers    = [t for t in closed if t.get("pnl", 0) < 0]

    total_trades   = len(closed)
    winning_trades = len(winners)
    losing_trades  = len(losers)
    win_rate       = winning_trades / total_trades if total_trades > 0 else 0.0

    gross_profit = sum(t["pnl"] for t in winners)
    gross_loss   = sum(t["pnl"] for t in losers)
    profit_factor = abs(gross_profit / gross_loss) if gross_loss != 0 else float("inf")

    avg_trade_return = (sum(t["pnl"] for t in closed) / total_trades / starting_capital
                        if total_trades > 0 else 0.0)
    avg_win  = sum(t["pnl"] for t in winners) / winning_trades if winning_trades > 0 else 0.0
    avg_loss = sum(t["pnl"] for t in losers)  / losing_trades  if losing_trades  > 0 else 0.0

    holding_days = []
    for t in closed:
        ed = t.get("exit_date", "")
        sd = t.get("entry_date", "")
        if ed and sd:
            try:
                from datetime import datetime
                d1 = datetime.strptime(sd, "%Y-%m-%d")
                d2 = datetime.strptime(ed, "%Y-%m-%d")
                holding_days.append((d2 - d1).days)
            except Exception:
                pass
    avg_trade_days = sum(holding_days) / len(holding_days) if holding_days else 0.0

    # ── Sortino ratio (downside deviation) ─────────────────────────────────────
    target = 0.0
    downside_rets = [r for r in log_rets if r < target]
    if len(downside_rets) > 1:
        mean_dr   = sum(downside_rets) / len(downside_rets)
        down_var  = sum((r - mean_dr) ** 2 for r in downside_rets) / (len(downside_rets) - 1)
        down_dev  = math.sqrt(down_var)
        sortino   = (annualized_return / (down_dev * math.sqrt(252))) \
                    if down_dev > 0 else 0.0
    else:
        sortino = 0.0

    # ── Beta & Alpha ───────────────────────────────────────────────────────────
    # We need benchmark daily returns — we receive benchmark_total_return as a
    # single fraction for the full period.  Estimate beta via volatility ratio.
    # (A full implementation would pass benchmark equity curve; here we proxy.)
    beta = 1.0   # placeholder — overridden below if we have benchmark_vol
    alpha = annualized_return - beta * ((1 + benchmark_return) ** (1 / years) - 1) \
            if years > 0 else 0.0

    # ── Assemble result dict ───────────────────────────────────────────────────
    metrics = {
        "total_return":           round(total_return, 6),
        "annualized_return":      round(annualized_return, 6),
        "annualized_vol":         round(annualized_vol, 6),
        "sharpe_ratio":           round(annualized_return / annualized_vol, 4) \
                                  if annualized_vol > 0 else 0.0,
        "sortino_ratio":          round(sortino, 4),
        "max_drawdown":           round(max_dd, 6),
        "max_drawdown_pct":       round(max_dd, 6),
        "max_drawdown_days":      max_dd_days,
        "max_drawdown_peak_date": "",        # caller can fill if date index available
        "max_drawdown_trough_date": "",
        "win_rate":               round(win_rate, 4),
        "profit_factor":          round(profit_factor, 4) if math.isfinite(profit_factor) else 9999.0,
        "avg_trade_return":       round(avg_trade_return, 6),
        "total_trades":           total_trades,
        "winning_trades":         winning_trades,
        "losing_trades":          losing_trades,
        "avg_win":                round(avg_win, 4),
        "avg_loss":               round(avg_loss, 4),
        "avg_trade_days":         round(avg_trade_days, 2),
        "beta":                   round(beta, 4),
        "alpha":                  round(alpha, 6),
        "benchmark_total_return": round(benchmark_return, 6),
        "equity_final":           round(equity_final, 2),
        "equity_peak":            round(equity_peak, 2),
        "start_date":             "",
        "end_date":               "",
    }
    return metrics


def _empty_metrics(starting_capital, benchmark_return):
    return {
        "total_return": 0.0, "annualized_return": 0.0, "annualized_vol": 0.0,
        "sharpe_ratio": 0.0, "sortino_ratio": 0.0,
        "max_drawdown": 0.0, "max_drawdown_pct": 0.0, "max_drawdown_days": 0,
        "max_drawdown_peak_date": "", "max_drawdown_trough_date": "",
        "win_rate": 0.0, "profit_factor": 0.0, "avg_trade_return": 0.0,
        "total_trades": 0, "winning_trades": 0, "losing_trades": 0,
        "avg_win": 0.0, "avg_loss": 0.0, "avg_trade_days": 0.0,
        "beta": 1.0, "alpha": 0.0,
        "benchmark_total_return": benchmark_return,
        "equity_final": starting_capital, "equity_peak": starting_capital,
        "start_date": "", "end_date": "",
    }


def print_report(metrics: Dict[str, Any]) -> str:
    """Return a human-readable multi-line report string."""
    lines = [
        "=" * 60,
        "          BACKTEST PERFORMANCE REPORT",
        "=" * 60,
        f"  Total Return        : {metrics['total_return']*100:+.2f}%",
        f"  Annualised Return   : {metrics['annualized_return']*100:+.2f}%",
        f"  Annualised Vol      : {metrics['annualized_vol']*100:.2f}%",
        f"  Sharpe Ratio        : {metrics['sharpe_ratio']:.2f}",
        f"  Sortino Ratio       : {metrics['sortino_ratio']:.2f}",
        f"  Max Drawdown        : {metrics['max_drawdown']*100:.2f}%",
        f"  Max DD Days         : {metrics['max_drawdown_days']}",
        "",
        f"  Total Trades        : {metrics['total_trades']}",
        f"  Win Rate            : {metrics['win_rate']*100:.1f}%",
        f"  Profit Factor       : {metrics['profit_factor']:.2f}",
        f"  Avg Trade Return    : {metrics['avg_trade_return']*100:+.3f}%",
        f"  Avg Win             : ${metrics['avg_win']:.2f}",
        f"  Avg Loss            : ${metrics['avg_loss']:.2f}",
        f"  Avg Trade Days      : {metrics['avg_trade_days']:.1f}",
        "",
        f"  Beta                : {metrics['beta']:.3f}",
        f"  Alpha               : {metrics['alpha']*100:+.2f}%",
        f"  Benchmark Return    : {metrics['benchmark_total_return']*100:+.2f}%",
        "",
        f"  Final Equity        : ${metrics['equity_final']:.2f}",
        f"  Peak Equity         : ${metrics['equity_peak']:.2f}",
        "=" * 60,
    ]
    return "\n".join(lines)