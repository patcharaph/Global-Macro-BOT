"""Tests for flowmacro.data.store — retry and upsert behavior."""
import time
from unittest.mock import MagicMock, patch, call
import pandas as pd
import pytest

from flowmacro.data.store import upsert_series, upsert_regime_history, upsert_ml_regime_history, read_series


def _make_client(fail_times: int = 0):
    """Return a mock Supabase client whose upsert fails `fail_times` then succeeds."""
    client = MagicMock()
    call_count = {"n": 0}

    def _execute():
        call_count["n"] += 1
        if call_count["n"] <= fail_times:
            raise ConnectionError("transient network error")

    table_mock = MagicMock()
    table_mock.upsert.return_value.execute.side_effect = _execute
    client.table.return_value = table_mock
    return client


@pytest.fixture
def series():
    idx = pd.date_range("2024-01-01", periods=3, freq="D")
    return pd.Series([1.0, 2.0, 3.0], index=idx, name="TEST")


# ── Cycle 1: retry succeeds after transient failure ───────────────────────────

@patch("flowmacro.data.store.time.sleep")
@patch("flowmacro.data.store._client")
def test_upsert_retries_on_transient_failure(mock_client, mock_sleep, series):
    mock_client.return_value = _make_client(fail_times=1)
    rows_written = upsert_series("TEST", series)
    assert rows_written == 3
    mock_sleep.assert_called_once_with(2)  # one retry with base delay


# ── Cycle 2: raises after all retries exhausted ───────────────────────────────

@patch("flowmacro.data.store.time.sleep")
@patch("flowmacro.data.store._client")
def test_upsert_raises_after_all_retries_fail(mock_client, mock_sleep, series):
    mock_client.return_value = _make_client(fail_times=99)
    with pytest.raises(ConnectionError, match="transient network error"):
        upsert_series("TEST", series)
    assert mock_sleep.call_count == 2  # retried twice before giving up


# ── Cycle 3: exponential backoff delays double each attempt ──────────────────

@patch("flowmacro.data.store.time.sleep")
@patch("flowmacro.data.store._client")
def test_upsert_backoff_doubles(mock_client, mock_sleep, series):
    mock_client.return_value = _make_client(fail_times=99)
    with pytest.raises(ConnectionError):
        upsert_series("TEST", series)
    delays = [c.args[0] for c in mock_sleep.call_args_list]
    assert delays == [2, 4]  # 2s → 4s (doubles each attempt)


# ── upsert_regime_history retry ───────────────────────────────────────────────

@patch("flowmacro.data.store.time.sleep")
@patch("flowmacro.data.store._client")
def test_upsert_regime_history_retries_on_transient_failure(mock_client, mock_sleep):
    mock_client.return_value = _make_client(fail_times=1)
    upsert_regime_history("2026-06-06", "GOLDILOCKS", 50.0, 75.0, 25.0)
    mock_sleep.assert_called_once_with(2)


@patch("flowmacro.data.store.time.sleep")
@patch("flowmacro.data.store._client")
def test_upsert_regime_history_raises_after_all_retries(mock_client, mock_sleep):
    mock_client.return_value = _make_client(fail_times=99)
    with pytest.raises(ConnectionError):
        upsert_regime_history("2026-06-06", "GOLDILOCKS", 50.0, 75.0, 25.0)
    assert [c.args[0] for c in mock_sleep.call_args_list] == [2, 4]


# ── read_series retry ─────────────────────────────────────────────────────────

def _make_read_client(fail_times: int = 0):
    """Mock Supabase client whose select chain fails `fail_times` then returns empty."""
    client = MagicMock()
    call_count = {"n": 0}

    def _execute():
        call_count["n"] += 1
        if call_count["n"] <= fail_times:
            raise ConnectionError("transient network error")
        result = MagicMock()
        result.data = []
        return result

    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.gte.return_value = chain
    chain.lte.return_value = chain
    chain.order.return_value = chain
    chain.range.return_value = MagicMock(execute=_execute)
    client.table.return_value = chain
    return client


@patch("flowmacro.data.store.time.sleep")
@patch("flowmacro.data.store._client")
def test_read_series_retries_on_transient_failure(mock_client, mock_sleep):
    mock_client.return_value = _make_read_client(fail_times=1)
    result = read_series("TEST", start="2024-01-01")
    assert result.empty
    mock_sleep.assert_called_once_with(2)


@patch("flowmacro.data.store.time.sleep")
@patch("flowmacro.data.store._client")
def test_read_series_raises_after_all_retries(mock_client, mock_sleep):
    mock_client.return_value = _make_read_client(fail_times=99)
    with pytest.raises(ConnectionError):
        read_series("TEST", start="2024-01-01")
    assert [c.args[0] for c in mock_sleep.call_args_list] == [2, 4]


# ── upsert_ml_regime_history retry ───────────────────────────────────────────

@patch("flowmacro.data.store.time.sleep")
@patch("flowmacro.data.store._client")
def test_upsert_ml_regime_history_retries_on_transient_failure(mock_client, mock_sleep):
    mock_client.return_value = _make_client(fail_times=1)
    upsert_ml_regime_history("2026-06-06", "GOLDILOCKS", 80.0, "GOLDILOCKS")
    mock_sleep.assert_called_once_with(2)
