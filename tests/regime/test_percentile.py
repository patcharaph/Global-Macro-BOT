import numpy as np
import pandas as pd
import pytest
from flowmacro.regime.indicators import Indicator, compute_percentile, normalize


def _series(n: int = 300) -> pd.Series:
    return pd.Series(np.arange(n, dtype=float))


# ── compute_percentile ───────────────────────────────────────────────────────

def test_output_bounded_0_to_100():
    result = compute_percentile(_series(), window_years=1)
    valid = result.dropna()
    assert not valid.empty
    assert (valid >= 0).all() and (valid <= 100).all()


def test_ascending_series_ends_near_100():
    # Monotonically increasing → last value is the max → percentile ≈ 100
    result = compute_percentile(_series(), window_years=1)
    assert result.dropna().iloc[-1] > 95.0


def test_descending_series_ends_near_0():
    series = pd.Series(np.arange(300, 0, -1, dtype=float))
    result = compute_percentile(series, window_years=1)
    assert result.dropna().iloc[-1] < 5.0


def test_min_periods_produces_nans_at_start():
    # With window_years=1 (252 days) and only 100 points, should return all NaN
    short = pd.Series(np.arange(100, dtype=float))
    result = compute_percentile(short, window_years=1)
    assert result.isna().all()


def test_constant_series_returns_nan_or_50():
    # All values equal → rank is undefined (or 50 depending on implementation)
    series = pd.Series([5.0] * 300)
    result = compute_percentile(series, window_years=1)
    valid = result.dropna()
    # Accept either all-NaN or all ≈ 50 (both are correct for constant input)
    if not valid.empty:
        assert ((valid >= 49.0) & (valid <= 51.0)).all()


# ── normalize (inverse flag) ─────────────────────────────────────────────────

def _ind(inverse: bool) -> Indicator:
    return Indicator("test", "TEST", "growth", 1, inverse, "fred")


def test_normalize_non_inverse_same_as_percentile():
    series = _series()
    raw = compute_percentile(series, window_years=1)
    normed = normalize(series, _ind(False), window_years=1)
    pd.testing.assert_series_equal(raw, normed)


def test_normalize_inverse_flips():
    # normal + inverse must sum to 100 at every valid point
    series = _series()
    normal = normalize(series, _ind(False), window_years=1).dropna()
    inverse = normalize(series, _ind(True), window_years=1).dropna()
    diff = (normal + inverse - 100).abs()
    assert (diff < 1e-9).all()


def test_normalize_inverse_ascending_ends_near_0():
    # Ascending series, inverse=True → last value ranks low
    result = normalize(_series(), _ind(True), window_years=1)
    assert result.dropna().iloc[-1] < 5.0
