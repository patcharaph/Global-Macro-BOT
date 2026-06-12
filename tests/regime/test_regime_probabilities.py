import pytest
from flowmacro.regime.probabilities import (
    compute_regime_probabilities,
    compute_ml_blended_probs,
    REGIME_CENTROIDS,
    REGIMES,
    BlendedResult,
)


def test_probabilities_sum_to_one():
    probs = compute_regime_probabilities(60.0, 40.0)
    assert abs(sum(probs.values()) - 1.0) < 1e-9


def test_goldilocks_dominates_at_high_growth_low_inflation():
    probs = compute_regime_probabilities(80.0, 20.0)
    assert probs["GOLDILOCKS"] > 0.5


def test_reflation_dominates_at_high_growth_high_inflation():
    probs = compute_regime_probabilities(80.0, 80.0)
    assert probs["REFLATION"] > 0.5


def test_stagflation_dominates_at_low_growth_high_inflation():
    probs = compute_regime_probabilities(20.0, 80.0)
    assert probs["STAGFLATION"] > 0.5


def test_deflation_dominates_at_low_growth_low_inflation():
    probs = compute_regime_probabilities(20.0, 20.0)
    assert probs["DEFLATION"] > 0.5


def test_high_entropy_at_center():
    # All four regimes equidistant from center → should blend roughly equally
    probs = compute_regime_probabilities(50.0, 50.0)
    assert max(probs.values()) < 0.40


def test_four_regimes_returned():
    probs = compute_regime_probabilities(60.0, 40.0)
    assert set(probs.keys()) == {"GOLDILOCKS", "REFLATION", "STAGFLATION", "DEFLATION"}


def test_all_probabilities_non_negative():
    probs = compute_regime_probabilities(30.0, 70.0)
    assert all(p >= 0 for p in probs.values())


def test_lower_tau_more_decisive():
    # Lower tau → sharper distribution → dominant regime has higher probability
    probs_sharp = compute_regime_probabilities(75.0, 25.0, tau=5.0)
    probs_broad  = compute_regime_probabilities(75.0, 25.0, tau=40.0)
    assert max(probs_sharp.values()) > max(probs_broad.values())


@pytest.mark.parametrize("regime,centroid", REGIME_CENTROIDS.items())
def test_centroid_gives_dominant_regime(regime, centroid):
    # Exactly at a centroid, that regime should be most probable
    g, i = centroid
    probs = compute_regime_probabilities(g, i)
    assert max(probs, key=lambda r: probs[r]) == regime


# ── compute_ml_blended_probs ──────────────────────────────────────────────────

_RULE_PROBS = {
    "GOLDILOCKS": 0.21,
    "REFLATION":  0.31,
    "STAGFLATION": 0.28,
    "DEFLATION":  0.20,
}  # must sum to 1.0 — function normalizes output so input must be normalized for boundary tests


def test_ml_blended_returns_named_tuple():
    result = compute_ml_blended_probs(_RULE_PROBS, "REFLATION", 94.8)
    assert isinstance(result, BlendedResult)
    assert set(result.blended) == set(REGIMES)
    assert set(result.ml_raw)  == set(REGIMES)
    assert set(result.rule)    == set(REGIMES)


def test_ml_blended_probs_sum_to_one():
    result = compute_ml_blended_probs(_RULE_PROBS, "REFLATION", 94.8)
    assert abs(sum(result.blended.values()) - 1.0) < 1e-9


def test_ml_raw_probs_sum_to_one():
    result = compute_ml_blended_probs(_RULE_PROBS, "REFLATION", 94.8)
    assert abs(sum(result.ml_raw.values()) - 1.0) < 1e-9


def test_ml_blended_weight_zero_equals_rule():
    result = compute_ml_blended_probs(_RULE_PROBS, "REFLATION", 94.8, ml_weight=0.0)
    for r in REGIMES:
        assert abs(result.blended[r] - _RULE_PROBS[r]) < 1e-9


def test_ml_blended_weight_one_equals_ml_raw():
    result = compute_ml_blended_probs(_RULE_PROBS, "REFLATION", 94.8, ml_weight=1.0)
    for r in REGIMES:
        assert abs(result.blended[r] - result.ml_raw[r]) < 1e-9


def test_ml_raw_concentration():
    result = compute_ml_blended_probs(_RULE_PROBS, "STAGFLATION", 80.0)
    assert abs(result.ml_raw["STAGFLATION"] - 0.80) < 1e-9
    remaining = (1.0 - 0.80) / (len(REGIMES) - 1)
    for r in REGIMES:
        if r != "STAGFLATION":
            assert abs(result.ml_raw[r] - remaining) < 1e-9


def test_ml_blended_dominant_skews_toward_ml():
    result = compute_ml_blended_probs(_RULE_PROBS, "REFLATION", 94.8, ml_weight=0.30)
    assert result.blended["REFLATION"] > _RULE_PROBS["REFLATION"]


def test_ml_blended_invalid_regime_raises():
    with pytest.raises(ValueError, match="Unknown ml_regime"):
        compute_ml_blended_probs(_RULE_PROBS, "RECESSION", 80.0)


def test_ml_blended_invalid_confidence_raises():
    with pytest.raises(ValueError, match="ml_confidence"):
        compute_ml_blended_probs(_RULE_PROBS, "REFLATION", 120.0)


def test_ml_blended_rule_is_copy_not_reference():
    original = dict(_RULE_PROBS)
    result = compute_ml_blended_probs(original, "REFLATION", 94.8)
    result.rule["GOLDILOCKS"] = 999.0
    assert original["GOLDILOCKS"] == 0.21  # mutation guard
