"""
XGBoost v2 feature engineering — 14 new leading/price indicators.

Group 2 — Macro Leading (5):
  hy_spread_pr, tips_breakeven_5y_pr, china_pmi_pr,
  copper_gold_ratio_pr, policy_forward_signal_pr

Group 3 — Price-Based Leading (9):
  spy_return_26w, spy_return_52w, eem_return_26w, tlt_return_13w,
  yield_curve_momentum_4w, dxy_return_13w, dbc_return_13w,
  gld_return_13w, hy_spread_momentum_4w

Rules (from spec):
  FRED series         → percentile_rank(260W)  before storing
  Price returns       → pct_change(N weeks) first, then percentile_rank
  Momentum (4W delta) → raw delta, NO percentile_rank
  China PMI (monthly) → resample("W-FRI").last().ffill()
  FRED failure        → log warning + skip (don't raise)
  yfinance            → retry 3× with exponential backoff
"""
import time
import pandas as pd
from loguru import logger

_PR_WINDOW  = 260   # 5 years of weekly data
_YF_RETRIES = 3
_YF_DELAY   = 5     # seconds; doubles each retry


# ── helpers ──────────────────────────────────────────────────────────────────

def percentile_rank(series: pd.Series, window: int = _PR_WINDOW) -> pd.Series:
    """Rolling percentile rank [0–100] with 260-week window.
    min_periods = window//2 so early history isn't all NaN.
    """
    return series.rolling(window, min_periods=window // 2).rank(pct=True) * 100


def _fetch_yf_weekly(ticker: str, start: str, end: str | None = None) -> pd.Series:
    """Download weekly (W-FRI) close with exponential-backoff retry.
    Returns empty Series on persistent failure.
    """
    import yfinance as yf
    delay = _YF_DELAY
    for attempt in range(1, _YF_RETRIES + 1):
        try:
            data = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
            if data.empty:
                raise ValueError("empty response")
            close = data["Close"]
            if isinstance(close, pd.DataFrame):
                close = close.iloc[:, 0]
            return close.resample("W-FRI").last()
        except Exception as exc:
            if attempt == _YF_RETRIES:
                logger.warning(f"yfinance {ticker} failed after {_YF_RETRIES} attempts: {exc}")
                return pd.Series(dtype=float, name=ticker)
            logger.warning(
                f"yfinance {ticker} attempt {attempt}/{_YF_RETRIES}: {exc} — retrying in {delay}s"
            )
            time.sleep(delay)
            delay *= 2


def _fetch_fred_weekly(series_id: str, start: str, end: str | None = None) -> pd.Series:
    """Fetch FRED series → resample W-FRI → ffill.
    Returns empty Series on failure (log warning, don't raise).
    """
    try:
        from flowmacro.data.sources.fred import fetch_series
        raw = fetch_series(series_id, start=start, end=end)
        return raw.resample("W-FRI").last().ffill()
    except Exception as exc:
        logger.warning(f"FRED {series_id} skipped: {exc}")
        return pd.Series(dtype=float, name=series_id)


# ── Group 2: Macro Leading (5 features) ──────────────────────────────────────

def build_macro_leading(start: str, end: str | None = None) -> pd.DataFrame:
    """Fetch and compute 5 macro leading features (Group 2)."""
    frames: dict[str, pd.Series] = {}

    # hy_spread_pr: BofA HY OAS — credit cycle, leads recession 6–12M
    s = _fetch_fred_weekly("BAMLH0A0HYM2", start, end)
    if not s.empty:
        frames["hy_spread_pr"] = percentile_rank(s)

    # tips_breakeven_5y_pr: forward-looking inflation expectation (vs lagging CPI)
    s = _fetch_fred_weekly("T5YIE", start, end)
    if not s.empty:
        frames["tips_breakeven_5y_pr"] = percentile_rank(s)

    # china_pmi_pr: China manufacturing PMI (monthly → W-FRI ffill)
    s = _fetch_fred_weekly("CPMINDXM", start, end)
    if not s.empty:
        frames["china_pmi_pr"] = percentile_rank(s)

    # copper_gold_ratio_pr: Dr. Copper industrial cycle signal
    copper = _fetch_yf_weekly("HG=F", start, end)
    gold   = _fetch_yf_weekly("GC=F", start, end)
    if not copper.empty and not gold.empty:
        ratio = (copper / gold).dropna()
        frames["copper_gold_ratio_pr"] = percentile_rank(ratio)

    # policy_forward_signal_pr: 1Y Treasury - Fed Funds → market Fed-rate expectation
    t1y = _fetch_fred_weekly("DGS1",     start, end)
    ffr = _fetch_fred_weekly("FEDFUNDS", start, end)
    if not t1y.empty and not ffr.empty:
        frames["policy_forward_signal_pr"] = percentile_rank((t1y - ffr).dropna())

    return pd.DataFrame(frames)


# ── Group 3: Price-Based Leading (9 features) ────────────────────────────────

def build_price_leading(start: str, end: str | None = None) -> pd.DataFrame:
    """Fetch and compute 9 price-based leading features (Group 3)."""
    frames: dict[str, pd.Series] = {}

    # Return-based features: pct_change(N) → percentile_rank
    for ticker, weeks, col in [
        ("SPY",      26, "spy_return_26w"),   # equities lead GDP 6–12M
        ("SPY",      52, "spy_return_52w"),   # long-term structural regime shift
        ("EEM",      26, "eem_return_26w"),   # EM equity leads global growth cycle
        ("TLT",      13, "tlt_return_13w"),   # bond rally = deflation/recession signal
        ("DX-Y.NYB", 13, "dxy_return_13w"),   # dollar leads global macro cycle
        ("DBC",      13, "dbc_return_13w"),   # commodity surge → inflation regime coming
        ("GLD",      13, "gld_return_13w"),   # gold leads inflation expectations
    ]:
        weekly = _fetch_yf_weekly(ticker, start, end)
        if not weekly.empty:
            frames[col] = percentile_rank(weekly.pct_change(periods=weeks))

    # yield_curve_momentum_4w: (10Y–2Y) rate of change — raw delta, NO percentile_rank
    t10 = _fetch_fred_weekly("DGS10", start, end)
    t2  = _fetch_fred_weekly("DGS2",  start, end)
    if not t10.empty and not t2.empty:
        frames["yield_curve_momentum_4w"] = (t10 - t2).diff(4)

    # hy_spread_momentum_4w: spread widening speed — raw delta, NO percentile_rank
    hy = _fetch_fred_weekly("BAMLH0A0HYM2", start, end)
    if not hy.empty:
        frames["hy_spread_momentum_4w"] = hy.diff(4)

    return pd.DataFrame(frames)


# ── Combined ─────────────────────────────────────────────────────────────────

def build_features_v2(start: str, end: str | None = None) -> pd.DataFrame:
    """Build all 14 Group 2 + Group 3 features. Returns weekly indexed DataFrame."""
    logger.info(f"features_v2: fetching {start} → {end or 'today'}")
    macro = build_macro_leading(start=start, end=end)
    price = build_price_leading(start=start, end=end)
    df    = pd.concat([macro, price], axis=1)
    if not df.empty:
        nan_pct = df.isnull().mean().mean() * 100
        logger.info(
            f"features_v2: {df.shape[1]} features × {df.shape[0]} weeks "
            f"({df.index.min().date()} → {df.index.max().date()})  NaN={nan_pct:.1f}%"
        )
    return df
