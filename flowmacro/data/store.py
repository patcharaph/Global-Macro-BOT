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
        client.table("raw_series").upsert(rows[i : i + _BATCH], on_conflict="series_id,date").execute()
    logger.debug(f"Supabase upsert {series_id}: {len(rows)} rows")
    return len(rows)


def read_series(series_id: str, start: str, end: str | None = None) -> pd.Series:
    """Read a time series from raw_series. Paginates to bypass PostgREST row limit."""
    client = _client()
    all_rows: list[dict] = []
    page = 1000

    offset = 0
    while True:
        query = (
            client.table("raw_series")
            .select("date, value")
            .eq("series_id", series_id)
            .gte("date", start)
        )
        if end:
            query = query.lte("date", end)
        result = query.order("date").range(offset, offset + page - 1).execute()
        all_rows.extend(result.data)
        if len(result.data) < page:
            break
        offset += page

    if not all_rows:
        return pd.Series(dtype=float, name=series_id)

    df = pd.DataFrame(all_rows)
    return df.set_index(pd.to_datetime(df["date"]))["value"].rename(series_id)
