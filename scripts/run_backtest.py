"""
Generate historical regime signals from Supabase, run vectorbt backtest, save results.

Warmup:  2005-01-01 (FRED seed data)
Backtest: 2010-01-01 → today  (first 5 years used for rolling percentile warmup)

Usage:
    python scripts/run_backtest.py
"""
import sys
from pathlib import Path

# Allow running from repo root without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import yfinance as yf
from loguru import logger

from flowmacro.data.store import read_series
from flowmacro.regime.indicators import INDICATORS, normalize
from flowmacro.regime.scorer import compute_scores
from flowmacro.regime.classifier import classify_series
from flowmacro.backtest.engine import run_backtest, save_backtest

_START_WARMUP   = "2005-01-01"
_START_BACKTEST = "2010-01-01"

_TICKERS = [
    "SPY", "QQQ", "IWM", "EFA", "EEM",
    "GLD", "SLV", "DBC", "USO",
    "TLT", "IEF", "UUP",
]


def build_regime_series() -> pd.Series:
    """Read all indicators from Supabase, compute rolling percentile, classify weekly."""
    normalized: dict[str, pd.Series] = {}

    for ind in INDICATORS:
        try:
            raw = read_series(ind.series_id, start=_START_WARMUP)
            if raw.empty:
                logger.warning(f"No data for {ind.name} ({ind.series_id}) — skipped")
                continue
            daily = raw.resample("D").ffill()
            normed = normalize(daily, ind, window_years=5)
            normalized[ind.name] = normed
            logger.debug(f"{ind.name}: {len(normed)} rows, last={normed.last_valid_index().date()}")
        except Exception as exc:
            logger.warning(f"Indicator {ind.name} failed: {exc}")

    if len(normalized) < 5:
        raise ValueError(f"Only {len(normalized)} indicators available — need at least 5 to proceed")

    normed_df = pd.DataFrame(normalized)
    normed_df = normed_df.loc[_START_BACKTEST:]

    scores_df  = compute_scores(normed_df)
    regimes_df = classify_series(scores_df)

    # Resample to weekly Friday — each regime drives the following week's portfolio
    regime_weekly = regimes_df["regime"].resample("W-FRI").last().dropna()
    logger.info(f"Regime signals: {len(regime_weekly)} weeks")
    logger.info(f"Distribution: {regime_weekly.value_counts().to_dict()}")
    return regime_weekly


def fetch_prices() -> pd.DataFrame:
    """Download price history from yfinance."""
    logger.info(f"Downloading prices for {_TICKERS} from {_START_BACKTEST}...")
    raw = yf.download(_TICKERS, start=_START_BACKTEST, auto_adjust=True, progress=False)
    prices = raw["Close"].dropna(how="all")
    logger.info(f"Prices: {len(prices)} days, {prices.shape[1]} tickers")
    return prices


def main() -> None:
    logger.info("=== FlowMacro Backtest ===")

    logger.info("Step 1/3 — Building historical regime series...")
    regime_series = build_regime_series()

    logger.info("Step 2/3 — Fetching price history...")
    prices = fetch_prices()

    # Keep only tickers present in both datasets
    available = [t for t in _TICKERS if t in prices.columns]
    prices = prices[available]

    logger.info("Step 3/3 — Running backtest...")
    result = run_backtest(prices, regime_series)

    strat = result["strategy"]
    bench = result["benchmark_60_40"]

    logger.info("=== Results ===")
    logger.info(f"FlowMacro:  Sharpe={strat['sharpe_ratio']:.2f}  Return={strat['total_return_pct']:.1f}%  MaxDD={strat['max_drawdown_pct']:.1f}%")
    logger.info(f"60/40 Bench: Sharpe={bench['sharpe_ratio']:.2f}  Return={bench['total_return_pct']:.1f}%  MaxDD={bench['max_drawdown_pct']:.1f}%")

    run_id = save_backtest(result)
    logger.info(f"Saved → Supabase backtest_runs  run_id={run_id}")
    logger.info("Done — refresh the Backtest page in the dashboard to see results.")


if __name__ == "__main__":
    main()
