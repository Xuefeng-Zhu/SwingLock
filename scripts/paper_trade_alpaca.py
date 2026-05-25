"""
paper_trade_alpaca.py
Alpaca paper trading execution for SwingLock strategy.

Run daily at ~4:05 PM ET (after market close):
    python scripts/paper_trade_alpaca.py

Environment variables (set in .env):
    ALPACA_API_KEY       - Alpaca paper trading API key
    ALPACA_SECRET_KEY    - Alpaca paper trading secret
    ALPACA_PAPER=true     - Safety flag: MUST be true for paper trading

Strategy rules (from SPEC.md, best params):
    breakout_lb  = 15   # 15-day rolling max of high (lagged 1 bar)
    atr_mult     = 2.0  # stop = entry - atr_mult × ATR14
    vol_thresh   = 1.5  # volume > vol_thresh × vol_sma20 (lagged 1 bar)
    hold_days    = 10   # time-based exit after N trading days

    Universe: SPY, QQQ, IWM, XLK, XLF
    Max open positions: 3
    Max risk per trade: 0.5% equity
    Max notional per position: 5% equity
"""

import os
import sys
import csv
import logging
import time
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional

import dotenv
import pandas as pd
import numpy as np
import yfinance as yf

# Alpaca imports
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest, StopLossRequest
from alpaca.trading.enums import OrderClass
from alpaca.data.timeframe import TimeFrame
from alpaca.data.live import StockDataStream
from alpaca.data.requests import StockBarsRequest
from alpaca.data.enums import DataFeed

# ─────────────────────────────────────────────────────────────────────────────
# Project root
# ─────────────────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).parent.parent.resolve()
dotenv.load_dotenv(REPO_ROOT / ".env")

# ─────────────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("SwingLock")

# ─────────────────────────────────────────────────────────────────────────────
# Strategy constants (from best params)
# ─────────────────────────────────────────────────────────────────────────────
TICKERS          = ["SPY", "QQQ", "IWM", "XLK", "XLF"]
BREAKOUT_LB      = 15        # 15-day rolling high lookback
ATR_PERIOD      = 14        # ATR period
VOL_SMA_PERIOD  = 20        # volume SMA period
SMA200_PERIOD   = 200       # trend filter SMA
VOL_THRESH      = 1.5       # volume must exceed this × vol_sma20
ATR_MULT        = 2.0       # stop distance = ATR_MULT × ATR14
HOLD_DAYS       = 10        # time-based exit hard cap
MAX_POSITIONS   = 3         # max simultaneous open positions
MAX_RISK_PCT    = 0.005     # 0.5% of equity per trade
MAX_NOTIONAL_PCT= 0.05      # 5% of equity hard cap per position

# ─────────────────────────────────────────────────────────────────────────────
# Data paths
# ─────────────────────────────────────────────────────────────────────────────
DATA_RAW        = REPO_ROOT / "data" / "raw"
DATA_PROCESSED   = REPO_ROOT / "data" / "processed"
JOURNAL_PATH     = REPO_ROOT / "journal" / "paper_trades.csv"
os.makedirs(DATA_RAW, exist_ok=True)
os.makedirs(DATA_PROCESSED, exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# Indicator helpers (mirrors compute_indicators.py logic)
# ─────────────────────────────────────────────────────────────────────────────
def true_range(high: np.ndarray, low: np.ndarray, prev_close: np.ndarray) -> np.ndarray:
    return np.maximum(high - low, np.abs(high - prev_close), np.abs(low - prev_close))


def compute_atr14(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    tr = true_range(high, low, np.roll(close, 1))
    tr[0] = high[0] - low[0]
    atr = np.zeros_like(tr, dtype=float)
    atr[period - 1] = tr[:period].mean()
    for i in range(period, len(tr)):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    return atr


def rolling_max(arr: np.ndarray, window: int) -> np.ndarray:
    return pd.Series(arr).rolling(window=window, min_periods=window).max().values


def rolling_mean(arr: np.ndarray, window: int) -> np.ndarray:
    return pd.Series(arr).rolling(window=window, min_periods=window).mean().values


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add all required indicators to OHLCV DataFrame."""
    high  = df["high"].values.astype(float)
    low   = df["low"].values.astype(float)
    close = df["close"].values.astype(float)
    vol   = df["volume"].values.astype(float)

    df = df.copy()
    df["sma200"]    = rolling_mean(close, SMA200_PERIOD)
    df["high_lb"]   = rolling_max(high, BREAKOUT_LB)   # 15-day breakout high
    df["atr14"]     = compute_atr14(high, low, close, ATR_PERIOD)
    df["vol_sma20"] = rolling_mean(vol, VOL_SMA_PERIOD)
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Data fetching
# ─────────────────────────────────────────────────────────────────────────────
def fetch_today_data(tickers: list[str], lookback: int = 250) -> dict[str, pd.DataFrame]:
    """
    Fetch recent daily OHLCV for tickers via yfinance.
    Returns dict of {ticker: DataFrame} with date index.
    """
    result = {}
    end = date.today() + timedelta(days=1)
    start = end - timedelta(days=lookback)
    for ticker in tickers:
        try:
            yf_ticker = yf.Ticker(ticker)
            df = yf_ticker.history(start=start, end=end, interval="1d", auto_adjust=True)
            if df.empty:
                log.warning("[%s] No data returned from yfinance", ticker)
                continue
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            cols = ["Open", "High", "Low", "Close", "Volume"]
            df = df[cols].copy()
            df.columns = [c.lower() for c in cols]
            df.index = df.index.tz_localize(None)
            df = df.reset_index().rename(columns={"Date": "date"})
            df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
            df = df[["date", "open", "high", "low", "close", "volume"]].copy()
            result[ticker] = df
            log.info("[%s] Fetched %d rows (%s → %s)", ticker, len(df), df["date"].iloc[0], df["date"].iloc[-1])
        except Exception as exc:
            log.error("[%s] Fetch failed: %s", ticker, exc)
        time.sleep(0.3)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Signal generation
# ─────────────────────────────────────────────────────────────────────────────
def generate_signals(data: dict[str, pd.DataFrame], trade_date: str) -> list[dict]:
    """
    Compute lagged indicators and generate entry signals for trade_date.
    All indicators are lagged by 1 bar (yesterday's values) to avoid lookahead.

    Returns list of signal dicts with keys: ticker, entry_price, stop_price,
    shares, dollar_risk, pct_risk, reason.
    """
    signals = []

    # Get SPY data for trend filter
    if "SPY" not in data:
        log.error("SPY data required for trend filter — aborting")
        return signals

    spy_df = compute_indicators(data["SPY"])
    spy_df = spy_df.set_index("date")

    # Check trend filter: SPY close > SPY SMA(200) on lagged bar
    spy_date_lagged = _prev_trading_day(spy_df.index, trade_date, offset=1)
    if spy_date_lagged is None:
        log.warning("Cannot apply trend filter — insufficient SPY history")
        return signals
    spy_row = spy_df.loc[spy_date_lagged] if spy_date_lagged in spy_df.index else None
    if spy_row is None:
        log.warning("SPY date %s not in index", spy_date_lagged)
        return signals

    if not (spy_row["close"] > spy_row["sma200"]):
        log.info("Trend filter FAILED: SPY %s (%.2f) <= SMA200 (%.2f) — no new entries",
                 spy_date_lagged, spy_row["close"], spy_row["sma200"])
        return signals

    log.info("Trend filter PASSED: SPY %s close %.2f > SMA200 %.2f",
             spy_date_lagged, spy_row["close"], spy_row["sma200"])

    # Count currently open positions
    open_pos = get_open_positions()
    slots = MAX_POSITIONS - len(open_pos)
    if slots <= 0:
        log.info("Max positions (%d) already open — skipping scan", MAX_POSITIONS)
        return signals

    for ticker in TICKERS:
        if ticker == "SPY":
            continue  # SPY is filter only, not traded

        if ticker not in data:
            continue

        df = compute_indicators(data[ticker])
        df = df.set_index("date")

        # Need at least 2 bars: bar[-2] for lagged signal, bar[-1] for entry price
        if len(df) < 2:
            log.warning("[%s] Insufficient data for signal generation", ticker)
            continue

        # Today's row (most recent bar) = entry price source
        today_row = df.iloc[-1]
        entry_price = float(today_row["close"])

        # Lagged bar (yesterday) = signal generation
        lag_row = df.iloc[-2]
        lag_date = lag_row.name

        # Skip if gap between lag_date and today is > 5 calendar days (stale data)
        lag_dt = pd.to_datetime(lag_date)
        today_dt = pd.to_datetime(trade_date)
        if (today_dt - lag_dt).days > 5:
            log.warning("[%s] Data appears stale (%s) — skipping", ticker, lag_date)
            continue

        # Validate indicators
        if pd.isna(lag_row["high_lb"]) or pd.isna(lag_row["vol_sma20"]) or pd.isna(lag_row["atr14"]):
            log.warning("[%s] Lagged indicators not ready (NaN) — skipping", ticker)
            continue

        if lag_row["vol_sma20"] <= 0 or lag_row["atr14"] <= 0:
            log.warning("[%s] Invalid indicator values — skipping", ticker)
            continue

        # ── Signal checks ──────────────────────────────────────────────────────
        vol_ok = lag_row["volume"] > VOL_THRESH * lag_row["vol_sma20"]
        price_ok = entry_price > lag_row["high_lb"]   # breakout: close > 15d high (lagged)

        if not (vol_ok and price_ok):
            continue  # No signal this ticker

        log.info("[%s] BREAKOUT SIGNAL @ $%.2f  (high15_lag=%.2f, vol=%.0f, vol_sma20=%.0f)",
                 ticker, entry_price, lag_row["high_lb"], lag_row["volume"], lag_row["vol_sma20"])

        # ── Stop and position sizing ────────────────────────────────────────────
        atr14 = float(lag_row["atr14"])
        stop_price = round(entry_price - ATR_MULT * atr14, 2)
        pct_stop = round(entry_price * 0.98, 2)   # max 2% adverse move
        stop_price = max(stop_price, pct_stop)   # tightest stop wins

        # Equity from Alpaca account
        equity = get_account_equity()
        if equity is None:
            equity = 25_000.0  # fallback
            log.warning("Could not fetch equity — using $25,000")

        max_dollar_risk = equity * MAX_RISK_PCT
        distance = entry_price - stop_price
        if distance <= 0:
            log.warning("[%s] Invalid stop distance (%.2f) — skipping", ticker, distance)
            continue

        shares_by_risk = int(max_dollar_risk / distance)
        shares_by_notional = int((equity * MAX_NOTIONAL_PCT) / entry_price)
        shares = min(shares_by_risk, shares_by_notional)
        shares = max(shares, 1)  # at least 1 share

        dollar_risk = shares * distance
        pct_risk = dollar_risk / equity * 100

        signals.append({
            "ticker": ticker,
            "entry_price": entry_price,
            "stop_price": stop_price,
            "shares": shares,
            "dollar_risk": round(dollar_risk, 2),
            "pct_risk": round(pct_risk, 3),
            "atr14": round(atr14, 4),
            "reason": "breakout",
        })

        if len(signals) >= slots:
            break

    return signals


def _prev_trading_day(dates: pd.Index, current: str, offset: int = 1) -> Optional[str]:
    """Return the N-th previous trading day before current."""
    current_dt = pd.to_datetime(current)
    # Normalize dates to Timestamp for comparison (handles string Index from yfinance pipeline)
    if dates.dtype == object or not hasattr(dates, 'tz') or dates.tz is None:
        try:
            dates = pd.to_datetime(dates)
        except Exception:
            pass
    if current_dt.tz is not None:
        current_dt = current_dt.tz_localize(None)
    past = dates[dates < current_dt]
    if len(past) < offset:
        return None
    result = past[-offset]
    # Return as YYYY-MM-DD string to match string Index from yfinance pipeline
    if hasattr(result, 'strftime'):
        return result.strftime("%Y-%m-%d")
    return str(result)


# ─────────────────────────────────────────────────────────────────────────────
# Alpaca client helpers
# ─────────────────────────────────────────────────────────────────────────────
def get_alpaca_client() -> TradingClient:
    api_key = os.getenv("ALPACA_API_KEY")
    secret  = os.getenv("ALPACA_SECRET_KEY")
    paper   = os.getenv("ALPACA_PAPER", "true").lower()

    if not api_key or not secret:
        raise RuntimeError(
            "ALPACA_API_KEY / ALPACA_SECRET_KEY not set in .env. "
            "Get free keys at https://app.alpaca.markets/"
        )
    if paper != "true":
        raise RuntimeError(
            f"ALPACA_PAPER={paper} — paper trading is disabled. "
            "Set ALPACA_PAPER=true to run paper trades."
        )

    return TradingClient(api_key, secret, paper=True)


def get_account_equity() -> Optional[float]:
    """Fetch current account equity from Alpaca."""
    try:
        client = get_alpaca_client()
        account = client.get_account()
        return float(account.equity)
    except Exception as exc:
        log.error("Failed to fetch account equity: %s", exc)
        return None


def get_open_positions() -> list[dict]:
    """Return list of open positions as dicts."""
    try:
        client = get_alpaca_client()
        positions = client.list_positions()
        return [
            {
                "symbol": p.symbol,
                "qty": float(p.qty),
                "side": p.side,
                "entry_price": float(p.avg_entry_price),
                "current_price": float(p.current_price),
                "unrealized_pl": float(p.unrealized_pl),
            }
            for p in positions
        ]
    except Exception as exc:
        log.error("Failed to fetch open positions: %s", exc)
        return []


def get_positions_for_ticker(ticker: str) -> list[dict]:
    """Get open positions for a specific ticker."""
    return [p for p in get_open_positions() if p["symbol"] == ticker]


# ─────────────────────────────────────────────────────────────────────────────
# Order execution
# ─────────────────────────────────────────────────────────────────────────────
def submit_entry(signal: dict, trade_date: str) -> bool:
    """
    Submit a market buy order for the signal.
    Returns True if order submitted successfully.
    """
    ticker      = signal["ticker"]
    shares      = signal["shares"]
    entry_price = signal["entry_price"]
    stop_price  = signal["stop_price"]

    try:
        client = get_alpaca_client()

        # Bracket order: market buy + stop-loss in single request
        order = MarketOrderRequest(
            symbol=ticker,
            qty=shares,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
            order_class=OrderClass.BRACKET,
            stop_loss=StopLossRequest(stop_price=stop_price),
        )
        filled = client.submit_order(order)
        log.info("[ORDER] BUY %d shares %s @ market  (order_id=%s)", shares, ticker, filled.id)

        # Log to journal
        log_trade({
            "date": trade_date,
            "ticker": ticker,
            "action": "entry",
            "entry_price": entry_price,
            "exit_price": "",
            "shares": shares,
            "stop_price": stop_price,
            "pnl": "",
            "reason": signal["reason"],
            "rule_violation": "N",
            "atr14": signal.get("atr14", ""),
            "dollar_risk": signal.get("dollar_risk", ""),
            "pct_risk": signal.get("pct_risk", ""),
            "order_id": filled.id,
            "notes": "",
        })
        return True

    except Exception as exc:
        log.error("[ORDER FAILED] BUY %s: %s", ticker, exc)
        return False


def check_and_close_expired_positions(trade_date: str) -> None:
    """
    Check all open positions for time-based exit (hold_days exceeded).
    Close positions where days_held >= HOLD_DAYS.
    """
    try:
        client = get_alpaca_client()
        positions = get_open_positions()

        if not positions:
            return

        # Load trade journal to find entry dates
        journal = load_journal()
        # Build entry date lookup by ticker (most recent entry)
        entry_dates = {}
        for row in reversed(journal):
            if row.get("action") == "entry" and row.get("ticker"):
                ticker = row["ticker"]
                if ticker not in entry_dates:
                    entry_dates[ticker] = row["date"]

        today_dt = pd.to_datetime(trade_date)

        for pos in positions:
            ticker = pos["symbol"]
            if ticker not in entry_dates:
                log.warning("[%s] Open position but no entry in journal — manual review required", ticker)
                continue

            entry_dt = pd.to_datetime(entry_dates[ticker])
            days_held = (today_dt - entry_dt).days

            if days_held >= HOLD_DAYS:
                log.info("[TIME EXIT] %s held %d days (limit=%d) — closing at market",
                         ticker, days_held, HOLD_DAYS)
                try:
                    order = MarketOrderRequest(
                        symbol=ticker,
                        qty=int(pos["qty"]),
                        side=OrderSide.SELL,
                        time_in_force=TimeInForce.DAY,
                    )
                    filled = client.submit_order(order)
                    log.info("[ORDER] SELL %d shares %s @ market  (time exit, order_id=%s)",
                             int(pos["qty"]), ticker, filled.id)

                    # Log exit
                    log_trade({
                        "date": trade_date,
                        "ticker": ticker,
                        "action": "exit",
                        "entry_price": pos["entry_price"],
                        "exit_price": pos["current_price"],
                        "shares": int(pos["qty"]),
                        "stop_price": "",
                        "pnl": round(pos["unrealized_pl"], 2),
                        "reason": f"time ({days_held}d)",
                        "rule_violation": "N",
                        "atr14": "",
                        "dollar_risk": "",
                        "pct_risk": "",
                        "order_id": filled.id,
                        "notes": "",
                    })
                except Exception as exc:
                    log.error("[TIME EXIT FAILED] %s: %s", ticker, exc)
            else:
                log.debug("[HOLD] %s: %d/%d days held", ticker, days_held, HOLD_DAYS)

    except Exception as exc:
        log.error("Error in check_and_close_expired_positions: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Journal I/O
# ─────────────────────────────────────────────────────────────────────────────
TRADE_COLS = [
    "date", "ticker", "action", "entry_price", "exit_price", "shares",
    "stop_price", "pnl", "reason", "rule_violation",
    "atr14", "dollar_risk", "pct_risk", "order_id", "notes",
]


def load_journal() -> list[dict]:
    """Load journal/paper_trades.csv as list of dicts."""
    if not JOURNAL_PATH.exists():
        return []
    try:
        with open(JOURNAL_PATH, newline="") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return []


def log_trade(trade: dict) -> None:
    """Append a trade record to the paper trades journal."""
    file_exists = JOURNAL_PATH.exists()

    # Ensure directory exists
    JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(JOURNAL_PATH, newline="", mode="a") as f:
        writer = csv.DictWriter(f, fieldnames=TRADE_COLS)
        if not file_exists:
            writer.writeheader()
        writer.writerow({k: trade.get(k, "") for k in TRADE_COLS})

    log.info("[JOURNAL] %s %s %s @ $%s  PNL=%s  reason=%s",
             trade["action"].upper(),
             trade["ticker"],
             trade.get("shares", ""),
             trade.get("entry_price", "") or trade.get("exit_price", ""),
             trade.get("pnl", ""),
             trade.get("reason", ""))


# ─────────────────────────────────────────────────────────────────────────────
# Daily scan
# ─────────────────────────────────────────────────────────────────────────────
def daily_scan(trade_date: Optional[str] = None) -> None:
    """
    Main daily paper trading scan.

    Steps:
    1. Fetch latest OHLCV data for all tickers
    2. Compute indicators with 1-bar lag
    3. Generate entry signals (respecting max positions)
    4. Execute buy orders with stop-loss
    5. Check existing positions for time-based exit
    6. Log everything to journal/paper_trades.csv
    """
    if trade_date is None:
        trade_date = date.today().strftime("%Y-%m-%d")

    log.info("=" * 60)
    log.info("SwingLock Daily Paper Trading Scan — %s", trade_date)
    log.info("=" * 60)

    # ── Safety check ──────────────────────────────────────────────────────────
    paper_flag = os.getenv("ALPACA_PAPER", "true").lower()
    if paper_flag != "true":
        log.error("ABORT: ALPACA_PAPER=%s (must be 'true')", paper_flag)
        log.error("Paper trading is DISABLED. Set ALPACA_PAPER=true to enable.")
        sys.exit(1)

    # ── Step 1: Fetch data ────────────────────────────────────────────────────
    log.info("[STEP 1] Fetching market data for %s", TICKERS)
    data = fetch_today_data(TICKERS)
    if not data:
        log.error("No data fetched — aborting scan")
        sys.exit(1)

    missing = [t for t in TICKERS if t not in data]
    if missing:
        log.warning("Missing data for: %s", missing)

    # ── Step 2: Check open positions (for logging / time exit) ───────────────
    log.info("[STEP 2] Checking open positions")
    open_pos = get_open_positions()
    log.info("  Open positions: %d / %d", len(open_pos), MAX_POSITIONS)
    for p in open_pos:
        log.info("    %s: qty=%s entry=$%.2f current=$%.2f unrealized=$%.2f",
                 p["symbol"], p["qty"], p["entry_price"], p["current_price"], p["unrealized_pl"])

    # ── Step 3: Time-based exit check ─────────────────────────────────────────
    log.info("[STEP 3] Checking time-based exits (hold_days=%d)", HOLD_DAYS)
    check_and_close_expired_positions(trade_date)

    # ── Step 4: Generate entry signals ───────────────────────────────────────
    log.info("[STEP 4] Scanning for entry signals (breakout_lb=%d, vol_thresh=%.1f)", BREAKOUT_LB, VOL_THRESH)
    signals = generate_signals(data, trade_date)
    if not signals:
        log.info("No entry signals today.")
    else:
        log.info("Generated %d signal(s): %s", len(signals), [s["ticker"] for s in signals])

    # ── Step 5: Execute orders ─────────────────────────────────────────────────
    log.info("[STEP 5] Executing orders")
    for sig in signals:
        ok = submit_entry(sig, trade_date)
        log.info("  %s: %s", sig["ticker"], "SUBMITTED" if ok else "FAILED")

    log.info("Daily scan complete — %s", trade_date)


# ─────────────────────────────────────────────────────────────────────────────
# CLI entrypoint
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="SwingLock Alpaca paper trading daily scan")
    parser.add_argument("--date", default=None, help="Trade date (YYYY-MM-DD). Defaults to today.")
    parser.add_argument("--dry-run", action="store_true", help="Compute signals without placing orders.")
    args = parser.parse_args()

    trade_date = args.date or date.today().strftime("%Y-%m-%d")

    if args.dry_run:
        log.info("DRY RUN — computing signals without placing orders")
        data = fetch_today_data(TICKERS)
        signals = generate_signals(data, trade_date)
        if not signals:
            print("No signals.")
        else:
            for s in signals:
                print(f"  SIGNAL: {s['ticker']}  entry=${s['entry_price']}  "
                      f"stop=${s['stop_price']}  shares={s['shares']}  "
                      f"risk=${s['dollar_risk']} ({s['pct_risk']}%)")
        sys.exit(0)

    daily_scan(trade_date)
