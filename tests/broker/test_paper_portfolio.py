"""Tests for flowmacro.broker.paper_portfolio — paper trading P&L behavior."""
from datetime import date
from unittest.mock import patch, MagicMock
import pandas as pd
import pytest


def _empty_series():
    return pd.Series(dtype=float)


def _series(value: float, on: date):
    return pd.Series([value], index=[pd.Timestamp(on)])


# ── Cycle 7: first run initialises at $3,000 ─────────────────────────────────

@patch("flowmacro.broker.paper_portfolio.upsert_series")
@patch("flowmacro.broker.paper_portfolio.read_series")
def test_init_run_stores_initial_cash(mock_read, mock_upsert):
    mock_read.return_value = _empty_series()  # no prior state

    from flowmacro.broker.paper_portfolio import update, _INITIAL_CASH
    summary = update("TRANSITIONING", date(2026, 6, 6))

    assert "INITIALISED" in summary
    assert f"${_INITIAL_CASH:,.2f}" in summary
    mock_upsert.assert_called_once()
    stored_value = mock_upsert.call_args[0][1].iloc[0]
    assert stored_value == _INITIAL_CASH


# ── Cycle 8: TRANSITIONING regime → 0% P&L (GLD/SHY basket, flat prices) ────

@patch("flowmacro.broker.paper_portfolio._price_on")
@patch("flowmacro.broker.paper_portfolio.upsert_series")
@patch("flowmacro.broker.paper_portfolio.read_series")
def test_transitioning_regime_earns_zero(mock_read, mock_upsert, mock_price):
    last_date = date(2026, 5, 30)
    mock_read.side_effect = [
        _series(3000.0, last_date),      # paper_total_value
        _series(0.0,    last_date),      # regime_code = 0 = TRANSITIONING
    ]
    mock_price.return_value = 100.0      # p0 = p1 = 100 → 0% return on GLD/SHY

    from flowmacro.broker.paper_portfolio import update
    summary = update("TRANSITIONING", date(2026, 6, 6))

    stored_value = mock_upsert.call_args[0][1].iloc[0]
    assert stored_value == pytest.approx(3000.0)  # flat prices → value unchanged
    assert "Week P&L" in summary


# ── Cycle 9: DEFLATION regime → P&L from TLT/IEF/UUP returns ────────────────

@patch("flowmacro.broker.paper_portfolio._price_on")
@patch("flowmacro.broker.paper_portfolio.upsert_series")
@patch("flowmacro.broker.paper_portfolio.read_series")
def test_deflation_regime_applies_ticker_returns(mock_read, mock_upsert, mock_price):
    last_date = date(2026, 5, 30)
    mock_read.side_effect = [
        _series(3000.0, last_date),   # paper_total_value
        _series(4.0,    last_date),   # regime_code = 4 = DEFLATION
    ]

    # DEFLATION weights: TLT 40%, IEF 25%, UUP 15% (of 80% investable = 32%/20%/12%)
    # All prices up 10%
    mock_price.return_value = 110.0  # p1; p0 computed from same mock → 110/110 = 0%
    # Make p0 = 100, p1 = 110 → 10% return
    call_count = {"n": 0}
    def price_side(ticker, on):
        call_count["n"] += 1
        return 100.0 if call_count["n"] % 2 == 1 else 110.0
    mock_price.side_effect = price_side

    from flowmacro.broker.paper_portfolio import update
    summary = update("DEFLATION", date(2026, 6, 6))

    stored_value = mock_upsert.call_args[0][1].iloc[0]
    # Should be > $3,000 (positive return from bond positions)
    assert stored_value > 3000.0
    assert "Week P&L" in summary
    assert "Regime held: DEFLATION" in summary


# ── Cycle 10: already updated today → returns empty string ───────────────────

@patch("flowmacro.broker.paper_portfolio.upsert_series")
@patch("flowmacro.broker.paper_portfolio.read_series")
def test_no_double_update_same_day(mock_read, mock_upsert):
    today = date(2026, 6, 6)
    mock_read.return_value = _series(3000.0, today)  # last update = today

    from flowmacro.broker.paper_portfolio import update
    summary = update("GOLDILOCKS", today)

    assert summary == ""
    mock_upsert.assert_not_called()
