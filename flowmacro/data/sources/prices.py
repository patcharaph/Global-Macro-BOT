from datetime import date
import pandas as pd
import yfinance as yf
from loguru import logger


def fetch_price(ticker: str, start: str, end: str | None = None) -> pd.Series:
    """Fetch daily close price for a single ticker. Returns date-indexed Series."""
    data = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)

    if data.empty:
        raise ValueError(f"yfinance: no data for {ticker} from {start}")

    close = data["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]

    close.name = ticker
    nan_pct = close.isna().mean() * 100
    stale = staleness_days(close)
    logger.debug(f"yfinance {ticker}: {len(close)} rows, last={close.index[-1].date()}, NaN={nan_pct:.1f}%, stale={stale}d")
    return close


def staleness_days(series: pd.Series) -> int:
    """Days since last non-NaN value. Returns -1 if no valid data."""
    last_valid = series.last_valid_index()
    if last_valid is None:
        return -1
    return (date.today() - last_valid.date()).days


def fetch_prices(tickers: list[str], start: str, end: str | None = None) -> tuple[pd.DataFrame, dict[str, int]]:
    """Fetch close prices for multiple tickers. Returns (DataFrame, staleness_days per ticker)."""
    prices: dict[str, pd.Series] = {}
    staleness: dict[str, int] = {}

    for ticker in tickers:
        try:
            s = fetch_price(ticker, start, end)
            prices[ticker] = s
            staleness[ticker] = staleness_days(s)
        except Exception as e:
            logger.error(f"yfinance {ticker}: failed — {e}")
            prices[ticker] = pd.Series(dtype=float, name=ticker)
            staleness[ticker] = -1

    return pd.DataFrame(prices), staleness
