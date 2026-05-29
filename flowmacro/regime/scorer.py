import pandas as pd
from flowmacro.regime.indicators import INDICATORS, TIER_WEIGHTS


def compute_scores(normalized: pd.DataFrame) -> pd.DataFrame:
    """
    Compute growth_score and inflation_score from normalized indicator values.

    normalized: DataFrame with indicator names as columns (values 0-100), dates as index.
    Returns DataFrame with columns: growth_score, inflation_score.
    """
    result = pd.DataFrame(index=normalized.index)

    for axis in ("growth", "inflation"):
        axis_inds = [i for i in INDICATORS if i.axis == axis]

        tier_means: dict[int, pd.Series] = {}
        for tier in (1, 2, 3):
            cols = [i.name for i in axis_inds if i.tier == tier and i.name in normalized.columns]
            if cols:
                tier_means[tier] = normalized[cols].mean(axis=1)

        if not tier_means:
            result[f"{axis}_score"] = float("nan")
            continue

        total_weight = sum(TIER_WEIGHTS[t] for t in tier_means)
        score = sum(TIER_WEIGHTS[t] * s for t, s in tier_means.items()) / total_weight
        result[f"{axis}_score"] = score

    return result
