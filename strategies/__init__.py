"""
strategies/__init__.py
Re-export strategy components for convenience.
"""
from .sma200_trendfilter import trend_filter
from .breakout_20d import breakout_20d_signal
from .atr_stop import atr_stop_price, stop_distance

__all__ = [
    "trend_filter",
    "breakout_20d_signal",
    "atr_stop_price",
    "stop_distance",
]