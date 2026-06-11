# V3 weights (2026-06-11): softmax blending replaces hard switching.
# USO removed from REFLATION (contango/roll cost; DBC absorbs energy exposure).
# SLV reduced in STAGFLATION (ρ≈0.82 with GLD, high industrial demand risk).
# TLT reduced in DEFLATION (modified duration ≈17yr); SHY added as short-end anchor.
# EEM raised in GOLDILOCKS; EEM raised in REFLATION as EM growth driver.

_CASH_BUFFER = 0.20
_INVESTABLE = 1.0 - _CASH_BUFFER  # 0.80

# Weights are fractions of total capital; each regime sums to _INVESTABLE.
# If a ticker is unavailable the remainder is rescaled to maintain _INVESTABLE.
REGIME_WEIGHTS: dict[str, dict[str, float]] = {
    "GOLDILOCKS": {
        "SPY": 0.20, "QQQ": 0.16, "IWM": 0.12,
        "EFA": 0.12, "EEM": 0.13, "BTC-USD": 0.07,
    },
    "REFLATION": {
        "SPY": 0.12, "IWM": 0.08, "EEM": 0.20,
        "GLD": 0.10, "DBC": 0.30,
    },
    "STAGFLATION": {
        "GLD": 0.34, "SLV": 0.08, "DBC": 0.24, "UUP": 0.14,
    },
    "DEFLATION": {
        "TLT": 0.30, "IEF": 0.25, "UUP": 0.15, "SHY": 0.10,
    },
    # SHY + GLD defensive basket (50% cash). Used by get_weights() for legacy
    # paper portfolio reads; V3 allocation uses compute_blended_weights() instead.
    "TRANSITIONING": {"SHY": 0.25, "GLD": 0.25},
}

# Regimes included in softmax blending (TRANSITIONING handled via entropy naturally)
_BLEND_REGIMES = {r: w for r, w in REGIME_WEIGHTS.items() if r != "TRANSITIONING"}


def compute_blended_weights(
    regime_probs: dict[str, float],
    regime_weights: dict[str, dict[str, float]] | None = None,
) -> dict[str, float]:
    """Weighted average of regime allocations by softmax probabilities.

    Formula: w_asset = Σ_k (p_k × w_k_asset)
    When probabilities shift gradually, the portfolio drifts smoothly —
    reducing turnover vs hard regime switches.

    TRANSITIONING is excluded; softmax entropy handles ambiguous signals naturally.
    """
    rw = regime_weights if regime_weights is not None else _BLEND_REGIMES

    all_assets: set[str] = set()
    for weights in rw.values():
        all_assets.update(weights.keys())

    blended: dict[str, float] = {}
    for asset in all_assets:
        blended[asset] = sum(
            regime_probs.get(regime, 0.0) * rw.get(regime, {}).get(asset, 0.0)
            for regime in rw
        )

    investable = sum(blended.values())
    if abs(investable - _INVESTABLE) >= 0.01:
        raise ValueError(f"Blended investable sum={investable:.4f}, expected {_INVESTABLE}")

    return blended


def get_weights(regime: str, available_tickers: list[str]) -> dict[str, float]:
    """Return portfolio weights for the regime, limited to available tickers.

    Weights are fractions of total capital. If target tickers are missing,
    the remaining weights are rescaled so total invested stays at _INVESTABLE.
    Returns empty dict when all tickers are unavailable (100% cash).
    """
    target = REGIME_WEIGHTS.get(regime, {})
    holdings = {t: w for t, w in target.items() if t in available_tickers}

    if not holdings:
        return {}

    allocated = sum(holdings.values())
    scale = _INVESTABLE / allocated
    return {t: w * scale for t, w in holdings.items()}
