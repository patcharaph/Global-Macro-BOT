import pandas as pd
import pytest
from flowmacro.portfolio.momentum_filter import apply_momentum_filter


def _make_prices(asset: str, start: float, trend_pct: float, weeks: int = 30) -> pd.DataFrame:
    """Generate weekly prices with a constant percentage change per week."""
    prices = [start]
    for _ in range(weeks - 1):
        prices.append(prices[-1] * (1 + trend_pct))
    return pd.DataFrame({asset: prices})


def test_downtrending_asset_cut_50_pct():
    # Strong downtrend: both 13W and 26W returns well below -5%
    prices = _make_prices("SPY", start=100.0, trend_pct=-0.01, weeks=30)
    weights = {"SPY": 0.20, "GLD": 0.10}
    result = apply_momentum_filter(weights, prices)
    assert result["SPY"] == pytest.approx(0.10)  # 50% cut
    assert result["Cash"] == pytest.approx(0.10)  # freed weight


def test_uptrending_asset_not_cut():
    prices = _make_prices("SPY", start=100.0, trend_pct=0.005, weeks=30)
    weights = {"SPY": 0.20}
    result = apply_momentum_filter(weights, prices)
    assert result["SPY"] == pytest.approx(0.20)  # no cut


def test_fast_down_slow_positive_no_cut():
    # Strong uptrend for 26W then mild decline for 13W:
    #   26W return remains positive → dual confirmation not met → no cut
    prices_list = [100.0]
    for _ in range(26):
        prices_list.append(prices_list[-1] * 1.03)   # +3%/w for 26 weeks
    for _ in range(13):
        prices_list.append(prices_list[-1] * 0.982)  # -1.8%/w for 13 weeks
    prices = pd.DataFrame({"SPY": prices_list})
    # Verify: 13W return < -5%, 26W return > 0% (by construction)
    p = prices["SPY"]
    assert p.iloc[-1] / p.iloc[-13] - 1 < -0.05   # fast is negative
    assert p.iloc[-1] / p.iloc[-26] - 1 > 0.0     # slow is still positive
    weights = {"SPY": 0.20}
    result = apply_momentum_filter(weights, prices)
    assert result["SPY"] == pytest.approx(0.20)


def test_cash_key_not_cut():
    prices = _make_prices("Cash", start=1.0, trend_pct=-0.01, weeks=30)
    weights = {"Cash": 0.20}
    result = apply_momentum_filter(weights, prices)
    assert result["Cash"] == pytest.approx(0.20)


def test_asset_not_in_price_history_not_cut():
    prices = _make_prices("SPY", start=100.0, trend_pct=-0.01, weeks=30)
    weights = {"QQQ": 0.20}  # QQQ not in prices
    result = apply_momentum_filter(weights, prices)
    assert result["QQQ"] == pytest.approx(0.20)


def test_insufficient_history_not_cut():
    prices = _make_prices("SPY", start=100.0, trend_pct=-0.02, weeks=20)  # < 26W
    weights = {"SPY": 0.20}
    result = apply_momentum_filter(weights, prices)
    assert result["SPY"] == pytest.approx(0.20)


def test_multiple_assets_cut_correctly():
    prices_down = _make_prices("SPY", start=100.0, trend_pct=-0.015, weeks=30)
    prices_up   = _make_prices("GLD", start=100.0, trend_pct=0.005, weeks=30)
    prices = pd.concat([prices_down, prices_up], axis=1)
    weights = {"SPY": 0.20, "GLD": 0.10}
    result = apply_momentum_filter(weights, prices)
    assert result["SPY"] < 0.20    # SPY cut
    assert result["GLD"] == pytest.approx(0.10)  # GLD unchanged
    assert result["Cash"] > 0.0


def test_freed_weight_goes_to_cash():
    prices = _make_prices("SPY", start=100.0, trend_pct=-0.015, weeks=30)
    weights = {"SPY": 0.20}
    result = apply_momentum_filter(weights, prices)
    total = result["SPY"] + result.get("Cash", 0.0)
    assert abs(total - 0.20) < 1e-9
