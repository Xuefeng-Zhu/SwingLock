"""
breakout_20d.py
Entry signal: today's close exceeds the 20-day rolling high of highs.

Rules:
    1. close > high20 (yesterday's 20d rolling high — 1 bar of lag to avoid lookahead)
    2. Volume confirms: volume > 1.5 × vol_sma20 (yesterday's SMA)

All checks use 1-bar lagged values to prevent lookahead bias.
"""
import numpy as np
import pandas as pd


def breakout_20d_signal(
    close: pd.Series,
    high: pd.Series,
    high20: pd.Series,
    volume: pd.Series,
    vol_sma20: pd.Series,
) -> pd.Series:
    """
    Return a boolean Series: True where all breakout conditions are met.

    Uses 1-bar lagged high20 and vol_sma20 to ensure the signal fires
    AFTER a confirmed breakout, not during it (no lookahead).
    """
    lag_high20    = high20.shift(1)
    lag_vol_sma20 = vol_sma20.shift(1)

    cond_breakout = close > lag_high20
    cond_volume   = volume > 1.5 * lag_vol_sma20

    return cond_breakout & cond_volume