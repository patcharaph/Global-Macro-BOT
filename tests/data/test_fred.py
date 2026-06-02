"""Tests for flowmacro.data.sources.fred — retry behavior."""
from unittest.mock import MagicMock, patch
import pandas as pd
import pytest


def _make_fred(fail_times: int = 0, return_empty: bool = False):
    """Return a mock Fred object whose get_series fails `fail_times` then succeeds."""
    fred = MagicMock()
    call_count = {"n": 0}
    idx = pd.date_range("2024-01-01", periods=3, freq="MS")
    good_data = pd.Series([1.0, 2.0, 3.0], index=idx)

    def _get_series(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] <= fail_times:
            raise ConnectionError("FRED API timeout")
        return pd.Series(dtype=float) if return_empty else good_data

    fred.get_series.side_effect = _get_series
    return fred


# ── Cycle 4: FRED succeeds after transient failure ────────────────────────────

@patch("flowmacro.data.sources.fred.time.sleep")
@patch("flowmacro.data.sources.fred.Fred")
@patch("flowmacro.data.sources.fred.settings")
def test_fred_retries_on_transient_failure(mock_settings, mock_Fred, mock_sleep):
    mock_settings.fred_api_key = "test-key"
    mock_Fred.return_value = _make_fred(fail_times=1)

    from flowmacro.data.sources.fred import fetch_series
    result = fetch_series("T10Y2Y", start="2024-01-01")

    assert len(result) == 3
    mock_sleep.assert_called_once_with(5)  # one retry with base delay


# ── Cycle 5: raises after all retries exhausted ───────────────────────────────

@patch("flowmacro.data.sources.fred.time.sleep")
@patch("flowmacro.data.sources.fred.Fred")
@patch("flowmacro.data.sources.fred.settings")
def test_fred_raises_after_all_retries_fail(mock_settings, mock_Fred, mock_sleep):
    mock_settings.fred_api_key = "test-key"
    mock_Fred.return_value = _make_fred(fail_times=99)

    from flowmacro.data.sources.fred import fetch_series
    with pytest.raises(ConnectionError, match="FRED API timeout"):
        fetch_series("T10Y2Y", start="2024-01-01")
    assert mock_sleep.call_count == 2  # retried twice before giving up


# ── Cycle 6: raises on empty data (no retry — not transient) ─────────────────

@patch("flowmacro.data.sources.fred.time.sleep")
@patch("flowmacro.data.sources.fred.Fred")
@patch("flowmacro.data.sources.fred.settings")
def test_fred_raises_on_empty_response(mock_settings, mock_Fred, mock_sleep):
    mock_settings.fred_api_key = "test-key"
    mock_Fred.return_value = _make_fred(return_empty=True)

    from flowmacro.data.sources.fred import fetch_series
    with pytest.raises(ValueError, match="no data returned"):
        fetch_series("UNKNOWN_SERIES", start="2024-01-01")
