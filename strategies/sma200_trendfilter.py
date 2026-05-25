"""
sma200_trendfilter.py
Trend filter: SPY must be above its 200-day SMA before accepting entries.
"""
import numpy as np
import pandas as pd


def trend_filter(close: pd.Series, sma200: pd.Series) -> pd.Series:
    """
    Return a boolean Series: True when close > SMA(200).
    NaN values propagate (no signal until SMA200 is computed).
    """
    return close > sma200