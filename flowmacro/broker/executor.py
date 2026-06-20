"""
Rebalance executor: converts target weights → broker orders.

Flow:
  1. Get current account snapshot from broker
  2. Compute target $ value per asset
  3. Diff vs current positions → delta $ per asset
  4. Convert delta $ → share qty using latest price (from yfinance)
  5. Submit sells first (free up cash), then buys
  6. Return execution summary

Safety guards:
  - Min order value: $10 (skip dust trades)
  - Max single position: 45% of portfolio (hard cap)
  - Dry-run mode: log orders without submitting
"""
from __future__ import annotations

import yfinance as yf
from loguru import logger

from flowmacro.broker.base import BrokerBase, Order
from flowmacro.broker.risk_guards import RiskGuardTripped, check_guards, record_value

_MIN_ORDER_VALUE  = 10.0   # USD — skip trades smaller than this
_MAX_WEIGHT_CAP   = 0.45   # hard cap per asset before sending to broker


def _fetch_prices(tickers: list[str]) -> dict[str, float]:
    """Fetch latest close price for each ticker via yfinance."""
    prices: dict[str, float] = {}
    for ticker in tickers:
        try:
            hist = yf.Ticker(ticker).fast_info
            price = hist.last_price or hist.previous_close
            if price and price > 0:
                prices[ticker] = float(price)
            else:
                logger.warning(f"executor: no price for {ticker}")
        except Exception as exc:
            logger.warning(f"executor: price fetch failed for {ticker}: {exc}")
    return prices


def execute_rebalance(
    broker: BrokerBase,
    target_weights: dict[str, float],
    dry_run: bool = False,
) -> dict:
    """
    Rebalance portfolio to target_weights.

    Args:
        broker:         Connected BrokerBase instance
        target_weights: {ticker: weight} — must sum to ≤ 1.0
        dry_run:        If True, log orders but do not submit

    Returns:
        Summary dict with orders, fills, portfolio_value, errors
    """
    # ── 1. Account snapshot ───────────────────────────────────────────────────
    snapshot = broker.get_account()
    portfolio_value = snapshot.total_value
    logger.info(
        f"executor: portfolio=${portfolio_value:,.2f}  cash=${snapshot.cash:,.2f}  "
        f"{'DRY-RUN' if dry_run else 'LIVE'}"
    )

    if portfolio_value < 50:
        raise ValueError(f"Portfolio value ${portfolio_value:.2f} too low — aborting")

    # ── 1b. Risk guards (drawdown circuit breaker + weekly loss limit) ────────
    check_guards(portfolio_value)

    # ── 2. Cap weights ────────────────────────────────────────────────────────
    capped: dict[str, float] = {}
    for ticker, w in target_weights.items():
        if w > _MAX_WEIGHT_CAP:
            logger.warning(f"executor: {ticker} weight {w:.1%} capped at {_MAX_WEIGHT_CAP:.0%}")
            capped[ticker] = _MAX_WEIGHT_CAP
        else:
            capped[ticker] = w

    # ── 3. Current positions ──────────────────────────────────────────────────
    current_values: dict[str, float] = {
        p.ticker: p.market_value for p in snapshot.positions
    }

    # ── 4. Prices ─────────────────────────────────────────────────────────────
    all_tickers = list(set(capped) | set(current_values))
    prices      = _fetch_prices(all_tickers)

    # ── 5. Build order list ───────────────────────────────────────────────────
    sells: list[Order] = []
    buys:  list[Order] = []

    for ticker in all_tickers:
        target_value  = capped.get(ticker, 0.0) * portfolio_value
        current_value = current_values.get(ticker, 0.0)
        delta_value   = target_value - current_value

        if abs(delta_value) < _MIN_ORDER_VALUE:
            continue

        price = prices.get(ticker)
        if not price:
            logger.warning(f"executor: skipping {ticker} — no price available")
            continue

        qty  = abs(delta_value) / price
        side = "buy" if delta_value > 0 else "sell"
        order = Order(
            ticker     = ticker,
            qty        = qty,
            side       = side,
            order_type = "market",
            notes      = f"target={capped.get(ticker,0):.1%}  current={current_value/portfolio_value:.1%}",
        )

        logger.info(
            f"executor: {side.upper():4s} {qty:.2f} {ticker}  "
            f"Δ${delta_value:+,.0f}  @${price:.2f}"
        )

        if side == "sell":
            sells.append(order)
        else:
            buys.append(order)

    orders = sells + buys  # sells first to free cash
    logger.info(f"executor: {len(sells)} sells + {len(buys)} buys = {len(orders)} total orders")

    if not orders:
        logger.info("executor: no orders needed — portfolio already at target")
        return {
            "orders": 0, "order_ids": [], "portfolio_value": portfolio_value,
            "dry_run": dry_run, "errors": [],
        }

    # ── 6. Submit ─────────────────────────────────────────────────────────────
    order_ids: list[str] = []
    errors:    list[str] = []

    for order in orders:
        if dry_run:
            order_ids.append(f"DRY-{order.ticker}")
            continue
        try:
            oid = broker.place_order(order)
            order_ids.append(oid)
        except Exception as exc:
            msg = f"{order.ticker} {order.side}: {exc}"
            logger.error(f"executor: order failed — {msg}")
            errors.append(msg)

    summary = {
        "orders":          len(orders),
        "order_ids":       order_ids,
        "portfolio_value": portfolio_value,
        "dry_run":         dry_run,
        "errors":          errors,
    }
    logger.info(f"executor: done — {summary}")

    # Record portfolio value after successful execution (not during dry-run)
    if not dry_run:
        record_value(portfolio_value)

    return summary
