from typing import NamedTuple

import numpy as np
from loguru import logger

REGIME_CENTROIDS: dict[str, tuple[float, float]] = {
    "GOLDILOCKS":  (75.0, 25.0),
    "REFLATION":   (75.0, 75.0),
    "STAGFLATION": (25.0, 75.0),
    "DEFLATION":   (25.0, 25.0),
}

REGIMES = list(REGIME_CENTROIDS.keys())


class BlendedResult(NamedTuple):
    blended: dict[str, float]  # allocation-ready probabilities (ML×weight + rule×(1-weight))
    ml_raw:  dict[str, float]  # ML-only probability vector (for storage/audit)
    rule:    dict[str, float]  # rule-only probabilities (reference copy)


def compute_regime_probabilities(
    growth_score: float,
    inflation_score: float,
    tau: float = 20.0,
) -> dict[str, float]:
    """Euclidean distance to each regime centroid → softmax probabilities.

    tau controls temperature: lower = sharper/more decisive,
    higher = more blended across regimes.
    When the signal is ambiguous (near center), entropy is high and
    the blended allocation naturally becomes more diversified.
    """
    distances = {
        regime: float(np.hypot(growth_score - g, inflation_score - i))
        for regime, (g, i) in REGIME_CENTROIDS.items()
    }
    exp_scores = {r: float(np.exp(-d / tau)) for r, d in distances.items()}
    total = sum(exp_scores.values())
    probs = {r: v / total for r, v in exp_scores.items()}

    logger.debug(
        "regime_probabilities "
        f"growth={growth_score:.1f} inflation={inflation_score:.1f} tau={tau} "
        + " ".join(f"{r}={p:.3f}" for r, p in probs.items())
    )
    return probs


def compute_ml_blended_probs(
    rule_probs: dict[str, float],
    ml_regime: str,
    ml_confidence: float,
    ml_weight: float = 0.30,
) -> BlendedResult:
    """Blend rule-based softmax probabilities with an XGBoost ML prediction.

    Converts the ML hard prediction + confidence into a probability vector
    (confidence on predicted regime, remaining mass split equally across others),
    then linearly blends with rule_probs.

    Returns a BlendedResult(blended, ml_raw, rule) named tuple so callers can
    store all three vectors without re-computing.
    """
    if ml_regime not in REGIMES:
        raise ValueError(f"Unknown ml_regime '{ml_regime}'. Must be one of {REGIMES}")
    if not (0.0 <= ml_confidence <= 100.0):
        raise ValueError(f"ml_confidence must be 0–100, got {ml_confidence}")
    if not (0.0 <= ml_weight <= 1.0):
        raise ValueError(f"ml_weight must be 0–1, got {ml_weight}")

    conf = float(ml_confidence) / 100.0  # cast numpy.float32 → Python float
    remaining = (1.0 - conf) / (len(REGIMES) - 1)
    ml_raw = {r: (conf if r == ml_regime else remaining) for r in REGIMES}

    blended_raw = {
        r: (1.0 - ml_weight) * float(rule_probs.get(r, 0.0)) + ml_weight * ml_raw[r]
        for r in REGIMES
    }
    total = sum(blended_raw.values())
    blended = {r: float(v / total) for r, v in blended_raw.items()}

    logger.debug(
        f"ml_blended ml_regime={ml_regime} ml_conf={ml_confidence:.1f} weight={ml_weight} "
        + " ".join(f"{r}={blended[r]:.3f}" for r in REGIMES)
    )
    return BlendedResult(blended=blended, ml_raw=ml_raw, rule=dict(rule_probs))
