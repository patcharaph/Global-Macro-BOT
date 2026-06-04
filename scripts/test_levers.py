"""
Test two levers for closing the CAGR gap:

Lever 1 — Confidence threshold grid
  Reduce TRANSITIONING time by raising confidence_enter/exit thresholds.
  Current: enter=8, exit=12 → 21.6% TRANSITIONING

Lever 2 — TRANSITIONING = SHY 25% + GLD 25%
  Replace 100% cash with a rate-insensitive defensive basket.
  SHY = 1-3yr Treasury (not hurt by rate hikes unlike TLT)

Usage:
    python scripts/test_levers.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import yfinance as yf
from loguru import logger

from flowmacro.data.store import read_series
from flowmacro.regime.indicators import INDICATORS, normalize
from flowmacro.regime.scorer import compute_scores
from flowmacro.regime.classifier import classify_series
from flowmacro.backtest.engine import run_backtest
import flowmacro.config as cfg

_START_WARMUP   = "2005-01-01"
_START_BACKTEST = "2010-01-01"
_IS_END         = "2019-12-31"
_OOS_START      = "2020-01-01"

_TICKERS_BASE = ["SPY", "QQQ", "IWM", "EFA", "EEM",
                  "GLD", "SLV", "DBC", "USO", "TLT", "IEF", "UUP"]
_TICKERS_SHY  = _TICKERS_BASE + ["SHY"]


def build_normalized() -> pd.DataFrame:
    """Pull normalized indicator scores once — reused across all tests."""
    normalized = {}
    for ind in INDICATORS:
        try:
            raw  = read_series(ind.series_id, start=_START_WARMUP)
            if raw.empty:
                continue
            daily  = raw.resample("D").ffill()
            normed = normalize(daily, ind, window_years=5)
            normalized[ind.name] = normed
        except Exception:
            pass
    df = pd.DataFrame(normalized)
    return df.loc[_START_BACKTEST:]


def build_regime_series(normed_df: pd.DataFrame,
                        enter: float, exit_: float) -> pd.Series:
    """Classify regime with given confidence thresholds."""
    cfg.settings.confidence_enter = enter
    cfg.settings.confidence_exit  = exit_
    scores_df  = compute_scores(normed_df)
    regimes_df = classify_series(scores_df)
    cfg.settings.confidence_enter = 8.0   # restore default
    cfg.settings.confidence_exit  = 12.0
    weekly = regimes_df["regime"].resample("W-FRI").last().dropna()
    trans_pct = (weekly == "TRANSITIONING").mean() * 100
    return weekly, trans_pct


def fetch_prices(tickers: list[str]) -> pd.DataFrame:
    raw = yf.download(tickers, start=_START_BACKTEST, auto_adjust=True, progress=False)
    prices = raw["Close"].dropna(how="all")
    return prices[[t for t in tickers if t in prices.columns]]


def backtest_split(prices, regime_series):
    full = run_backtest(prices, regime_series)
    is_p = prices[prices.index <= _IS_END]
    is_r = regime_series[regime_series.index <= _IS_END]
    is_  = run_backtest(is_p, is_r)
    oos_p = prices[prices.index >= _OOS_START]
    oos_r = regime_series[regime_series.index >= _OOS_START]
    oos_  = run_backtest(oos_p, oos_r)
    return (
        full["strategy"]["sharpe_ratio"],
        full["strategy"]["max_drawdown_pct"],
        is_["strategy"]["sharpe_ratio"],
        oos_["strategy"]["sharpe_ratio"],
    )


def set_transitioning_weights(mode: str) -> None:
    from flowmacro.portfolio import allocator
    if mode == "cash":
        allocator.REGIME_WEIGHTS["TRANSITIONING"] = {}
    elif mode == "shy_gld":
        allocator.REGIME_WEIGHTS["TRANSITIONING"] = {"SHY": 0.25, "GLD": 0.25}


if __name__ == "__main__":
    logger.info("=== Lever Test: Confidence Threshold + TRANSITIONING Allocation ===\n")

    logger.info("Loading normalized indicators (once)...")
    normed_df = build_normalized()

    logger.info("Fetching prices (base tickers + SHY)...")
    prices_base = fetch_prices(_TICKERS_BASE)
    prices_shy  = fetch_prices(_TICKERS_SHY)

    # ── Lever 1: Confidence threshold grid ────────────────────────────────────
    logger.info("\n─── Lever 1: Confidence Threshold Grid (TRANSITIONING=cash) ───")
    logger.info(f"{'Label':<20} {'Trans%':>7} {'Sharpe':>7} {'MaxDD':>7} {'IS Sh':>7} {'OOS Sh':>7} {'IS':>5} {'OOS':>5}")
    logger.info("─" * 70)

    set_transitioning_weights("cash")

    threshold_grid = [
        ("V1 baseline",    8,  12),
        ("enter=12 exit=17", 12, 17),
        ("enter=15 exit=20", 15, 20),
        ("enter=20 exit=26", 20, 26),
    ]

    best_lever1 = None
    for label, enter, exit_ in threshold_grid:
        weekly, trans_pct = build_regime_series(normed_df, enter, exit_)
        sharpe, maxdd, is_sh, oos_sh = backtest_split(prices_base, weekly)
        is_pass  = "PASS" if is_sh  >= 0.70 else "fail"
        oos_pass = "PASS" if oos_sh >= 0.50 else "fail"
        logger.info(
            f"{label:<20} {trans_pct:>6.1f}% {sharpe:>7.2f} {maxdd:>6.1f}% "
            f"{is_sh:>7.2f} {oos_sh:>7.2f} {is_pass:>5} {oos_pass:>5}"
        )
        if is_sh >= 0.70 and oos_sh >= 0.50 and (best_lever1 is None or sharpe > best_lever1[0]):
            best_lever1 = (sharpe, label, enter, exit_)

    if best_lever1:
        logger.info(f"\n=> Best Lever 1: {best_lever1[1]} (Sharpe={best_lever1[0]:.2f})")
    else:
        logger.info("\n=> No threshold combination passed both IS+OOS criteria")

    # ── Lever 2: TRANSITIONING = SHY + GLD ───────────────────────────────────
    logger.info("\n─── Lever 2: TRANSITIONING = SHY 25% + GLD 25% (V1 thresholds) ───")
    logger.info(f"{'Label':<25} {'Trans%':>7} {'Sharpe':>7} {'MaxDD':>7} {'IS Sh':>7} {'OOS Sh':>7} {'IS':>5} {'OOS':>5}")
    logger.info("─" * 75)

    set_transitioning_weights("shy_gld")
    weekly_v1, trans_pct_v1 = build_regime_series(normed_df, 8, 12)
    sharpe, maxdd, is_sh, oos_sh = backtest_split(prices_shy, weekly_v1)
    is_pass  = "PASS" if is_sh  >= 0.70 else "fail"
    oos_pass = "PASS" if oos_sh >= 0.50 else "fail"
    logger.info(
        f"{'SHY+GLD (enter=8)':<25} {trans_pct_v1:>6.1f}% {sharpe:>7.2f} {maxdd:>6.1f}% "
        f"{is_sh:>7.2f} {oos_sh:>7.2f} {is_pass:>5} {oos_pass:>5}"
    )

    # ── Combined: best threshold + SHY/GLD ────────────────────────────────────
    logger.info("\n─── Combined: Best Threshold + SHY/GLD ───")
    for label, enter, exit_ in threshold_grid[1:]:   # skip V1 baseline
        weekly, trans_pct = build_regime_series(normed_df, enter, exit_)
        sharpe, maxdd, is_sh, oos_sh = backtest_split(prices_shy, weekly)
        is_pass  = "PASS" if is_sh  >= 0.70 else "fail"
        oos_pass = "PASS" if oos_sh >= 0.50 else "fail"
        logger.info(
            f"{'SHY+GLD '+label:<30} {trans_pct:>6.1f}% {sharpe:>7.2f} {maxdd:>6.1f}% "
            f"{is_sh:>7.2f} {oos_sh:>7.2f} {is_pass:>5} {oos_pass:>5}"
        )

    # Restore defaults
    set_transitioning_weights("cash")
    cfg.settings.confidence_enter = 8.0
    cfg.settings.confidence_exit  = 12.0
    logger.info("\nDefaults restored. allocator.py unchanged.")
