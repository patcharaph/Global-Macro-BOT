import pandas as pd
import pytest
from flowmacro.regime.indicators import INDICATORS
from flowmacro.regime.scorer import compute_scores


def _frame(value: float, names: list[str] | None = None) -> pd.DataFrame:
    """Single-row DataFrame with all (or selected) indicator names at a given value."""
    if names is None:
        names = [i.name for i in INDICATORS]
    return pd.DataFrame([{n: value for n in names}])


# ── output range ─────────────────────────────────────────────────────────────

def test_all_50_gives_50():
    result = compute_scores(_frame(50.0))
    assert result["growth_score"].iloc[0] == pytest.approx(50.0, abs=1e-6)
    assert result["inflation_score"].iloc[0] == pytest.approx(50.0, abs=1e-6)


def test_all_100_gives_100():
    result = compute_scores(_frame(100.0))
    assert result["growth_score"].iloc[0] == pytest.approx(100.0, abs=1e-6)
    assert result["inflation_score"].iloc[0] == pytest.approx(100.0, abs=1e-6)


def test_all_0_gives_0():
    result = compute_scores(_frame(0.0))
    assert result["growth_score"].iloc[0] == pytest.approx(0.0, abs=1e-6)
    assert result["inflation_score"].iloc[0] == pytest.approx(0.0, abs=1e-6)


def test_scores_bounded_with_random_values():
    import numpy as np
    rng = pd.DataFrame(
        [{i.name: float(v) for i, v in zip(INDICATORS, values)}
         for values in [list(range(0, len(INDICATORS)))]],
    )
    result = compute_scores(rng)
    assert 0 <= result["growth_score"].iloc[0] <= 100
    assert 0 <= result["inflation_score"].iloc[0] <= 100


# ── axis independence ─────────────────────────────────────────────────────────

def test_growth_and_inflation_independent():
    growth_names = [i.name for i in INDICATORS if i.axis == "growth"]
    inflation_names = [i.name for i in INDICATORS if i.axis == "inflation"]
    row = {n: 80.0 for n in growth_names}
    row.update({n: 20.0 for n in inflation_names})
    result = compute_scores(pd.DataFrame([row]))
    assert result["growth_score"].iloc[0] > result["inflation_score"].iloc[0]


# ── missing tiers ─────────────────────────────────────────────────────────────

def test_tier1_only_still_computes():
    tier1_names = [i.name for i in INDICATORS if i.tier == 1]
    result = compute_scores(_frame(75.0, tier1_names))
    assert not pd.isna(result["growth_score"].iloc[0])
    assert not pd.isna(result["inflation_score"].iloc[0])


def test_no_indicators_returns_nan():
    result = compute_scores(pd.DataFrame([{"unrelated_col": 50.0}]))
    assert pd.isna(result["growth_score"].iloc[0])
    assert pd.isna(result["inflation_score"].iloc[0])


# ── tier weight proportionality ───────────────────────────────────────────────

def test_tier1_at_100_pulls_score_higher_than_tier3_at_100():
    # T1 indicators at 100, T2+T3 at 0 → score > 50
    # T3 indicators at 100, T1+T2 at 0 → score < T1-only result
    growth_inds = [i for i in INDICATORS if i.axis == "growth"]
    t1_names = [i.name for i in growth_inds if i.tier == 1]
    other_names = [i.name for i in growth_inds if i.tier != 1]

    row_t1_high = {n: 100.0 for n in t1_names}
    row_t1_high.update({n: 0.0 for n in other_names})

    t3_names = [i.name for i in growth_inds if i.tier == 3]
    other_names2 = [i.name for i in growth_inds if i.tier != 3]
    row_t3_high = {n: 100.0 for n in t3_names}
    row_t3_high.update({n: 0.0 for n in other_names2})

    # Add inflation indicators at neutral (50) for both
    inflation_names = [i.name for i in INDICATORS if i.axis == "inflation"]
    for row in (row_t1_high, row_t3_high):
        row.update({n: 50.0 for n in inflation_names})

    res_t1 = compute_scores(pd.DataFrame([row_t1_high]))["growth_score"].iloc[0]
    res_t3 = compute_scores(pd.DataFrame([row_t3_high]))["growth_score"].iloc[0]
    assert res_t1 > res_t3
