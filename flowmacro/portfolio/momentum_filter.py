import pandas as pd
from loguru import logger


def apply_momentum_filter(
    weights: dict[str, float],
    price_history: pd.DataFrame,
    window_fast: int = 13,
    window_slow: int = 26,
    threshold: float = -0.05,
) -> dict[str, float]:
    """Cut weight 50% when both 13W and 26W returns are below threshold.

    Dual confirmation prevents false positives during volatile sideways markets.
    Freed weight goes to Cash — not redistributed to other assets.

    Reference: Jegadeesh & Titman (1993) momentum autocorrelation.
    """
    filtered = weights.copy()
    freed_weight = 0.0

    for asset, weight in weights.items():
        if asset == "Cash" or asset not in price_history.columns:
            continue

        prices = price_history[asset].dropna()
        if len(prices) < window_slow:
            continue

        mom_fast = float(prices.iloc[-1] / prices.iloc[-window_fast] - 1)
        mom_slow = float(prices.iloc[-1] / prices.iloc[-window_slow] - 1)

        if mom_fast < threshold and mom_slow < threshold:
            cut = weight * 0.50
            filtered[asset] = weight - cut
            freed_weight += cut
            logger.info(
                f"momentum_filter cut {asset}: "
                f"13W={mom_fast:.2%} 26W={mom_slow:.2%} "
                f"weight {weight:.3f} → {filtered[asset]:.3f}"
            )

    filtered["Cash"] = filtered.get("Cash", 0.0) + freed_weight
    return filtered
