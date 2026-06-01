"""
CFTC Legacy COT (Futures-Only) data fetcher.

Downloads annual ZIP files from CFTC and extracts net speculative positions
(NonCommercial Long - Short) for four macro-relevant futures markets.

Release schedule: every Friday (data as of Tuesday of that week).
"""
import io
import zipfile
from datetime import date
import pandas as pd
import requests
from loguru import logger

_COT_URL = "https://www.cftc.gov/files/dea/history/deacot{year}.zip"
_TIMEOUT = 60  # CFTC can be slow

# Market matching rules per series_id.
# match: case-insensitive substring (supports | for multiple patterns)
# exclude: optional case-insensitive substring to reject (e.g. "MICRO", "ULTRA")
MARKET_SERIES: dict[str, dict] = {
    "cot_sp500_net": {
        "match":   "E-MINI S&P 500",
        "exclude": "MICRO",
    },
    "cot_treasury10y_net": {
        # Name changed ~2022: "10-YEAR U.S. TREASURY NOTES" → "UST 10Y NOTE"
        "match":   "10-YEAR U.S. TREASURY NOTES|UST 10Y NOTE",
        "exclude": "ULTRA",
    },
    "cot_gold_net": {
        "match":   "GOLD - COMMODITY EXCHANGE",
        "exclude": "MICRO",
    },
    "cot_crude_net": {
        # Physical WTI on NYMEX, stable across years
        "match":   "WTI FINANCIAL CRUDE OIL",
        "exclude": None,
    },
}

_COL_MARKET = "Market and Exchange Names"
_COL_DATE   = "As of Date in Form YYYY-MM-DD"
_COL_LONG   = "Noncommercial Positions-Long (All)"
_COL_SHORT  = "Noncommercial Positions-Short (All)"


def fetch_cot_net(series_id: str, start: str, end: str | None = None) -> pd.Series:
    """Fetch weekly net speculative position for a CFTC futures market.

    series_id must be one of: cot_sp500_net, cot_treasury10y_net,
    cot_gold_net, cot_crude_net.

    Returns a weekly date-indexed pd.Series. Net = NonComm Long - Short.
    """
    if series_id not in MARKET_SERIES:
        raise ValueError(
            f"Unknown COT series_id '{series_id}'. "
            f"Valid: {list(MARKET_SERIES)}"
        )

    rule = MARKET_SERIES[series_id]
    match_pat   = rule["match"].upper()
    exclude_pat = rule.get("exclude")

    start_year = int(start[:4])
    end_year = int(end[:4]) if end else date.today().year

    frames: list[pd.DataFrame] = []
    for year in range(start_year, end_year + 1):
        try:
            df = _download_year(year)
            frames.append(df)
        except Exception as exc:
            logger.warning(f"COT {year}: skipped — {exc}")

    if not frames:
        raise ValueError(f"No COT data fetched for {series_id} ({start} – {end})")

    combined = pd.concat(frames, ignore_index=True)
    names_upper = combined[_COL_MARKET].str.upper()

    # Support "|" for multi-pattern match (e.g. old name | new name)
    mask = names_upper.str.contains(match_pat, na=False, regex=True)
    if exclude_pat:
        mask = mask & ~names_upper.str.contains(exclude_pat.upper(), na=False)

    filtered = combined[mask].copy()

    if filtered.empty:
        raise ValueError(
            f"No market matched series_id='{series_id}' "
            f"(match='{rule['match']}', exclude='{exclude_pat}'). "
            f"Sample markets: {combined[_COL_MARKET].unique()[:5].tolist()}"
        )

    filtered["date"] = pd.to_datetime(filtered[_COL_DATE], format="%Y-%m-%d")
    filtered["net"] = (
        pd.to_numeric(filtered[_COL_LONG], errors="coerce")
        - pd.to_numeric(filtered[_COL_SHORT], errors="coerce")
    )

    series = (
        filtered.set_index("date")["net"]
        .sort_index()
        .dropna()
        .rename(series_id)
    )

    # Apply start/end filter
    series = series[series.index >= pd.Timestamp(start)]
    if end:
        series = series[series.index <= pd.Timestamp(end)]

    logger.debug(
        f"COT {series_id}: {len(series)} weekly rows, "
        f"last={series.index[-1].date() if not series.empty else 'n/a'}"
    )
    return series


def _download_year(year: int) -> pd.DataFrame:
    """Download and parse one year of CFTC Legacy COT data."""
    url = _COT_URL.format(year=year)
    logger.debug(f"COT download: {url}")

    resp = requests.get(url, timeout=_TIMEOUT)
    resp.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        # The file inside can vary: annual.txt, deacot<year>.txt, etc.
        names = zf.namelist()
        csv_name = next(
            (n for n in names if n.lower().endswith(".txt")), names[0]
        )
        with zf.open(csv_name) as f:
            df = pd.read_csv(f, low_memory=False)

    _assert_columns(df, year)
    return df[[_COL_MARKET, _COL_DATE, _COL_LONG, _COL_SHORT]]


def _assert_columns(df: pd.DataFrame, year: int) -> None:
    required = {_COL_MARKET, _COL_DATE, _COL_LONG, _COL_SHORT}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(
            f"COT {year}: unexpected CSV columns. Missing: {missing}. "
            f"Got: {list(df.columns[:8])}"
        )
