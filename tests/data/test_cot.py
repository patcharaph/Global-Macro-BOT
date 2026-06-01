import io
import zipfile
import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
from flowmacro.data.sources.cot import fetch_cot_net, MARKET_SERIES, _COL_MARKET, _COL_DATE, _COL_LONG, _COL_SHORT


def _make_zip_bytes(rows: list[dict]) -> bytes:
    """Build a minimal CFTC-format ZIP in memory."""
    df = pd.DataFrame(rows)
    csv_bytes = df.to_csv(index=False).encode()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("annual.txt", csv_bytes)
    return buf.getvalue()


def _good_rows(market: str, n: int = 3) -> list[dict]:
    return [
        {
            _COL_MARKET: market,
            _COL_DATE:   f"2024-01-{i+1:02d}",
            _COL_LONG:   str(100_000 + i * 1_000),
            _COL_SHORT:  str(50_000),
        }
        for i in range(n)
    ]


@pytest.fixture
def mock_cftc(monkeypatch):
    """Patch requests.get to return a minimal CFTC ZIP for any year."""
    rows = _good_rows("E-MINI S&P 500 STOCK INDEX - CME")
    zip_bytes = _make_zip_bytes(rows)

    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.content = zip_bytes
    monkeypatch.setattr("flowmacro.data.sources.cot.requests.get", lambda *a, **kw: mock_resp)
    return mock_resp


def test_fetch_returns_series(mock_cftc):
    s = fetch_cot_net("cot_sp500_net", "2024-01-01", end="2024-12-31")
    assert isinstance(s, pd.Series)
    assert s.name == "cot_sp500_net"
    assert len(s) == 3


def test_net_is_long_minus_short(mock_cftc):
    s = fetch_cot_net("cot_sp500_net", "2024-01-01", end="2024-12-31")
    # row 0: long=100_000, short=50_000 → net=50_000
    assert s.iloc[0] == pytest.approx(50_000)


def test_unknown_series_raises():
    with pytest.raises(ValueError, match="Unknown COT series_id"):
        fetch_cot_net("cot_unknown_net", "2024-01-01")


def test_market_not_found_raises(monkeypatch):
    rows = _good_rows("SOME OTHER MARKET - EXCHANGE")
    zip_bytes = _make_zip_bytes(rows)
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.content = zip_bytes
    monkeypatch.setattr("flowmacro.data.sources.cot.requests.get", lambda *a, **kw: mock_resp)

    with pytest.raises(ValueError, match="No market matched"):
        fetch_cot_net("cot_sp500_net", "2024-01-01", end="2024-12-31")


def test_missing_columns_raises(monkeypatch):
    # Column errors are logged as warnings; all years fail → raises "No COT data fetched"
    df = pd.DataFrame([{"col_a": 1, "col_b": 2}])
    csv_bytes = df.to_csv(index=False).encode()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("annual.txt", csv_bytes)

    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.content = buf.getvalue()
    monkeypatch.setattr("flowmacro.data.sources.cot.requests.get", lambda *a, **kw: mock_resp)

    with pytest.raises(ValueError, match="No COT data fetched"):
        fetch_cot_net("cot_sp500_net", "2024-01-01", end="2024-12-31")


def test_all_series_ids_valid():
    valid = set(MARKET_SERIES.keys())
    assert "cot_sp500_net" in valid
    assert "cot_treasury10y_net" in valid
    assert "cot_gold_net" in valid
    assert "cot_crude_net" in valid


def test_date_filter_applied(mock_cftc):
    # start=2024-01-03 should exclude row at 01/01/2024
    s = fetch_cot_net("cot_sp500_net", "2024-01-03", end="2024-12-31")
    assert all(s.index >= pd.Timestamp("2024-01-03"))
