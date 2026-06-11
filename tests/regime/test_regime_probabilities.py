import pytest
from flowmacro.regime.probabilities import compute_regime_probabilities, REGIME_CENTROIDS


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
