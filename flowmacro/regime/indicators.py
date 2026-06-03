from dataclasses import dataclass
import pandas as pd

TIER_WEIGHTS = {1: 0.50, 2: 0.30, 3: 0.20}

# Expected max days between updates per series (based on release frequency)
STALE_THRESHOLD_DAYS: dict[str, int] = {
    # Daily FRED (5 days to tolerate weekends + bank holidays)
    "T10Y2Y": 5, "BAA10Y": 5, "T5YIE": 5,
    # Weekly FRED
    "ICSA": 10,
    # Monthly FRED / derived
    "IPMAN": 45, "UNRATE": 45, "CPIAUCSL": 45, "cpi_yoy": 45,
    # Quarterly FRED
    "A191RL1Q225SBEA": 100,
    # Price-derived (daily)
    "copper_gold": 3, "spy_200ma": 3, "dxy_trend": 3,
    # Pipeline outputs (weekly job)
    "regime_code": 10, "regime_confidence": 10,
    "growth_score": 10, "inflation_score": 10,
    # COT (weekly CFTC release, Friday)
    "cot_sp500_net": 10, "cot_treasury10y_net": 10,
    "cot_gold_net": 10, "cot_crude_net": 10,
}
_DEFAULT_STALE_DAYS = 3  # fallback for price tickers


def stale_threshold(series_id: str) -> int:
    return STALE_THRESHOLD_DAYS.get(series_id, _DEFAULT_STALE_DAYS)


@dataclass(frozen=True)
class Indicator:
    name: str
    series_id: str   # FRED series ID, yfinance ticker, or derived key
    axis: str        # "growth" or "inflation"
    tier: int        # 1, 2, or 3
    inverse: bool    # True = higher raw value → lower score
    source: str      # "fred" or "price"
    abs_lo: float | None = None  # if set, use absolute linear scaling instead of percentile
    abs_hi: float | None = None  # score = clip((x - abs_lo) / (abs_hi - abs_lo) * 100, 0, 100)


INDICATORS: list[Indicator] = [
    # Growth axis
    Indicator("yield_curve",    "T10Y2Y",           "growth",    1, False, "fred"),
    Indicator("credit_spread",  "BAA10Y",            "growth",    1, True,  "fred"),
    Indicator("initial_claims", "ICSA",              "growth",    1, True,  "fred"),
    Indicator("ism_pmi",        "IPMAN",             "growth",    2, False, "fred"),
    Indicator("copper_gold",    "copper_gold",       "growth",    2, False, "price"),
    Indicator("spy_200ma",      "spy_200ma",         "growth",    2, False, "price"),
    Indicator("unemployment",   "UNRATE",            "growth",    3, True,  "fred"),
    Indicator("gdp_growth",     "A191RL1Q225SBEA",   "growth",    3, False, "fred"),
    # Inflation axis — breakeven and CPI use absolute scaling so that
    # "2% = neutral (50)" holds regardless of the rolling window period.
    # Percentile rank against post-2008 deflation made 2% look inflationary.
    Indicator("breakeven_5y",   "T5YIE",    "inflation", 1, False, "fred",
              abs_lo=0.5, abs_hi=3.5),   # 0.5%→0  2.0%→50  3.5%→100
    Indicator("dxy_trend",      "dxy_trend","inflation", 2, True,  "price"),
    Indicator("cpi_yoy",        "cpi_yoy",  "inflation", 3, False, "fred",
              abs_lo=0.0, abs_hi=4.0),   # 0%→0  2%→50  4%→100  (clipped)
    # COT indicators (speculative net positioning, weekly)
    Indicator("cot_sp500",       "cot_sp500_net",       "growth",    2, False, "cot"),
    Indicator("cot_treasury10y", "cot_treasury10y_net", "growth",    2, True,  "cot"),
    Indicator("cot_gold",        "cot_gold_net",        "inflation", 2, False, "cot"),
    Indicator("cot_crude",       "cot_crude_net",       "inflation", 3, False, "cot"),
]


def compute_percentile(series: pd.Series, window_years: int = 5) -> pd.Series:
    """Rolling percentile rank (0-100) over a lookback window of trading days."""
    window = window_years * 252
    pct = series.rolling(window, min_periods=window // 2).rank(pct=True) * 100
    pct.name = series.name
    return pct


def normalize(series: pd.Series, indicator: Indicator, window_years: int = 5) -> pd.Series:
    """Normalize indicator to 0-100 score.

    Uses absolute linear scaling when abs_lo/abs_hi are set (anchors 'neutral'
    to a fixed economic level, e.g. 2% inflation = 50).
    Falls back to rolling percentile rank otherwise.
    """
    if indicator.abs_lo is not None and indicator.abs_hi is not None:
        span = indicator.abs_hi - indicator.abs_lo
        scaled = (series - indicator.abs_lo) / span * 100
        scaled = scaled.clip(0, 100)
        scaled.name = series.name
        if indicator.inverse:
            scaled = 100 - scaled
        return scaled

    pct = compute_percentile(series, window_years)
    if indicator.inverse:
        pct = 100 - pct
    return pct
