import pandas as pd
from loguru import logger
from flowmacro.config import settings

_BATCH = 500


def _client():
    if not settings.supabase_url or not settings.supabase_key:
        raise EnvironmentError("SUPABASE_URL and SUPABASE_KEY must be set in .env")
    from supabase import create_client
    return create_client(settings.supabase_url, settings.supabase_key)


def upsert_series(series_id: str, data: pd.Series) -> int:
    """Upsert a time series into raw_series. Returns number of rows written."""
    client = _client()
    rows = [
        {"series_id": series_id, "date": str(idx.date()), "value": float(val)}
        for idx, val in data.items()
        if pd.notna(val)
    ]
    for i in range(0, len(rows), _BATCH):
        client.table("raw_series").upsert(rows[i : i + _BATCH]).execute()
    logger.debug(f"Supabase upsert {series_id}: {len(rows)} rows")
    return len(rows)


def read_series(series_id: str, start: str, end: str | None = None) -> pd.Series:
    """Read a time series from raw_series. Returns date-indexed Series."""
    client = _client()
    query = (
        client.table("raw_series")
        .select("date, value")
        .eq("series_id", series_id)
        .gte("date", start)
    )
    if end:
        query = query.lte("date", end)
    result = query.order("date").execute()

    if not result.data:
        return pd.Series(dtype=float, name=series_id)

    df = pd.DataFrame(result.data)
    return df.set_index(pd.to_datetime(df["date"]))["value"].rename(series_id)
