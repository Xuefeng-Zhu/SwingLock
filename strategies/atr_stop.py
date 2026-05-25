"""
atr_stop.py
ATR-based stop loss for the baseline strategy.

Stop = entry_price - multiplier * ATR14
Tightest stop wins if ATR stop is wider than 2% stop.
"""
import numpy as np


def atr_stop_price(entry_price: float, atr14: float, multiplier: float = 2.0) -> float:
    """
    Compute stop price given entry and ATR.

    Parameters
    ----------
    entry_price : float
        Price at which the position was entered.
    atr14 : float
        Current 14-day ATR value.
    multiplier : float
        ATR multiples for the stop distance.

    Returns
    -------
    float
        Stop price (floor: entry * 0.98, i.e., max 2% adverse move).
    """
    atr_stop = entry_price - multiplier * atr14
    pct_stop = entry_price * 0.98
    return max(atr_stop, pct_stop)


def stop_distance(entry_price: float, atr14: float, multiplier: float = 2.0) -> float:
    """Distance in dollars from entry to stop."""
    return entry_price - atr_stop_price(entry_price, atr14, multiplier)