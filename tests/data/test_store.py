"""Tests for flowmacro.data.store — retry and upsert behavior."""
import time
from unittest.mock import MagicMock, patch, call
import pandas as pd
import pytest

from flowmacro.data.store import upsert_series


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
