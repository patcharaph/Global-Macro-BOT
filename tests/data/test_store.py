"""Tests for flowmacro.data.store — retry and upsert behavior."""
import time
from unittest.mock import MagicMock, patch, call
import pandas as pd
import pytest

from flowmacro.data.store import (
    upsert_series, upsert_regime_history, upsert_ml_regime_history, read_series,
    upsert_paper_portfolio_ml, read_paper_portfolio_ml,
)


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


# ── upsert_paper_portfolio_ml ─────────────────────────────────────────────────

_PML_ARGS = dict(
    run_date="2026-06-13",
    ml_blend_probs={"GOLDILOCKS": 0.5, "REFLATION": 0.2, "STAGFLATION": 0.15, "DEFLATION": 0.15},
    ml_raw_probs={"GOLDILOCKS": 0.7, "REFLATION": 0.1, "STAGFLATION": 0.1, "DEFLATION": 0.1},
    rule_probs={"GOLDILOCKS": 0.4, "REFLATION": 0.25, "STAGFLATION": 0.2, "DEFLATION": 0.15},
    blend_weights={"SPY": 0.2, "GLD": 0.3},
    portfolio_value=3_045.50,
    period_return=0.0152,
    ml_regime="GOLDILOCKS",
    ml_confidence=70.0,
)


@patch("flowmacro.data.store.time.sleep")
@patch("flowmacro.data.store._client")
def test_upsert_paper_portfolio_ml_retries_on_transient_failure(mock_client, mock_sleep):
    mock_client.return_value = _make_client(fail_times=1)
    upsert_paper_portfolio_ml(**_PML_ARGS)
    mock_sleep.assert_called_once_with(2)


@patch("flowmacro.data.store.time.sleep")
@patch("flowmacro.data.store._client")
def test_upsert_paper_portfolio_ml_raises_after_all_retries(mock_client, mock_sleep):
    mock_client.return_value = _make_client(fail_times=99)
    with pytest.raises(ConnectionError):
        upsert_paper_portfolio_ml(**_PML_ARGS)
    assert [c.args[0] for c in mock_sleep.call_args_list] == [2, 4]


# ── read_paper_portfolio_ml ───────────────────────────────────────────────────

def _make_pml_read_client(fail_times: int = 0, rows: list | None = None):
    """Mock for read_paper_portfolio_ml — chain: select → gte → order → execute."""
    client = MagicMock()
    call_count = {"n": 0}
    _rows = rows if rows is not None else []

    def _execute():
        call_count["n"] += 1
        if call_count["n"] <= fail_times:
            raise ConnectionError("transient network error")
        result = MagicMock()
        result.data = _rows
        return result

    chain = MagicMock()
    chain.select.return_value = chain
    chain.gte.return_value = chain
    chain.order.return_value = MagicMock(execute=_execute)
    client.table.return_value = chain
    return client


@patch("flowmacro.data.store.time.sleep")
@patch("flowmacro.data.store._client")
def test_read_paper_portfolio_ml_retries_on_transient_failure(mock_client, mock_sleep):
    mock_client.return_value = _make_pml_read_client(fail_times=1, rows=[])
    result = read_paper_portfolio_ml()
    assert result.empty
    mock_sleep.assert_called_once_with(2)


@patch("flowmacro.data.store.time.sleep")
@patch("flowmacro.data.store._client")
def test_read_paper_portfolio_ml_raises_after_all_retries(mock_client, mock_sleep):
    mock_client.return_value = _make_pml_read_client(fail_times=99)
    with pytest.raises(ConnectionError):
        read_paper_portfolio_ml()
    assert [c.args[0] for c in mock_sleep.call_args_list] == [2, 4]


@patch("flowmacro.data.store.time.sleep")
@patch("flowmacro.data.store._client")
def test_read_paper_portfolio_ml_returns_empty_dataframe_when_no_rows(mock_client, mock_sleep):
    mock_client.return_value = _make_pml_read_client(rows=[])
    result = read_paper_portfolio_ml()
    assert isinstance(result, pd.DataFrame)
    assert result.empty


_PML_ROWS = [
    {
        "date": "2026-06-06",
        "portfolio_value": 3_012.50,
        "period_return": 0.0042,
        "ml_regime": "GOLDILOCKS",
        "ml_confidence": 68.0,
        "ml_weight_used": 0.30,
    },
    {
        "date": "2026-06-13",
        "portfolio_value": 3_045.80,
        "period_return": 0.0111,
        "ml_regime": "REFLATION",
        "ml_confidence": 55.5,
        "ml_weight_used": 0.30,
    },
]


@patch("flowmacro.data.store.time.sleep")
@patch("flowmacro.data.store._client")
def test_read_paper_portfolio_ml_returns_date_indexed_dataframe(mock_client, mock_sleep):
    mock_client.return_value = _make_pml_read_client(rows=_PML_ROWS)
    result = read_paper_portfolio_ml()

    assert isinstance(result.index, pd.DatetimeIndex)
    assert len(result) == 2
    assert list(result.columns) == [
        "portfolio_value", "period_return",
        "ml_regime", "ml_confidence", "ml_weight_used",
    ]
    assert result.index[0] == pd.Timestamp("2026-06-06")
    assert result["portfolio_value"].iloc[0] == pytest.approx(3_012.50)
    assert result["ml_regime"].iloc[1] == "REFLATION"
