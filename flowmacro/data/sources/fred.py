import pandas as pd
from fredapi import Fred
from loguru import logger
from flowmacro.config import settings


def fetch_series(series_id: str, start: str, end: str | None = None) -> pd.Series:
    if not settings.fred_api_key:
        raise EnvironmentError("FRED_API_KEY not set in .env")

    fred = Fred(api_key=settings.fred_api_key)
    data = fred.get_series(series_id, observation_start=start, observation_end=end)

    if data is None or data.empty:
        raise ValueError(f"FRED: no data returned for {series_id} from {start}")

    nan_pct = data.isna().mean() * 100
    logger.debug(f"FRED {series_id}: {len(data)} rows, last={data.index[-1].date()}, NaN={nan_pct:.1f}%")
    return data
