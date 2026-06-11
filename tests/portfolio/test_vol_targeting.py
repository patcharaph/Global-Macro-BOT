import numpy as np
import pandas as pd
import pytest
from flowmacro.portfolio.vol_targeting import apply_vol_targeting


def _make_returns(assets: list[str], weekly_vol: float, weeks: int = 30) -> pd.DataFrame:
    """Generate random weekly returns with given annualised vol."""
    rng = np.random.default_rng(seed=42)
    weekly_sigma = weekly_vol / np.sqrt(52)
    data = rng.normal(0, weekly_sigma, size=(weeks, len(assets)))
    return pd.DataFrame(data, columns=assets)


def test_no_leverage_scale_never_exceeds_one():
    # High vol → scale < 1.0
    returns = _make_returns(["SPY", "TLT"], weekly_vol=0.30, weeks=30)
    weights = {"SPY": 0.40, "TLT": 0.40}
    result = apply_vol_targeting(weights, returns, target_vol=0.10, max_scale=1.0)
    total_invested = sum(v for k, v in result.items() if k != "Cash")
    assert total_invested <= 0.80 + 1e-9


def test_low_vol_portfolio_not_levered():
    # Low vol → scale would be >1, but capped at max_scale=1.0
    returns = _make_returns(["SPY"], weekly_vol=0.02, weeks=30)
    weights = {"SPY": 0.40}
    result = apply_vol_targeting(weights, returns, target_vol=0.10, max_scale=1.0)
    assert result.get("SPY", 0.0) <= 0.40 + 1e-9


def test_cash_weight_sums_to_one():
    returns = _make_returns(["SPY", "GLD"], weekly_vol=0.20, weeks=30)
    weights = {"SPY": 0.30, "GLD": 0.20}
    result = apply_vol_targeting(weights, returns)
    total = sum(result.values())
    assert abs(total - 1.0) < 1e-6


def test_high_vol_reduces_exposure():
    # Very high vol → scale < 1 → invested amount decreases, Cash increases
    returns = _make_returns(["SPY"], weekly_vol=0.50, weeks=30)
    weights = {"SPY": 0.80}
    result = apply_vol_targeting(weights, returns, target_vol=0.10)
    assert result.get("SPY", 0.0) < 0.80
    assert result.get("Cash", 0.0) > 0.20


def test_no_investable_assets_returns_unchanged():
    returns = _make_returns(["SPY"], weekly_vol=0.20, weeks=30)
    weights = {"Cash": 1.0}
    result = apply_vol_targeting(weights, returns)
    assert result == {"Cash": 1.0}


def test_insufficient_history_returns_unchanged():
    returns = _make_returns(["SPY"], weekly_vol=0.20, weeks=1)  # only 1 row
    weights = {"SPY": 0.40}
    result = apply_vol_targeting(weights, returns)
    assert result == {"SPY": 0.40}


def test_asset_not_in_returns_ignored():
    returns = _make_returns(["SPY"], weekly_vol=0.20, weeks=30)
    weights = {"QQQ": 0.40}  # QQQ not in returns
    result = apply_vol_targeting(weights, returns)
    assert result == {"QQQ": 0.40}
