"""
report_quantstats.py
Generate QuantStats HTML performance reports from backtest equity curves.

Usage:
  python scripts/report_quantstats.py
  python scripts/report_quantstats.py --input backtest/results/equity.csv
"""

import sys, argparse, json
from pathlib import Path

import pandas as pd
import quantstats as qs


def load_equity(csv_path):
    df = pd.read_csv(csv_path, parse_dates=["date"], index_col="date")
    return df["equity"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input",  default="backtest/results/equity.csv")
    parser.add_argument("--output", default="reports/performance.html")
    parser.add_argument("--title",  default="SwingResearch Baseline Strategy")
    args = parser.parse_args()

    repo_root = Path(__file__).parent.parent.resolve()
    in_path   = repo_root / args.input
    out_path  = repo_root / args.output

    if not in_path.exists():
        print(f"[ERROR] Equity file not found: {in_path}")
        print("  Run backtest_vbt.py or backtest_simple.py first.")
        sys.exit(1)

    print(f"Loading equity curve: {in_path}")
    equity = load_equity(in_path)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Writing report: {out_path}")

    qs.reports.html(
        returns=equity.pct_change().dropna(),
        benchmark="SPY",
        title=args.title,
        output=out_path
    )
    print("Done.")


if __name__ == "__main__":
    main()
