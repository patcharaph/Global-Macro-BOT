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


def upsert_paper_portfolio_ml(
    run_date: str,
    ml_blend_probs: dict,
    ml_raw_probs: dict,
    rule_probs: dict,
    blend_weights: dict,
    portfolio_value: float,
    period_return: float,
    ml_regime: str,
    ml_confidence: float,
    ml_weight_used: float = 0.30,
) -> None:
    """Upsert one row into paper_portfolio_ml (Portfolio B virtual tracking)."""
    client = _client()

    def _f(d: dict) -> dict:
        return {k: float(v) for k, v in d.items()}

    row = {
        "date":            run_date,
        "ml_blend_probs":  _f(ml_blend_probs),
        "ml_raw_probs":    _f(ml_raw_probs),
        "rule_probs":      _f(rule_probs),
        "blend_weights":   _f(blend_weights),
        "portfolio_value": round(float(portfolio_value), 4),
        "period_return":   round(float(period_return), 6),
        "ml_regime":       ml_regime,
        "ml_confidence":   round(float(ml_confidence), 2),
        "ml_weight_used":  float(ml_weight_used),
    }
    _with_retry(
        lambda: client.table("paper_portfolio_ml").upsert(row, on_conflict="date").execute(),
        label="Supabase paper_portfolio_ml",
    )
    logger.debug(
        f"paper_portfolio_ml upsert: {run_date} ml={ml_regime} "
        f"conf={ml_confidence:.1f} value={portfolio_value:.2f}"
    )


def upsert_features_v2(run_date: str, features: dict) -> None:
    """Upsert one row into macro_features_v2 (conflict key: date)."""
    client = _client()
    row = {
        "date": run_date,
        **{k: (None if pd.isna(v) else float(v)) for k, v in features.items()},
    }
    _with_retry(
        lambda: client.table("macro_features_v2").upsert(row, on_conflict="date").execute(),
        label="Supabase macro_features_v2",
    )
    logger.debug(f"macro_features_v2 upsert: {run_date} ({len(features)} features)")


def read_features_v2(start: str = "2010-01-01") -> pd.DataFrame:
    """Read macro_features_v2 table. Returns DataFrame with date index.
    Paginates in 1000-row chunks to avoid PostgREST max_rows cap.
    """
    client = _client()
    all_rows: list = []
    page_size = 1000
    offset = 0
    while True:
        ref: list = []
        _with_retry(
            lambda off=offset: ref.append(
                client.table("macro_features_v2")
                .select("*")
                .gte("date", start)
                .order("date")
                .range(off, off + page_size - 1)
                .execute()
            ),
            label="Supabase read macro_features_v2",
        )
        batch = ref[0].data
        all_rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size
    if not all_rows:
        return pd.DataFrame()
    df = pd.DataFrame(all_rows)
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").drop(columns=["created_at"], errors="ignore")


def read_last_portfolio_b_weights(before_date: str) -> dict | None:
    """Read Portfolio B's blend_weights from the most recent row before before_date.

    Used for the weekly week-over-week allocation diff. Returns None if no
    prior row exists (first run) or the read fails.
    """
    client = _client()
    ref: list = []
    _with_retry(
        lambda: ref.append(
            client.table("paper_portfolio_ml")
            .select("date,blend_weights")
            .lt("date", before_date)
            .order("date", desc=True)
            .limit(1)
            .execute()
        ),
        label="Supabase read paper_portfolio_ml blend_weights",
    )
    rows = ref[0].data
    if not rows:
        return None
    return rows[0]["blend_weights"]


def read_paper_portfolio_ml(start: str = "2020-01-01") -> pd.DataFrame:
    """Read Portfolio B history. Returns DataFrame with date index and all columns."""
    client = _client()
    ref: list = []
    _with_retry(
        lambda: ref.append(
            client.table("paper_portfolio_ml")
            .select("date,portfolio_value,period_return,ml_regime,ml_confidence,ml_weight_used")
            .gte("date", start)
            .order("date")
            .execute()
        ),
        label="Supabase read paper_portfolio_ml",
    )
    rows = ref[0].data
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")


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
