"""
Persistent paper portfolio for Phase 3 paper trading validation.

State stored in Supabase raw_series:
  paper_total_value  — weekly portfolio total value (USD)

Each weekly run:
  1. Read last stored value + regime from Supabase
  2. Compute week-over-week return using actual prices + last regime weights
  3. Store updated portfolio value
  4. Return summary string for inclusion in weekly email
"""

from datetime import date, timedelta
import pandas as pd
from loguru import logger

from flowmacro.data.store import read_series, upsert_series
from flowmacro.portfolio.allocator import get_weights, REGIME_WEIGHTS, compute_blended_weights

_VALUE_SERIES = "paper_total_value"
_INITIAL_CASH = 3_000.0  # USD
_REGIME_CODE  = {
    1: "GOLDILOCKS", 2: "REFLATION",
    3: "STAGFLATION", 4: "DEFLATION", 0: "TRANSITIONING",
}


def _all_regime_tickers() -> list[str]:
    tickers: set[str] = set()
    for weights in REGIME_WEIGHTS.values():
        tickers.update(weights.keys())
    return list(tickers)


def _price_on(ticker: str, on: date) -> float | None:
    """Most recent price on or before `on` from Supabase (10-day lookback)."""
    try:
        s = read_series(ticker, start=str(on - timedelta(days=10)), end=str(on))
        if s.empty:
            return None
        return float(s.dropna().iloc[-1])
    except Exception:
        return None


def _last_regime_from_supabase(on: date) -> str:
    try:
        s = read_series("regime_code", start=str(on), end=str(on))
        if s.empty:
            return "TRANSITIONING"
        return _REGIME_CODE.get(int(s.dropna().iloc[-1]), "TRANSITIONING")
    except Exception:
        return "TRANSITIONING"


def _last_probs_from_supabase(on: date) -> dict[str, float] | None:
    """Read V3 softmax probabilities stored on `on`. Returns None if unavailable."""
    _REGIME_PROB_SERIES = {
        "GOLDILOCKS": "regime_prob_goldilocks",
        "REFLATION":  "regime_prob_reflation",
        "STAGFLATION": "regime_prob_stagflation",
        "DEFLATION":  "regime_prob_deflation",
    }
    try:
        probs: dict[str, float] = {}
        window_start = str(on - timedelta(days=1))
        window_end   = str(on)
        for regime, series_id in _REGIME_PROB_SERIES.items():
            s = read_series(series_id, start=window_start, end=window_end)
            if s.empty:
                return None
            probs[regime] = float(s.dropna().iloc[-1])
        return probs if len(probs) == 4 else None
    except Exception:
        return None


def update(current_regime: str, today: date) -> str:
    """
    Update paper portfolio for today's weekly run.
    Returns a formatted summary for the weekly email.
    """
    # ── Read last stored state ────────────────────────────────────────────────
    try:
        value_series = read_series(_VALUE_SERIES, start="2020-01-01")
    except Exception as exc:
        logger.warning(f"Paper portfolio: could not read state: {exc}")
        return ""

    # ── First run: initialise ─────────────────────────────────────────────────
    if value_series.empty:
        logger.info(f"Paper portfolio: initialising at ${_INITIAL_CASH:,.0f}")
        upsert_series(_VALUE_SERIES, pd.Series(
            [_INITIAL_CASH], index=[pd.Timestamp(today)]
        ))
        return (
            f"Paper Portfolio (INITIALISED)\n"
            f"  Start value:  ${_INITIAL_CASH:,.2f}\n"
            f"  Regime today: {current_regime}\n"
            f"  P&L tracking begins next week"
        )

    last_date  = value_series.last_valid_index()
    last_value = float(value_series.loc[last_date])

    if (today - last_date.date()).days < 1:
        logger.info("Paper portfolio: already updated today — skipping")
        return ""

    # ── Compute return: last week's weights × actual price moves ─────────────
    last_regime = _last_regime_from_supabase(last_date.date())
    last_probs  = _last_probs_from_supabase(last_date.date())

    if last_probs is not None:
        # V3: use blended weights derived from stored softmax probabilities
        weights = compute_blended_weights(last_probs)
    else:
        # V2B fallback: single-regime hard weights
        weights = get_weights(last_regime, _all_regime_tickers())

    portfolio_return = 0.0
    ticker_returns: dict[str, float] = {}

    for ticker, w in weights.items():
        p0 = _price_on(ticker, last_date.date())
        p1 = _price_on(ticker, today)
        if p0 and p1 and p0 > 0:
            r = (p1 / p0) - 1
            portfolio_return += w * r
            ticker_returns[ticker] = round(r * 100, 2)
        else:
            logger.warning(f"Paper portfolio: missing price for {ticker} — treating as 0% return")

    new_value = last_value * (1 + portfolio_return)
    week_pnl  = new_value - last_value
    week_pct  = portfolio_return * 100
    total_pct = (new_value / _INITIAL_CASH - 1) * 100

    logger.info(
        f"Paper portfolio: {last_regime} → {current_regime}  "
        f"week={week_pct:+.2f}%  total={total_pct:+.2f}%  value=${new_value:,.2f}"
    )

    upsert_series(_VALUE_SERIES, pd.Series([new_value], index=[pd.Timestamp(today)]))

    # ── Format email summary ──────────────────────────────────────────────────
    pos_lines = (
        "\n".join(f"    {t}: {r:+.2f}%" for t, r in sorted(ticker_returns.items()))
        or "    (100% cash — TRANSITIONING)"
    )
    return (
        f"Paper Portfolio\n"
        f"  Value:       ${new_value:,.2f}  (total {total_pct:+.2f}% since start)\n"
        f"  Week P&L:    ${week_pnl:+,.2f}  ({week_pct:+.2f}%)\n"
        f"  Regime held: {last_regime}  →  now: {current_regime}\n"
        f"  Returns this week:\n{pos_lines}"
    )
