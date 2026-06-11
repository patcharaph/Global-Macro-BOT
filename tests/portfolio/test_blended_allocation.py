import pytest
from flowmacro.portfolio.allocator import compute_blended_weights, REGIME_WEIGHTS, _INVESTABLE

_FOUR_REGIMES = {r: w for r, w in REGIME_WEIGHTS.items() if r != "TRANSITIONING"}


def _equal_probs() -> dict[str, float]:
    return {r: 0.25 for r in _FOUR_REGIMES}


def _pure_probs(regime: str) -> dict[str, float]:
    return {r: (1.0 if r == regime else 0.0) for r in _FOUR_REGIMES}


def test_investable_sum_with_equal_probs():
    blended = compute_blended_weights(_equal_probs())
    assert abs(sum(blended.values()) - _INVESTABLE) < 1e-6


@pytest.mark.parametrize("regime", list(_FOUR_REGIMES.keys()))
def test_pure_regime_matches_base_weights(regime):
    blended = compute_blended_weights(_pure_probs(regime))
    base = _FOUR_REGIMES[regime]
    for asset, w in base.items():
        assert abs(blended.get(asset, 0.0) - w) < 1e-9


def test_all_weights_non_negative():
    probs = {"GOLDILOCKS": 0.4, "REFLATION": 0.3, "STAGFLATION": 0.2, "DEFLATION": 0.1}
    blended = compute_blended_weights(probs)
    assert all(v >= 0 for v in blended.values())


def test_investable_sum_with_skewed_probs():
    probs = {"GOLDILOCKS": 0.6, "REFLATION": 0.2, "STAGFLATION": 0.1, "DEFLATION": 0.1}
    blended = compute_blended_weights(probs)
    assert abs(sum(blended.values()) - _INVESTABLE) < 1e-6


def test_raises_on_bad_regime_weights():
    bad_weights = {"GOLDILOCKS": {"SPY": 0.50}}  # sums to 0.50, not 0.80
    probs = {"GOLDILOCKS": 1.0}
    with pytest.raises(ValueError):
        compute_blended_weights(probs, regime_weights=bad_weights)


def test_custom_regime_weights_parameter():
    custom = {
        "GOLDILOCKS": {"SPY": 0.80},
        "DEFLATION":  {"TLT": 0.80},
    }
    probs = {"GOLDILOCKS": 0.5, "DEFLATION": 0.5}
    blended = compute_blended_weights(probs, regime_weights=custom)
    assert abs(blended["SPY"] - 0.40) < 1e-9
    assert abs(blended["TLT"] - 0.40) < 1e-9
    assert abs(sum(blended.values()) - _INVESTABLE) < 1e-6
