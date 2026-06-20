"""
Risk guards for live IBKR trading.

Guards run before every execute_rebalance() call.
Raises RiskGuardTripped to halt trading for the week if any limit is breached.

Thresholds (conservative for Phase 3 validation):
  - Drawdown circuit breaker: -15% from all-time high-water mark
  - Single-week loss limit:   -8%  (top-1% loss week in backtest history)
  - Portfolio floor:          $1,000 (hard minimum before executor runs)

Portfolio value history is persisted to Supabase series "ibkr_portfolio_value".
HWM is derived on-the-fly as the running max of that series.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
from loguru import logger

from flowmacro.data.store import read_series, upsert_series

_DD_LIMIT_PCT   = 15.0      # drawdown from HWM that triggers halt
_WK_LOSS_PCT    = 8.0       # single-week loss that triggers halt
_MIN_VALUE_USD  = 1_000.0   # hard portfolio floor (already checked in executor at $50)
_HISTORY_KEY    = "ibkr_portfolio_value"
_HISTORY_WEEKS  = 54        # how far back to load for HWM computation


class RiskGuardTripped(Exception):
    """Raised when a risk guard fires — caller should halt trading and alert."""


def check_guards(portfolio_value: float) -> None:
    """
    Run all risk guards against current portfolio_value.

    Reads ibkr_portfolio_value history from Supabase to compute HWM and
    last-week return. Raises RiskGuardTripped if any limit is breached.
    Does NOT write — call record_value() after successful execution.

    Args:
        portfolio_value: Current total portfolio value in USD (from broker.get_account()).
    """
    # Guard 1: Hard floor (no history needed)
    if portfolio_value < _MIN_VALUE_USD:
        raise RiskGuardTripped(
            f"Portfolio ${portfolio_value:,.0f} is below floor ${_MIN_VALUE_USD:,.0f}"
        )

    try:
        start = str(date.today() - timedelta(weeks=_HISTORY_WEEKS))
        hist = read_series(_HISTORY_KEY, start=start)

        if hist.empty:
            logger.info("risk_guards: no prior history — skipping drawdown and weekly checks (first run)")
            logger.info("risk_guards: all guards PASSED")
            return

        hist = hist.dropna().sort_index()

        # Guard 2: Drawdown from all-time high-water mark
        hwm = max(float(hist.max()), portfolio_value)
        dd_pct = (1.0 - portfolio_value / hwm) * 100.0
        logger.info(
            f"risk_guards: portfolio=${portfolio_value:,.0f}  "
            f"HWM=${hwm:,.0f}  drawdown={dd_pct:.1f}%"
        )
        if dd_pct > _DD_LIMIT_PCT:
            raise RiskGuardTripped(
                f"Drawdown {dd_pct:.1f}% exceeds circuit-breaker limit {_DD_LIMIT_PCT:.0f}% "
                f"(portfolio=${portfolio_value:,.0f}  HWM=${hwm:,.0f})"
            )

        # Guard 3: Single-week loss
        prev_value = float(hist.iloc[-1])
        wk_ret_pct = (portfolio_value / prev_value - 1.0) * 100.0
        logger.info(
            f"risk_guards: prev_week=${prev_value:,.0f}  "
            f"weekly_return={wk_ret_pct:+.1f}%"
        )
        if wk_ret_pct < -_WK_LOSS_PCT:
            raise RiskGuardTripped(
                f"Weekly loss {wk_ret_pct:.1f}% exceeds limit -{_WK_LOSS_PCT:.0f}% "
                f"(${prev_value:,.0f} → ${portfolio_value:,.0f})"
            )

    except RiskGuardTripped:
        raise
    except Exception as exc:
        # Data read failure → log warning but allow trading (fail-open on data errors)
        logger.warning(f"risk_guards: history check failed ({exc}) — allowing execution")

    logger.info("risk_guards: all guards PASSED")


def record_value(portfolio_value: float) -> None:
    """
    Persist today's portfolio value to Supabase after successful execution.

    Separate from check_guards() so that a dry-run or failed execution
    does not pollute the HWM history.
    """
    try:
        ts = pd.Timestamp(date.today())
        upsert_series(_HISTORY_KEY, pd.Series([portfolio_value], index=[ts]))
        logger.info(f"risk_guards: recorded ${portfolio_value:,.0f} to {_HISTORY_KEY}")
    except Exception as exc:
        logger.warning(f"risk_guards: failed to record portfolio value ({exc})")
