from loguru import logger


def needs_rebalance(
    current_weights: dict[str, float],
    target_weights: dict[str, float],
    band: float = 0.02,
) -> bool:
    """Return True if any asset drifted beyond band (default 2%)."""
    all_assets = set(current_weights) | set(target_weights)
    return any(
        abs(current_weights.get(a, 0.0) - target_weights.get(a, 0.0)) > band
        for a in all_assets
    )


def compute_trades(
    current_weights: dict[str, float],
    target_weights: dict[str, float],
    portfolio_value: float,
) -> list[dict]:
    """Compute trades for assets with drift above minimum size (0.1%).

    Returns list of {asset, action, weight_change, value_change}.
    """
    trades = []
    all_assets = set(current_weights) | set(target_weights)

    for asset in sorted(all_assets):
        curr = current_weights.get(asset, 0.0)
        tgt = target_weights.get(asset, 0.0)
        drift = tgt - curr

        if abs(drift) > 0.001:
            trade = {
                "asset": asset,
                "action": "BUY" if drift > 0 else "SELL",
                "weight_change": round(drift, 6),
                "value_change": round(drift * portfolio_value, 2),
            }
            trades.append(trade)
            logger.info(
                f"trade: {asset} {trade['action']} "
                f"Δweight={drift:+.3%} Δvalue=${trade['value_change']:+,.2f}"
            )

    return trades
