"""Tests for flowmacro.backtest.engine.run_backtest — output contract."""
import pandas as pd
import pytest

from flowmacro.backtest.engine import run_backtest


def _minimal_prices():
    idx = pd.date_range("2020-01-03", periods=5, freq="D")
    return pd.DataFrame({
        "SPY": [300.0, 301.0, 302.0, 301.0, 303.0],
        "TLT": [140.0, 141.0, 140.0, 142.0, 141.0],
    }, index=idx)


def _regime(prices):
    return pd.Series(["DEFLATION"], index=prices.index[:1])


# ── Behavior A: returns equity_curve_spy when SPY in prices ──────────────────

def test_run_backtest_returns_spy_curve_when_spy_in_prices():
    prices = _minimal_prices()
    result = run_backtest(prices, _regime(prices))
    assert "equity_curve_spy" in result
    assert not result["equity_curve_spy"].empty
    assert result["equity_curve_spy"].iloc[0] == pytest.approx(100.0)

