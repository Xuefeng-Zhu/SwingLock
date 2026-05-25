"""
compute_indicators.py
Compute rolling indicators on raw OHLCV data and save to processed/.

Indicators added:
    - sma200  : 200-day SMA of close
    - sma50   : 50-day SMA of close
    - high20  : 20-day rolling MAX of high
    - low20   : 20-day rolling MIN of low
    - atr14   : 14-day Average True Range
    - vol_sma20 : 20-day SMA of volume

Usage:
    python scripts/compute_indicators.py
    python scripts/compute_indicators.py --tickers SPY QQQ --data data/raw
"""
import os
import argparse
from pathlib import Path

import pandas as pd
import numpy as np


TICKERS_DEFAULT = ["SPY", "QQQ", "IWM"]


def true_range(high, low, prev_close):
    """Compute True Range = max(high-low, |high-prev_close|, |low-prev_close|)"""
    return np.maximum(high - low, np.abs(high - prev_close), np.abs(low - prev_close))


def compute_atr14(high, low, close, period=14):
    """Compute ATR14 using Wilder's smoothing method (modified MA)."""
    tr = true_range(high, low, np.roll(close, 1))
    tr[0] = high[0] - low[0]   # first bar: use high-low
    atr = np.zeros_like(tr, dtype=float)
    atr[period - 1] = tr[:period].mean()
    for i in range(period, len(tr)):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    return atr


def rolling_max(arr, window):
    """Rolling max with min_periods=window (NaN until window is filled)."""
    return pd.Series(arr).rolling(window=window, min_periods=window).max().values


def rolling_min(arr, window):
    return pd.Series(arr).rolling(window=window, min_periods=window).min().values


def rolling_mean(arr, window):
    return pd.Series(arr).rolling(window=window, min_periods=window).mean().values


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add all indicators to a OHLCV DataFrame."""
    high  = df["high"].values.astype(float)
    low   = df["low"].values.astype(float)
    close = df["close"].values.astype(float)
    vol   = df["volume"].values.astype(float)

    df = df.copy()
    df["sma200"]    = rolling_mean(close, 200)
    df["sma50"]     = rolling_mean(close, 50)
    df["high20"]    = rolling_max(high, 20)
    df["low20"]     = rolling_min(low, 20)
    df["atr14"]     = compute_atr14(high, low, close, 14)
    df["vol_sma20"] = rolling_mean(vol, 20)

    return df


def process_ticker(ticker: str, raw_dir: Path, out_dir: Path) -> bool:
    """Load raw CSV, compute indicators, save to processed/."""
    raw_path = raw_dir / f"{ticker}.csv"
    out_path = out_dir / f"{ticker}.csv"
    if not raw_path.exists():
        print(f"  [SKIP] {ticker}: {raw_path} not found")
        return False

    try:
        df = pd.read_csv(raw_path, parse_dates=["date"])
        df = compute_indicators(df)
        df.to_csv(out_path, index=False)
        rows = len(df)
        non_null_atr = df["atr14"].notna().sum()
        print(f"  [OK]   {ticker}.csv  ({rows} rows, ATR valid from row {200 + 14})")
        return True
    except Exception as exc:
        print(f"  [ERR]  {ticker}: {exc}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Compute rolling indicators on raw data")
    parser.add_argument("--tickers", nargs="+", default=TICKERS_DEFAULT)
    parser.add_argument("--data",    default="data/raw",  help="Raw data directory")
    args = parser.parse_args()

    repo_root = Path(__file__).parent.parent.resolve()
    raw_dir    = repo_root / args.data
    out_dir    = repo_root / "data" / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\nComputing indicators for: {args.tickers}")
    print(f"  Raw input : {raw_dir}")
    print(f"  Output     : {out_dir}\n")

    success = 0
    for ticker in args.tickers:
        if process_ticker(ticker, raw_dir, out_dir):
            success += 1

    print(f"\nDone: {success}/{len(args.tickers)} tickers processed.")


if __name__ == "__main__":
    main()