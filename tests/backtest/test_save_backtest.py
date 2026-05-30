import uuid
from unittest.mock import MagicMock
import pandas as pd
import pytest

from flowmacro.backtest.engine import save_backtest


def _result():
    return {
        "strategy":        {"sharpe_ratio": 1.2, "max_drawdown_pct": 15.0, "total_return_pct": 80.0},
        "benchmark_60_40": {"sharpe_ratio": 0.8, "max_drawdown_pct": 20.0, "total_return_pct": 50.0},
        "equity_curve":    pd.Series([100.0, 105.0, 102.0], index=pd.date_range("2020-01-01", periods=3)),
    }


def _mock_client():
    tables: dict = {}

    def _get_table(name: str):
        if name not in tables:
            t = MagicMock()
            t.upsert.return_value.execute.return_value = MagicMock()
            tables[name] = t
        return tables[name]

    m = MagicMock()
    m.table.side_effect = _get_table
    m._tables = tables  # expose for assertions
    return m


# ── Behavior 1: คืน UUID ────────────────────────────────────────────────────
def test_save_backtest_returns_uuid():
    run_id = save_backtest(_result(), client=_mock_client())
    uuid.UUID(run_id)  # raises ValueError if not a valid UUID


# ── Behavior 2: metrics บันทึกลง backtest_runs ────────────────────────────────
def test_save_backtest_writes_metrics_to_backtest_runs():
    client = _mock_client()
    save_backtest(_result(), client=client)

    assert "backtest_runs" in client._tables
    row = client._tables["backtest_runs"].upsert.call_args[0][0]
    assert row["sharpe_ratio"]          == pytest.approx(1.2)
    assert row["max_drawdown"]          == pytest.approx(15.0)
    assert row["annual_return"]         == pytest.approx(80.0)
    assert row["benchmark_sharpe"]      == pytest.approx(0.8)
    assert row["outperforms_benchmark"] is True  # 80% > 50%


# ── Behavior 3: equity curve บันทึกลง raw_series ────────────────────────────
def test_save_backtest_writes_equity_curve_to_raw_series():
    client = _mock_client()
    save_backtest(_result(), client=client)

    assert "raw_series" in client._tables
    rows = client._tables["raw_series"].upsert.call_args[0][0]
    series_ids = {r["series_id"] for r in rows}
    assert "equity_curve" in series_ids
    assert all("date" in r and "value" in r for r in rows)


# ── Behavior 4: ไม่มี equity_curve ใน result → ไม่ crash ─────────────────────
def test_save_backtest_without_equity_curve_does_not_raise():
    result_no_curve = {
        "strategy":        {"sharpe_ratio": 1.0, "max_drawdown_pct": 10.0, "total_return_pct": 60.0},
        "benchmark_60_40": {"sharpe_ratio": 0.7, "max_drawdown_pct": 12.0, "total_return_pct": 40.0},
    }
    run_id = save_backtest(result_no_curve, client=_mock_client())
    uuid.UUID(run_id)
