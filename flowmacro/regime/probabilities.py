import numpy as np
from loguru import logger

REGIME_CENTROIDS: dict[str, tuple[float, float]] = {
    "GOLDILOCKS":  (75.0, 25.0),
    "REFLATION":   (75.0, 75.0),
    "STAGFLATION": (25.0, 75.0),
    "DEFLATION":   (25.0, 25.0),
}


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
