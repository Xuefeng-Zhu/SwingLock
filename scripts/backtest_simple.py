"""
backtest_simple.py
backtesting.py event-driven backtest for SwingResearch baseline strategy.
Validates vectorbt results with a slower but transparent event-driven engine.

Usage:
  python scripts/backtest_simple.py
"""

import sys, json, argparse
from pathlib import Path

import pandas as pd
import numpy as np
from backtesting import Backtest, Strategy
from backtesting.lib import crossover

# ── Strategy ──────────────────────────────────────────────────────────────────
from strategies import trend_filter, breakout_20d_signal, atr_stop_price


TICKERS      = ["SPY", "QQQ", "IWM"]
START        = "2019-01-02"
END          = "2024-12-31"
CAPITAL      = 25_000.0
ATR_MULT     = 2.0
HOLD_CAP_DAYS = 20


class SwingStrategy(Strategy):
    """Event-driven strategy using backtesting.py."""

    trend_on      = True
    max_positions  = 3
    hold_cap_days  = HOLD_CAP_DAYS

    def init(self):
        # Indicator warmup check
        self.signal_ready = False

    @property
    def entry_price(self):
        return self.position.entry_price

    def next(self):
        bar = len(self.data) - 1
        date = self.data.index[bar]

        # Warmup: skip until ATR and SMA200 are valid
        if bar < 225:
            return

        # ── Trend filter: SPY above 200d SMA ──────────────────────
        spy_trend = self.data.Close[bar] > self.data.sma200[bar]

        # ── Breakout signal ───────────────────────────────────────
        # Use 1-bar lag on high20 / vol_sma to prevent lookahead
        lag_bar = bar - 1
        close_today  = self.data.Close[bar]
        high20_lag   = self.data.high20[lag_bar]
        vol_lag      = self.data.Volume[lag_bar]
        vol_sma_lag  = self.data.vol_sma20[lag_bar]
        atr14_val    = self.data.atr14[bar]

        if pd.isna(atr14_val) or atr14_val == 0 or pd.isna(high20_lag):
            return

        # Entry conditions (all must be true)
        breakout     = close_today > high20_lag
        vol_confirm  = vol_lag > 1.5 * vol_sma_lag
        entry_ready = breakout and vol_confirm and spy_trend

        # ── Position management ───────────────────────────────────
        pos_count = len(self.closed_trades) + (1 if self.position else 0)

        # Time exit
        if self.position:
            bars_held = bar - self._entry_bar
            if bars_held >= self.hold_cap_days:
                self.position.close()
                return

            # Stop loss
            stop = self.position.stop_loss
            if stop and self.data.Low[bar] <= stop:
                self.position.close()
                return

        # ── Entry ────────────────────────────────────────────────
        if entry_ready and not self.position and pos_count < self.max_positions:
            risk_dollar = self.equity * 0.005
            atr_stop    = self.data.Close[bar] - ATR_MULT * atr14_val
            pct_stop    = self.data.Close[bar] * 0.98
            stop_price  = max(atr_stop, pct_stop)
            dist        = self.data.Close[bar] - stop_price
            if dist <= 0:
                return
            shares      = min(int(risk_dollar / dist),
                              int(0.05 * self.equity / self.data.Close[bar]))
            if shares < 1:
                return

            self.buy(size=shares,
                     sl=stop_price,
                     tp=self.data.Close[bar] + 2.5 * dist)

        # Store entry bar for time tracking
        if self.position and not hasattr(self, "_entry_bar"):
            self._entry_bar = bar


def run_backtest(data_dir, ticker, start, end, capital):
    """Run backtesting.py backtest for one ticker."""
    path = Path(data_dir) / f"{ticker}.csv"
    if not path.exists():
        raise FileNotFoundError(f"Missing: {path}")

    df = pd.read_csv(path, parse_dates=["date"], index_col="date")
    # Rename columns for backtesting.py
    df = df.rename(columns={"open": "Open", "high": "High",
                             "low": "Low", "close": "Close", "volume": "Volume"})
    df = df[start:end]

    bt = Backtest(df, SwingStrategy, cash=capital, commission=0.0,
                  margin=1.0, hedging=False, exclusive_orders=True)
    stats, heatmap = bt.run()
    return stats


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start",   default=START)
    parser.add_argument("--end",     default=END)
    parser.add_argument("--capital", type=float, default=CAPITAL)
    parser.add_argument("--data",    default="data/processed")
    args = parser.parse_args()

    print(f"\nSwingResearch — backtesting.py engine")
    print(f"  Period : {args.start} → {args.end}")
    print(f"  Capital: ${args.capital:,.0f}")
    print(f"  Engine : backtesting.py\n")

    repo_root = Path(__file__).parent.parent.resolve()
    data_dir  = repo_root / args.data

    all_stats = {}
    for ticker in TICKERS:
        print(f"Backtesting {ticker}...", end=" ")
        try:
            stats = run_backtest(data_dir, ticker, args.start, args.end, args.capital)
            all_stats[ticker] = stats
            print(f"{stats['# Trades']} trades, "
                  f"Return: {stats['Return [%]']:.2f}%")
        except Exception as e:
            print(f"ERROR: {e}")

    # Aggregate
    total_trades = sum(int(s["# Trades"]) for s in all_stats.values())
    total_return = sum(s["Return [%]"] * args.capital / 100 for s in all_stats.values())
    print(f"\nAggregated: {total_trades} trades, Total return: ${total_return:.2f}")

    # Save results
    out_dir = repo_root / "backtest" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    for ticker, stats in all_stats.items():
        stats.to_json(out_dir / f"stats_{ticker.lower()}.json")


if __name__ == "__main__":
    main()
