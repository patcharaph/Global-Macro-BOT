"""Tests for flowmacro.broker.risk_guards — drawdown + weekly loss circuit breakers."""
import pytest
from datetime import date, timedelta
from unittest.mock import patch
import pandas as pd

from flowmacro.broker.risk_guards import (
    RiskGuardTripped,
    check_guards,
    record_value,
    _DD_LIMIT_PCT,
    _WK_LOSS_PCT,
    _MIN_VALUE_USD,
)


def _hist(*values, base_date=None):
    """Build a Series of weekly portfolio values ending today."""
    if base_date is None:
        base_date = date.today()
    dates = [pd.Timestamp(base_date) - timedelta(weeks=len(values) - 1 - i) for i in range(len(values))]
    return pd.Series(list(values), index=dates, dtype=float)


# ── Guard 1: Portfolio floor ──────────────────────────────────────────────────

def test_floor_raises_when_below_minimum():
    with pytest.raises(RiskGuardTripped, match="below floor"):
        check_guards(_MIN_VALUE_USD - 0.01)


def test_floor_passes_at_exactly_minimum():
    with patch("flowmacro.broker.risk_guards.read_series", return_value=pd.Series(dtype=float)):
        check_guards(_MIN_VALUE_USD)  # should not raise


# ── Guard 2: Drawdown from HWM ────────────────────────────────────────────────

@patch("flowmacro.broker.risk_guards.read_series")
def test_drawdown_passes_below_limit(mock_read):
    # 14% total drawdown from HWM, but spread over 2 weeks so weekly loss is ~7% (< 8% limit)
    hwm = 10_000.0
    mid  = hwm * 0.93   # week -1: -7% from HWM
    current = hwm * (1 - (_DD_LIMIT_PCT - 1) / 100)  # now: 14% from HWM, 7% from last week
    mock_read.return_value = _hist(hwm, mid)
    check_guards(current)  # should not raise


@patch("flowmacro.broker.risk_guards.read_series")
def test_drawdown_trips_at_limit(mock_read):
    hwm = 10_000.0
    too_much_dd = _DD_LIMIT_PCT + 1.0   # 16% drawdown → trip
    current = hwm * (1 - too_much_dd / 100)
    mock_read.return_value = _hist(hwm)
    with pytest.raises(RiskGuardTripped, match="Drawdown"):
        check_guards(current)


@patch("flowmacro.broker.risk_guards.read_series")
def test_drawdown_hwm_uses_history_max_not_most_recent(mock_read):
    # History: 10k → dipped to 8k → currently at 8.1k
    # HWM should be 10k (the peak), not 8k (the most recent)
    mock_read.return_value = _hist(10_000.0, 8_000.0)
    current = 8_100.0
    dd_from_hwm = (1 - 8_100 / 10_000) * 100  # 19% > 15% limit
    with pytest.raises(RiskGuardTripped, match="Drawdown"):
        check_guards(current)


@patch("flowmacro.broker.risk_guards.read_series")
def test_new_high_passes_drawdown(mock_read):
    # portfolio is at a new high — HWM = current_value, drawdown = 0%
    mock_read.return_value = _hist(9_000.0)
    check_guards(10_000.0)  # 10k > 9k HWM → no drawdown


# ── Guard 3: Single-week loss ─────────────────────────────────────────────────

@patch("flowmacro.broker.risk_guards.read_series")
def test_weekly_loss_passes_below_limit(mock_read):
    prev = 10_000.0
    safe_loss = _WK_LOSS_PCT - 1.0   # 7% weekly loss → safe
    current = prev * (1 - safe_loss / 100)
    mock_read.return_value = _hist(prev)
    check_guards(current)  # should not raise


@patch("flowmacro.broker.risk_guards.read_series")
def test_weekly_loss_trips_at_limit(mock_read):
    prev = 10_000.0
    too_much = _WK_LOSS_PCT + 1.0   # 9% weekly loss → trip
    current = prev * (1 - too_much / 100)
    mock_read.return_value = _hist(prev)
    with pytest.raises(RiskGuardTripped, match="Weekly loss"):
        check_guards(current)


@patch("flowmacro.broker.risk_guards.read_series")
def test_weekly_gain_never_trips(mock_read):
    mock_read.return_value = _hist(10_000.0)
    check_guards(11_000.0)  # +10% gain — should pass


# ── First run (no history) ────────────────────────────────────────────────────

@patch("flowmacro.broker.risk_guards.read_series")
def test_no_history_passes_all_guards(mock_read):
    mock_read.return_value = pd.Series(dtype=float)
    check_guards(5_000.0)  # no history → only floor guard applies


# ── Data error → fail-open ────────────────────────────────────────────────────

@patch("flowmacro.broker.risk_guards.read_series", side_effect=Exception("Supabase timeout"))
def test_data_read_error_allows_execution(mock_read):
    check_guards(10_000.0)  # data error → fail-open, should not raise


# ── record_value ──────────────────────────────────────────────────────────────

@patch("flowmacro.broker.risk_guards.upsert_series")
def test_record_value_stores_to_supabase(mock_upsert):
    record_value(12_345.67)
    mock_upsert.assert_called_once()
    series = mock_upsert.call_args[0][1]
    assert abs(float(series.iloc[0]) - 12_345.67) < 0.01


@patch("flowmacro.broker.risk_guards.upsert_series", side_effect=Exception("network error"))
def test_record_value_failure_does_not_raise(mock_upsert):
    record_value(10_000.0)  # upsert fails silently
