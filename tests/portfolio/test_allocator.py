import pytest
from flowmacro.portfolio.allocator import get_weights, REGIME_WEIGHTS, _INVESTABLE


@pytest.mark.parametrize("regime", ["GOLDILOCKS", "REFLATION", "STAGFLATION", "DEFLATION"])
def test_weights_sum_to_investable(regime):
    tickers = list(REGIME_WEIGHTS[regime].keys())
    w = get_weights(regime, tickers)
    assert abs(sum(w.values()) - _INVESTABLE) < 1e-9


def test_transitioning_returns_empty():
    assert get_weights("TRANSITIONING", ["SPY", "TLT"]) == {}


def test_unknown_regime_returns_empty():
    assert get_weights("UNKNOWN", ["SPY"]) == {}


def test_missing_ticker_rescales_to_investable():
    # Remove BTC-USD from GOLDILOCKS — remaining 5 tickers should still sum to 0.80
    tickers = [t for t in REGIME_WEIGHTS["GOLDILOCKS"] if t != "BTC-USD"]
    w = get_weights("GOLDILOCKS", tickers)
    assert "BTC-USD" not in w
    assert abs(sum(w.values()) - _INVESTABLE) < 1e-9


def test_all_tickers_missing_returns_empty():
    w = get_weights("GOLDILOCKS", ["TLT", "IEF"])  # none overlap with GOLDILOCKS
    assert w == {}


def test_goldilocks_includes_btc():
    tickers = list(REGIME_WEIGHTS["GOLDILOCKS"].keys())
    w = get_weights("GOLDILOCKS", tickers)
    assert "BTC-USD" in w
    assert w["BTC-USD"] > 0


def test_no_regime_has_weight_above_investable():
    for regime, target in REGIME_WEIGHTS.items():
        if not target:
            continue
        tickers = list(target.keys())
        w = get_weights(regime, tickers)
        assert sum(w.values()) <= _INVESTABLE + 1e-9
