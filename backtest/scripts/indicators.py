"""
indicators.py
Compute daily indicators for each ticker from raw CSV data.
Stdlib only.
"""
import csv
import math
from datetime import datetime
from typing import List, Dict

# ─── Rolling window helpers ───────────────────────────────────────────────────

def rolling_max(values: list, n: int) -> list:
    """Rolling max over last n values. Returns list of same length (padded with None)."""
    out = []
    for i in range(len(values)):
        if i < n - 1:
            out.append(None)
        else:
            out.append(max(values[i - n + 1 : i + 1]))
    return out


def rolling_min(values: list, n: int) -> list:
    out = []
    for i in range(len(values)):
        if i < n - 1:
            out.append(None)
        else:
            out.append(min(values[i - n + 1 : i + 1]))
    return out


def rolling_sma(values: list, n: int) -> list:
    out = []
    for i in range(len(values)):
        if i < n - 1:
            out.append(None)
        else:
            out.append(sum(values[i - n + 1 : i + 1]) / n)
    return out


def true_range(high: float, low: float, prev_close: float) -> float:
    return max(high - low, abs(high - prev_close), abs(low - prev_close))


def compute_atr(rows: list, period: int = 14) -> list:
    """Compute ATR(period) using True Range. Returns list (None for first 'period' rows)."""
    trs = []
    for i, r in enumerate(rows):
        prev = float(rows[i - 1]["close"]) if i > 0 else float(r["close"])
        trs.append(true_range(float(r["high"]), float(r["low"]), prev))
    # First ATR value is simple SMA of first 'period' TRs
    atr = [None] * len(trs)
    if len(trs) >= period:
        sma = sum(trs[:period]) / period
        atr[period - 1] = sma
        for i in range(period, len(trs)):
            sma = (sma * (period - 1) + trs[i]) / period
            atr[i] = sma
    return atr


def compute_20d_return(close: float, close_n_days_ago: float) -> float:
    if close_n_days_ago and close_n_days_ago != 0:
        return (close - close_n_days_ago) / close_n_days_ago
    return 0.0


# ─── Main per-ticker indicator engine ───────────────────────────────────────

def process_ticker(ticker: str, in_dir: str = "data/raw", out_dir: str = "data/processed") -> str:
    """
    Read raw CSV, append computed indicator columns, write to processed/ .
    Returns output file path.
    """
    import os
    os.makedirs(out_dir, exist_ok=True)

    rows = []
    with open(f"{in_dir}/{ticker}.csv") as f:
        for r in csv.DictReader(f):
            r["volume"] = int(r["volume"])
            r["close"]  = float(r["close"])
            r["high"]   = float(r["high"])
            r["low"]    = float(r["low"])
            r["open"]   = float(r["open"])
            rows.append(r)

    closes   = [r["close"]  for r in rows]
    highs    = [r["high"]   for r in rows]
    lows     = [r["low"]    for r in rows]
    volumes  = [r["volume"] for r in rows]

    high_20  = rolling_max(highs, 20)
    low_20   = rolling_min(lows, 20)
    vol_sma20 = rolling_sma(volumes, 20)
    atr14    = compute_atr(rows, 14)

    out_rows = []
    for i, r in enumerate(rows):
        r["high_20"]   = high_20[i]
        r["low_20"]    = low_20[i]
        r["vol_sma20"] = round(vol_sma20[i], 2) if vol_sma20[i] is not None else None
        r["atr14"]     = round(atr14[i], 4) if atr14[i] is not None else None
        out_rows.append(r)

    out_path = f"{out_dir}/{ticker}.csv"
    fieldnames = [
        "date", "open", "high", "low", "close", "adj_close", "volume",
        "high_20", "low_20", "vol_sma20", "atr14",
    ]
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(out_rows)

    print(f"  [OK] {ticker}: {len(out_rows)} rows -> {out_path}")
    return out_path


def compute_spy_sma50(in_dir: str = "data/processed") -> Dict[str, float]:
    """
    Compute SPY 50-day SMA for every date in the dataset.
    Returns dict: date_str -> sma50 value.
    """
    spy_rows = []
    with open(f"{in_dir}/SPY.csv") as f:
        for r in csv.DictReader(f):
            spy_rows.append({"date": r["date"], "close": float(r["close"])})

    closes = [r["close"] for r in spy_rows]
    sma50  = rolling_sma(closes, 50)
    return {spy_rows[i]["date"]: sma50[i] for i in range(len(spy_rows)) if sma50[i] is not None}


if __name__ == "__main__":
    import os
    IN  = "data/raw"
    OUT = "data/processed"
    os.makedirs(OUT, exist_ok=True)

    tickers = ["SPY", "QQQ", "IWM", "NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "TSLA"]
    for t in tickers:
        process_ticker(t, IN, OUT)

    print("Computing SPY SMA(50) ...")
    spy_sma = compute_spy_sma50(OUT)
    print(f"  {len(spy_sma)} date/SMA pairs loaded.")