import time
import pandas as pd
from loguru import logger
from flowmacro.config import settings

_BATCH = 500
_RETRIES = 3
_RETRY_BASE_DELAY = 2  # seconds; doubles each attempt


def _client():
    if not settings.supabase_url or not settings.supabase_key:
        raise EnvironmentError("SUPABASE_URL and SUPABASE_KEY must be set in .env")
    from supabase import create_client
    return create_client(settings.supabase_url, settings.supabase_key)


def _with_retry(fn, label: str = "Supabase") -> None:
    """Call fn() with exponential-backoff retry."""
    delay = _RETRY_BASE_DELAY
    for attempt in range(1, _RETRIES + 1):
        try:
            fn()
            return
        except Exception as exc:
            if attempt == _RETRIES:
                raise
            logger.warning(f"{label} attempt {attempt}/{_RETRIES} failed: {exc} — retrying in {delay}s")
            time.sleep(delay)
            delay *= 2


def _upsert_batch(client, rows: list[dict]) -> None:
    _with_retry(
        lambda: client.table("raw_series").upsert(rows, on_conflict="series_id,date").execute(),
        label="Supabase upsert batch",
    )


def upsert_series(series_id: str, data: pd.Series) -> int:
    """Upsert a time series into raw_series. Returns number of rows written."""
    client = _client()
    rows = [
        {"series_id": series_id, "date": str(idx.date()), "value": float(val)}
        for idx, val in data.items()
        if pd.notna(val)
    ]
    for i in range(0, len(rows), _BATCH):
        _upsert_batch(client, rows[i : i + _BATCH])
    logger.debug(f"Supabase upsert {series_id}: {len(rows)} rows")
    return len(rows)


def upsert_regime_history(
    run_date: str,
    regime: str,
    confidence: float,
    growth_score: float,
    inflation_score: float,
) -> None:
    """Upsert one row into regime_history (conflict key: run_date)."""
    client = _client()
    row = {
        "run_date":        run_date,
        "regime":          regime,
        "confidence":      round(confidence, 2),
        "growth_score":    round(growth_score, 2),
        "inflation_score": round(inflation_score, 2),
    }
    _with_retry(
        lambda: client.table("regime_history").upsert(row, on_conflict="run_date").execute(),
        label="Supabase regime_history",
    )
    logger.debug(f"regime_history upsert: {run_date} {regime} conf={confidence:.1f}")


def upsert_ml_regime_history(
    run_date: str,
    ml_regime: str,
    ml_confidence: float,
    rb_regime: str,
) -> None:
    """Upsert one row into regime_history_ml (shadow mode tracking table)."""
    client = _client()
    row = {
        "run_date":      run_date,
        "ml_regime":     ml_regime,
        "ml_confidence": round(float(ml_confidence), 2),
        "rb_regime":     rb_regime,
        "agrees":        ml_regime == rb_regime,
    }
    _with_retry(
        lambda: client.table("regime_history_ml").upsert(row, on_conflict="run_date").execute(),
        label="Supabase regime_history_ml",
    )
    logger.debug(
        f"regime_history_ml upsert: {run_date} ml={ml_regime} rb={rb_regime} "
        f"agrees={ml_regime == rb_regime}"
    )


def _fetch_page(client, series_id: str, start: str, end: str | None, offset: int, page: int):
    query = (
        client.table("raw_series")
        .select("date, value")
        .eq("series_id", series_id)
        .gte("date", start)
    )
    if end:
        query = query.lte("date", end)
    return query.order("date").range(offset, offset + page - 1).execute()


def read_series(series_id: str, start: str, end: str | None = None) -> pd.Series:
    """Read a time series from raw_series. Paginates to bypass PostgREST row limit."""
    client = _client()
    all_rows: list[dict] = []
    page = 1000
    offset = 0

    while True:
        ref: list = []
        _with_retry(
            lambda o=offset: ref.append(_fetch_page(client, series_id, start, end, o, page)),
            label=f"Supabase read {series_id}",
        )
        result = ref[0]
        all_rows.extend(result.data)
        if len(result.data) < page:
            break
        offset += page

    if not all_rows:
        return pd.Series(dtype=float, name=series_id)

    df = pd.DataFrame(all_rows)
    return df.set_index(pd.to_datetime(df["date"]))["value"].rename(series_id)
