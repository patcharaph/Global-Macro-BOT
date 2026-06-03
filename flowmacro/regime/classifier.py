from dataclasses import dataclass
import pandas as pd
from flowmacro.config import settings

_REGIME_MAP = {
    (True,  False): "GOLDILOCKS",
    (True,  True):  "REFLATION",
    (False, True):  "STAGFLATION",
    (False, False): "DEFLATION",
}


@dataclass
class RegimeResult:
    regime: str
    confidence: float
    growth_score: float
    inflation_score: float


def _confidence(g: float, i: float) -> float:
    """Average deviation of both axes from neutral (50).

    Uses average instead of min so that a clear signal on one axis
    (e.g. strong growth with neutral inflation) still registers as
    confident, rather than being suppressed by the other axis.
    Max value = 100 (both axes at extreme 0 or 100).
    """
    return (abs(g - 50) + abs(i - 50))


def classify(growth_score: float, inflation_score: float) -> RegimeResult:
    """Classify a single (growth, inflation) pair into a regime."""
    if pd.isna(growth_score) or pd.isna(inflation_score):
        return RegimeResult("TRANSITIONING", float("nan"), growth_score, inflation_score)

    confidence = _confidence(growth_score, inflation_score)

    if confidence < settings.confidence_enter:
        regime = "TRANSITIONING"
    else:
        regime = _REGIME_MAP[(growth_score >= 50, inflation_score >= 50)]

    return RegimeResult(regime, confidence, growth_score, inflation_score)


def classify_series(scores_df: pd.DataFrame) -> pd.DataFrame:
    """Apply classification with hysteresis to a DataFrame of growth/inflation scores."""
    rows = []
    in_transitioning = False

    for _, row in scores_df.iterrows():
        g, i = row["growth_score"], row["inflation_score"]

        if pd.isna(g) or pd.isna(i):
            rows.append({"regime": "TRANSITIONING", "confidence": float("nan"),
                         "growth_score": g, "inflation_score": i})
            continue

        confidence = _confidence(g, i)

        if in_transitioning:
            if confidence >= settings.confidence_exit:
                in_transitioning = False
                regime = _REGIME_MAP[(g >= 50, i >= 50)]
            else:
                regime = "TRANSITIONING"
        else:
            if confidence < settings.confidence_enter:
                in_transitioning = True
                regime = "TRANSITIONING"
            else:
                regime = _REGIME_MAP[(g >= 50, i >= 50)]

        rows.append({"regime": regime, "confidence": confidence,
                     "growth_score": g, "inflation_score": i})

    return pd.DataFrame(rows, index=scores_df.index)
