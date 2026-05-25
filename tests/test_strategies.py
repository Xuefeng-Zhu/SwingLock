"""
tests/test_strategies.py
Unit tests for strategy components.

Run: pytest tests/test_strategies.py -v
"""

import pytest, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import numpy as np
import pandas as pd
from strategies import trend_filter, breakout_20d_signal, atr_stop_price, stop_distance


def test_trend_filter_bull():
    close   = pd.Series([100, 101, 103, 105])
    sma200  = pd.Series([95,  95,  95,  95])
    result  = trend_filter(close, sma200)
    assert result.all()


def test_trend_filter_bear():
    close   = pd.Series([90, 88, 86, 84])
    sma200  = pd.Series([95, 95, 95, 95])
    result  = trend_filter(close, sma200)
    assert not result.any()


def test_breakout_signal_requires_lag():
    close   = pd.Series([100]*25)
    high    = pd.Series([102]*25)
    high20  = pd.Series(list(np.arange(95, 100)) + [100]*5)
    volume  = pd.Series([1e6]*25)
    vol_sma = pd.Series([5e5]*25)

    sig = breakout_20d_signal(close, high, high20, volume, vol_sma)
    # Before bar 21 (lag index 20), signal is False
    assert not sig.iloc[20]  # lag index
    # At bar 21+: may be True
    assert isinstance(sig.iloc[-1], bool)


def test_atr_stop_price():
    stop = atr_stop_price(entry_price=100.0, atr14=2.0, multiplier=2.0)
    assert stop == 96.0   # 100 - 2*2

    # Floor at 2%
    stop2 = atr_stop_price(entry_price=100.0, atr14=0.5, multiplier=2.0)
    assert stop2 == 98.0  # max(100-1.0, 100*0.98) = 98


def test_stop_distance():
    dist = stop_distance(entry_price=100.0, atr14=2.0, multiplier=2.0)
    assert dist == 4.0
