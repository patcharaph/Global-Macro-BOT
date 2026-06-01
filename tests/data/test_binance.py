import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
from flowmacro.data.sources.binance import fetch_btc_price, _to_ms


def _make_kline(open_time_ms: int, close: float) -> list:
    return [open_time_ms, "0", "0", "0", str(close), "0", 0, "0", 0, "0", "0", "0"]


def test_to_ms_known_date():
    ms = _to_ms("2020-01-01")
    assert ms == 1577836800000  # 2020-01-01 00:00:00 UTC


def test_returns_series_named_btcusd():
    batch = [_make_kline(1577836800000, 7200.0)]  # 2020-01-01
    mock_resp = MagicMock()
    mock_resp.json.return_value = batch
    mock_resp.raise_for_status.return_value = None

    with patch("flowmacro.data.sources.binance.requests.get", return_value=mock_resp):
        s = fetch_btc_price("2020-01-01", "2020-01-02")

    assert isinstance(s, pd.Series)
    assert s.name == "BTC-USD"
    assert len(s) == 1
    assert abs(s.iloc[0] - 7200.0) < 1e-6


def test_paginates_when_full_batch():
    batch1 = [_make_kline(1577836800000 + i * 86400000, float(i)) for i in range(1000)]
    batch2 = [_make_kline(1577836800000 + 1000 * 86400000, 999.0)]

    mock_resp1 = MagicMock()
    mock_resp1.json.return_value = batch1
    mock_resp1.raise_for_status.return_value = None

    mock_resp2 = MagicMock()
    mock_resp2.json.return_value = batch2
    mock_resp2.raise_for_status.return_value = None

    with patch("flowmacro.data.sources.binance.requests.get",
               side_effect=[mock_resp1, mock_resp2]):
        s = fetch_btc_price("2020-01-01")

    assert len(s) == 1001


def test_raises_on_empty_response():
    mock_resp = MagicMock()
    mock_resp.json.return_value = []
    mock_resp.raise_for_status.return_value = None

    with patch("flowmacro.data.sources.binance.requests.get", return_value=mock_resp):
        with pytest.raises(ValueError, match="no BTC/USDT data"):
            fetch_btc_price("2020-01-01")
