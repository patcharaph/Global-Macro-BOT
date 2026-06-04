# ── V1 weights (current production) ──────────────────────────────────────────
# V2 experiments (2026-06-05): reducing cash buffer and changing REFLATION
# allocation all degraded Sharpe vs V1 baseline. Root cause: the gap is
# structural (TRANSITIONING = 21.6% cash + REFLATION performance mixed in
# rate-hike years). Weight-only tuning cannot close it.

_CASH_BUFFER = 0.20
_INVESTABLE = 1.0 - _CASH_BUFFER  # 0.80

# Weights are fractions of total capital; each regime sums to _INVESTABLE.
# If a ticker is unavailable the remainder is rescaled to maintain _INVESTABLE.
REGIME_WEIGHTS: dict[str, dict[str, float]] = {
    "GOLDILOCKS": {
        "SPY": 0.24, "QQQ": 0.16, "IWM": 0.12,
        "EFA": 0.12, "EEM": 0.08, "BTC-USD": 0.08,
    },
    "REFLATION": {
        # ~40% equities (growth driver), ~40% commodities (inflation hedge)
        "SPY": 0.16, "EEM": 0.16, "IWM": 0.08,
        "GLD": 0.16, "DBC": 0.16, "USO": 0.08,
    },
    "STAGFLATION": {
        "GLD": 0.30, "SLV": 0.15, "DBC": 0.20, "UUP": 0.15,
    },
    "DEFLATION": {
        "TLT": 0.40, "IEF": 0.25, "UUP": 0.15,
    },
    # SHY (1-3yr Treasury) + GLD — rate-insensitive defensive basket.
    # With _INVESTABLE=0.80, get_weights() scales these to SHY 40% + GLD 40%.
    # More productive than 100% cash; not hurt by rate hikes unlike TLT.
    "TRANSITIONING": {"SHY": 0.25, "GLD": 0.25},
}


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
