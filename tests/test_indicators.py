"""
tests/test_indicators.py
Unit tests for indicator computations.

Run: pytest tests/test_indicators.py -v
"""

import pytest, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from compute_indicators import compute_indicators, compute_atr14, true_range
import pandas as pd
import numpy as np


class DummyData:
    """Small OHLCV fixture for testing."""
    @staticmethod
    def make(n=30):
        dates = pd.bdate_range("2020-01-01", periods=n)
        return pd.DataFrame({
            "date":   dates,
            "open":   np.random.uniform(100, 110, n),
            "high":   np.random.uniform(105, 115, n),
            "low":    np.random.uniform(95, 105, n),
            "close":  np.random.uniform(100, 110, n),
            "volume": np.random.uniform(1e6, 5e6, n),
        })


def test_true_range():
    tr = true_range(
        high=pd.Series([110, 112, 108]),
        low=pd.Series([100, 102,  98]),
        prev_close=pd.Series([105, 109, 111]),
    )
    assert tr[0] == 10.0      # high - low
    assert tr[1] == 10.0      # high - prev_close
    assert tr[2] == 13.0      # prev_close - low


def test_compute_atr14_warmup():
    df = DummyData.make(20)
    df.columns = ["date","open","high","low","close","volume"]
    high  = df["high"].values.astype(float)
    low   = df["low"].values.astype(float)
    close = df["close"].values.astype(float)
    atr   = compute_atr14(high, low, close, 14)
    assert len(atr) == 20
    assert all(np.isnan(atr[:13]))   # first 13 bars = NaN
    assert not np.isnan(atr[13])      # bar 14 has ATR


def test_rolling_high20():
    df = DummyData.make(25)
    df.columns = ["date","open","high","low","close","volume"]
    result = compute_indicators(df)
    assert "high20" in result.columns
    assert result["high20"].notna().sum() == 6   # bars 20-25


def test_sma200_requires_200_bars():
    df = DummyData.make(210)
    df.columns = ["date","open","high","low","close","volume"]
    result = compute_indicators(df)
    assert result["sma200"].notna().sum() == 10  # bars 201-210
