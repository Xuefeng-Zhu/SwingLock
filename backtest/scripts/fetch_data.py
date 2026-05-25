"""
Data fetcher — Yahoo Finance JSON API (no auth required).
Fetches daily OHLCV for a list of tickers and saves to CSVs.
Stdlib only: urllib, json, datetime, csv, os, math, time.
"""
import urllib.request
import json
import csv
import os
import math
import time
from datetime import datetime, timedelta

TICKERS = ["SPY", "QQQ", "IWM", "NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "TSLA"]
OUT_DIR = "data/raw/"

END_DT   = datetime(2024, 12, 31)
START_DT = END_DT - timedelta(days=6 * 365)

os.makedirs(OUT_DIR, exist_ok=True)


def fetch_yahoo_chart(symbol, start_ts: int, end_ts: int, interval="1d"):
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        f"?period1={start_ts}&period2={end_ts}&interval={interval}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode())

    result = data["chart"]["result"]
    if not result:
        print(f"  [WARN] No result for {symbol}")
        return []
    result = result[0]
    timestamps = result.get("timestamp", [])
    quote = result["indicators"].get("quote", [{}])[0]
    adj_close = result["indicators"].get("adjclose", [None])
    adj_close = adj_close[0]["adjclose"] if adj_close and adj_close[0] else None

    rows = []
    for i, ts in enumerate(timestamps):
        close = quote["close"][i]
        vol   = quote["volume"][i]
        if close is None or (isinstance(close, float) and math.isnan(close)):
            continue
        adj = (adj_close[i]
               if adj_close
                  and not (isinstance(adj_close[i], float) and math.isnan(adj_close[i]))
               else close)
        rows.append({
            "date":      datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d"),
            "open":      round(quote["open"][i] or close, 4),
            "high":      round(quote["high"][i] or close, 4),
            "low":       round(quote["low"][i]  or close, 4),
            "close":     round(close, 4),
            "adj_close": round(adj, 4),
            "volume":    int(vol) if vol and not (isinstance(vol, float) and math.isnan(vol)) else 0,
        })
    return rows


def save_csv(rows, symbol, out_dir):
    path = os.path.join(out_dir, f"{symbol}.csv")
    if not rows:
        print(f"  [SKIP] {symbol} — no data")
        return False
    fieldnames = ["date", "open", "high", "low", "close", "adj_close", "volume"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    print(f"  [OK] {symbol} — {len(rows)} rows -> {path}")
    return True


if __name__ == "__main__":
    start_ts = int(START_DT.timestamp())
    end_ts   = int(END_DT.timestamp())
    failures = []
    for t in TICKERS:
        print(f"Fetching {t} ...", flush=True)
        try:
            rows = fetch_yahoo_chart(t, start_ts, end_ts)
            if not rows:
                failures.append(t)
                continue
            if save_csv(rows, t, OUT_DIR):
                time.sleep(0.3)
            else:
                failures.append(t)
        except Exception as e:
            print(f"  [ERR] {t}: {e}")
            failures.append(t)

    print(f"\nDone. Failures: {failures}")