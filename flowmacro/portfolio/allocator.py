REGIME_ASSETS: dict[str, list[str]] = {
    "GOLDILOCKS":    ["SPY", "QQQ", "IWM", "EFA", "EEM"],
    "REFLATION":     ["GLD", "SLV", "DBC", "USO", "EEM", "IWM"],
    "STAGFLATION":   ["GLD", "SLV", "DBC", "UUP"],
    "DEFLATION":     ["TLT", "IEF", "UUP"],
    "TRANSITIONING": [],  # 100% cash in backtest
}

_CASH_BUFFER = 0.20  # minimum cash for non-TRANSITIONING regimes


def get_weights(regime: str, available_tickers: list[str]) -> dict[str, float]:
    """Equal-weight allocation for the regime, limited to available tickers."""
    target = REGIME_ASSETS.get(regime, [])
    holdings = [t for t in target if t in available_tickers]

    if not holdings:
        return {}  # 100% cash

    investable = 1.0 - _CASH_BUFFER
    w = investable / len(holdings)
    return {t: w for t in holdings}
