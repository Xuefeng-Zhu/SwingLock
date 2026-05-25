"""
signals.py
Entry/exit signal logic for the Breakout / Momentum strategy.
Stdlib only.
"""
from typing import Optional

# ─── Strategy constants ────────────────────────────────────────────────────────
MAX_RISK_PCT      = 0.005   # 0.5 % of equity per trade
MAX_POSITIONS     = 5
MAX_SINGLE_POS_PCT = 0.05   # hard cap: 5 % of equity per position
HOLD_DAYS_MAX     = 12      # hard time-based exit
VIX_SKIP          = 28.0     # skip if VIX >= this
RS_LOOKBACK       = 20      # days for relative-strength calculation
BREAKOUT_LOOKBACK = 20      # days for 20-day high
VOL_MULTIPLIER    = 1.5     # volume must be > this × 20d SMA
STOP_ATR_MULT     = 1.5     # stop = entry - ATR × this
TARGET_R_MULT     = 2.5     # target = entry + (entry - stop) × this
MAX_DAY_GAIN_SKIP = 0.08    # skip if stock up > 8 % today
EARNINGS_WINDOW   = 5       # calendar days before earnings to skip


# ─── Per-ticker signal check ───────────────────────────────────────────────────

def check_entry(ticker: str, bar: dict, spy_sma50: float,
                qqq_close_20d_ago: float, earnings_dates: set) -> Optional[dict]:
    """
    Returns a dict with entry params if all entry conditions are met,
    otherwise returns None.

    bar keys required: date, open, high, low, close, volume,
                       high_20, low_20, vol_sma20, atr14
    earnings_dates: set of date strings within the window
    """
    import math

    date = bar["date"]
    close = bar["close"]
    high  = bar["high"]
    low   = bar["low"]
    volume = bar["volume"]

    # ── Rule 1: 20-day high breakout ──────────────────────────────────────────
    # True breakout: today's close exceeds the 20-day rolling high of highs.
    # That means price has cleared all prior highs in the lookback window.
    high_20 = bar.get("high_20")
    if high_20 is None or close <= high_20:
        return None

    # ── Rule 2: Volume confirmation ───────────────────────────────────────────
    vol_sma20 = bar.get("vol_sma20")
    if vol_sma20 is None or volume < VOL_MULTIPLIER * vol_sma20:
        return None

    # ── Rule 3: Relative strength vs QQQ ──────────────────────────────────────
    # Requires QQQ data for the same date — caller must inject it
    qqq_close_today = bar.get("qqq_close")
    qqq_20d_ret = None
    if qqq_close_today and qqq_close_20d_ago and qqq_close_20d_ago > 0:
        qqq_20d_ret = (qqq_close_today - qqq_close_20d_ago) / qqq_close_20d_ago
    # stock 20d return
    stock_20d_ago = bar.get("close_20d_ago")
    stock_20d_ret = None
    if stock_20d_ago and stock_20d_ago > 0:
        stock_20d_ret = (close - stock_20d_ago) / stock_20d_ago
    # Both must be computable; stock must outperform QQQ
    if qqq_20d_ret is None or stock_20d_ret is None:
        return None
    if stock_20d_ret <= qqq_20d_ret:
        return None

    # ── Rule 4: Market regime (SPY above its 50d SMA) ───────────────────────
    if spy_sma50 is None:
        return None
    spy_close_today = bar.get("spy_close")
    if spy_close_today is None or spy_close_today < spy_sma50:
        return None

    # ── Rule 5: Not overextended (> 8 % today) ────────────────────────────────
    prev_close = bar.get("prev_close", close)
    if prev_close and prev_close > 0:
        day_gain = (close - prev_close) / prev_close
        if day_gain > MAX_DAY_GAIN_SKIP:
            return None

    # ── Rule 6: Earnings safe ────────────────────────────────────────────────
    if earnings_dates and date in earnings_dates:
        return None

    # Stop: tighter of ATR-based or 2% below 20d low (as absolute floor)
    atr14 = bar.get("atr14")
    if atr14 is None or atr14 == 0:
        atr14 = close * 0.02   # fallback: 2 % of price

    stop_by_atr  = close - STOP_ATR_MULT * atr14
    stop_by_low20 = (bar.get("low_20") or close) * 0.98
    stop_price    = max(stop_by_atr, stop_by_low20)   # tighter stop
    distance      = close - stop_price
    if distance <= 0:
        return None

    target_price = close + TARGET_R_MULT * distance
    return {
        "entry_price":   close,
        "stop_price":    round(stop_price, 2),
        "target_price":  round(target_price, 2),
        "atr14":         round(atr14, 4),
        "distance":      round(distance, 4),
        "reason":        "breakout",
    }


# ─── Exit logic ────────────────────────────────────────────────────────────────

def check_exit(trade: dict, bar: dict, day_count: int) -> tuple[bool, str, float]:
    """
    Returns (should_exit, reason, exit_price).
    trade keys: entry_price, stop_price, target_price, shares
    bar keys:   close, high, low, atr14
    """
    close = bar["close"]
    high  = bar["high"]
    low   = bar["low"]

    # 1. Hard stop-loss
    if low < trade["stop_price"]:
        return True, "stop", trade["stop_price"]
    # If open gap below stop, exit at market
    open_price = bar.get("open", close)
    if open_price < trade["stop_price"] < close:
        return True, "stop_gap", trade["stop_price"]

    # 2. Time-based hard cap
    if day_count >= HOLD_DAYS_MAX:
        return True, "time", close

    # 3. Target reached — exit full position at close
    entry = trade["entry_price"]
    stop  = trade["stop_price"]
    r_mult = (close - entry) / (entry - stop) if (entry - stop) > 0 else 0
    if r_mult >= TARGET_R_MULT:
        return True, "target", close

    return False, "", 0.0