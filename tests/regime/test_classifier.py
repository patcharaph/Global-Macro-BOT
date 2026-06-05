import math
import pandas as pd
import pytest
from flowmacro.regime.classifier import classify, classify_series


# ---------------------------------------------------------------------------
# classify() — single-point tests
# ---------------------------------------------------------------------------

def test_classify_goldilocks():
    # growth=75, inflation=25 → confidence = min(2*25, 2*25) = 50 → GOLDILOCKS
    result = classify(75.0, 25.0)
    assert result.regime == "GOLDILOCKS"
    assert result.confidence == pytest.approx(50.0)


def test_classify_reflation():
    # growth=75, inflation=75 → confidence = 50 → REFLATION
    result = classify(75.0, 75.0)
    assert result.regime == "REFLATION"


def test_classify_stagflation():
    # growth=25, inflation=75 → confidence = 50 → STAGFLATION
    result = classify(25.0, 75.0)
    assert result.regime == "STAGFLATION"


def test_classify_deflation():
    # growth=25, inflation=25 → confidence = 50 → DEFLATION
    result = classify(25.0, 25.0)
    assert result.regime == "DEFLATION"


def test_classify_transitioning_when_confidence_below_15():
    # growth=60, inflation=52 → confidence = |10| + |2| = 12 < enter=15 → TRANSITIONING
    result = classify(60.0, 52.0)
    assert result.regime == "TRANSITIONING"
    assert result.confidence == pytest.approx(12.0)


def test_classify_transitioning_on_nan_input():
    result = classify(float("nan"), 75.0)
    assert result.regime == "TRANSITIONING"
    assert math.isnan(result.confidence)


# ---------------------------------------------------------------------------
# classify_series() — hysteresis tests
# ---------------------------------------------------------------------------

def _make_scores(rows: list[tuple[float, float]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["growth_score", "inflation_score"])


def test_hysteresis_stays_transitioning_until_confidence_exits():
    # Row 0: confidence=50 → GOLDILOCKS (50 >= enter=15)
    # Row 1: confidence=12 → enter TRANSITIONING (12 < enter=15)
    # Row 2: confidence=17 → stays TRANSITIONING (17 < exit=20, hysteresis holds)
    # Row 3: confidence=60 → exit TRANSITIONING → GOLDILOCKS (60 >= exit=20)
    scores = _make_scores([
        (75.0, 25.0),   # |25|+|25| = 50 → GOLDILOCKS
        (60.0, 52.0),   # |10|+|2|  = 12 → enter TRANSITIONING
        (61.0, 56.0),   # |11|+|6|  = 17 → stays TRANSITIONING (17 < exit=20)
        (80.0, 20.0),   # |30|+|30| = 60 → exit → GOLDILOCKS
    ])

    result = classify_series(scores)

    assert result["regime"].tolist() == [
        "GOLDILOCKS",
        "TRANSITIONING",
        "TRANSITIONING",  # hysteresis: 45 >= 40 but < 50, must stay
        "GOLDILOCKS",
    ]
