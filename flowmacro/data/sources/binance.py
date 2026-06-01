from datetime import date, datetime, timezone
import pandas as pd
import requests
from loguru import logger

_BASE_URL = "https://api.binance.com"
_KLINES_LIMIT = 1000  # max candles per request


def fetch_btc_price(start: str, end: str | None = None) -> pd.Series:
    """Fetch BTC/USDT daily close price from Binance public API.

    Returns a date-indexed Series named 'BTC-USD'. Paginates automatically
    to fetch beyond the 1000-candle per-request limit. No API key required.
    """
    start_ms = _to_ms(start)
    end_ms = _to_ms(end) if end else None

    all_rows: list[list] = []

    while True:
        params: dict = {
            "symbol": "BTCUSDT",
            "interval": "1d",
            "startTime": start_ms,
            "limit": _KLINES_LIMIT,
        }
        if end_ms is not None:
            params["endTime"] = end_ms

        resp = requests.get(
            f"{_BASE_URL}/api/v3/klines", params=params, timeout=30
        )
        resp.raise_for_status()
        batch = resp.json()

        if not batch:
            break

        all_rows.extend(batch)

        if len(batch) < _KLINES_LIMIT:
            break

        # Advance past the last returned candle's open time
        start_ms = batch[-1][0] + 1

    if not all_rows:
        raise ValueError(f"Binance: no BTC/USDT data from {start}")

    # Kline columns: [open_time, open, high, low, close, volume, ...]
    dates = [
        datetime.fromtimestamp(row[0] / 1000, tz=timezone.utc).date()
        for row in all_rows
    ]
    closes = [float(row[4]) for row in all_rows]

    series = pd.Series(closes, index=pd.to_datetime(dates), name="BTC-USD")
    series.index.name = "Date"

    stale = (date.today() - series.index[-1].date()).days
    logger.debug(
        f"Binance BTC-USD: {len(series)} rows, "
        f"last={series.index[-1].date()}, stale={stale}d"
    )
    return series


def _to_ms(date_str: str) -> int:
    """Convert 'YYYY-MM-DD' to UTC millisecond timestamp."""
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)
