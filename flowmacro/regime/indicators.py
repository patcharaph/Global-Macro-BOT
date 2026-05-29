from dataclasses import dataclass
import pandas as pd

TIER_WEIGHTS = {1: 0.50, 2: 0.30, 3: 0.20}


@dataclass(frozen=True)
class Indicator:
    name: str
    series_id: str   # FRED series ID, yfinance ticker, or derived key
    axis: str        # "growth" or "inflation"
    tier: int        # 1, 2, or 3
    inverse: bool    # True = higher raw value → lower score
    source: str      # "fred" or "price"


INDICATORS: list[Indicator] = [
    # Growth axis
    Indicator("yield_curve",   "T10Y2Y",          "growth",    1, False, "fred"),
    Indicator("credit_spread", "BAMLH0A0HYM2",    "growth",    1, True,  "fred"),
    Indicator("lei",           "USSLIND",          "growth",    1, False, "fred"),
    Indicator("ism_pmi",       "NAPM",             "growth",    2, False, "fred"),
    Indicator("copper_gold",   "copper_gold",      "growth",    2, False, "price"),  # derived: HG=F / GC=F
    Indicator("spy_200ma",     "spy_200ma",        "growth",    2, False, "price"),  # derived: (SPY/200MA - 1) * 100
    Indicator("unemployment",  "UNRATE",           "growth",    3, True,  "fred"),
    Indicator("gdp_growth",    "A191RL1Q225SBEA",  "growth",    3, False, "fred"),
    # Inflation axis
    Indicator("breakeven_5y",  "T5YIE",            "inflation", 1, False, "fred"),
    Indicator("dxy_trend",     "dxy_trend",        "inflation", 2, True,  "price"),  # derived: (UUP/20MA - 1) * 100
    Indicator("cpi_yoy",       "cpi_yoy",          "inflation", 3, False, "fred"),   # derived: CPIAUCSL YoY %
]


def compute_percentile(series: pd.Series, window_years: int = 5) -> pd.Series:
    """Rolling percentile rank (0-100) over a lookback window of trading days."""
    window = window_years * 252
    pct = series.rolling(window, min_periods=window // 2).rank(pct=True) * 100
    pct.name = series.name
    return pct


def normalize(series: pd.Series, indicator: Indicator, window_years: int = 5) -> pd.Series:
    """Compute percentile rank and flip if inverse indicator."""
    pct = compute_percentile(series, window_years)
    if indicator.inverse:
        pct = 100 - pct
    return pct
