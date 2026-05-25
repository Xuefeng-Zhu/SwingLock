"""
fetch_data.py
Fetch daily OHLCV data from Yahoo Finance (no API key required).

Usage:
    python scripts/fetch_data.py --tickers SPY QQQ IWM --start 2019-01-01 --end 2024-12-31
    python scripts/fetch_data.py --tickers SPY QQQ IWM --start 2019-01-01 --end 2024-12-31 --out data/raw
"""
import os
import sys
import json
import time
import argparse
from pathlib import Path
from datetime import datetime

import pandas as pd
import yfinance as yf


TICKERS_DEFAULT = ["SPY", "QQQ", "IWM"]


def fetch_ticker(ticker: str, start: str, end: str, out_dir: Path) -> bool:
    """Fetch daily OHLCV for one ticker. Returns True on success."""
    path = out_dir / f"{ticker}.csv"
    if path.exists():
        print(f"  [SKIP] {ticker}.csv already exists")
        return True

    try:
        yf_ticker = yf.Ticker(ticker)
        df = yf_ticker.history(start=start, end=end, interval="1d", auto_adjust=True)
        if df.empty:
            print(f"  [FAIL] {ticker}: no data returned")
            return False

        # Flatten multi-index if present
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # Keep only OHLCV columns
        cols = ["Open", "High", "Low", "Close", "Volume"]
        df = df[cols].copy()
        df.columns = [c.lower() for c in cols]

        # Reset to naive datetime (yfinance returns UTC-aware)
        df.index = df.index.tz_localize(None)

        # Add date column and reorder
        df = df.reset_index().rename(columns={"Date": "date"})
        cols2 = ["date", "open", "high", "low", "close", "volume"]
        df = df[cols2].copy()
        df["date"] = df["date"].dt.strftime("%Y-%m-%d")

        # Validate
        assert list(df.columns) == cols2, f"Column mismatch: {df.columns.tolist()}"
        assert df["volume"].gt(0).all(), f"{ticker}: zero or negative volume found"
        assert df[["open","high","low","close"]].gt(0).all().all(), f"{ticker}: non-positive price found"

        df.to_csv(path, index=False)
        rows = len(df)
        print(f"  [OK]   {ticker}.csv  ({rows} rows, {df['date'].iloc[0]} to {df['date'].iloc[-1]})")
        return True

    except Exception as exc:
        print(f"  [ERR]  {ticker}: {exc}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Fetch daily OHLCV from Yahoo Finance")
    parser.add_argument("--tickers", nargs="+", default=TICKERS_DEFAULT)
    parser.add_argument("--start", default="2019-01-01")
    parser.add_argument("--end",   default="2024-12-31")
    parser.add_argument("--out",   default="data/raw",
                        help="Output directory relative to repo root")
    args = parser.parse_args()

    # Resolve output dir relative to repo root
    repo_root = Path(__file__).parent.parent.resolve()
    out_dir = repo_root / args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\nFetching {len(args.tickers)} tickers: {args.tickers}")
    print(f"  Period  : {args.start} → {args.end}")
    print(f"  Output  : {out_dir}\n")

    success = 0
    for ticker in args.tickers:
        ok = fetch_ticker(ticker, args.start, args.end, out_dir)
        if ok:
            success += 1
        time.sleep(0.3)   # polite rate limiting

    print(f"\nDone: {success}/{len(args.tickers)} tickers fetched successfully.")
    if success < len(args.tickers):
        sys.exit(1)


if __name__ == "__main__":
    main()