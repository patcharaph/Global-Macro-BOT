import pytest
from flowmacro.portfolio.rebalance import needs_rebalance, compute_trades


# ── needs_rebalance ──────────────────────────────────────────────────────────

def test_no_rebalance_when_drift_below_band():
    current = {"SPY": 0.20, "Cash": 0.80}
    target  = {"SPY": 0.21, "Cash": 0.79}  # drift = 1% < 2% band
    assert not needs_rebalance(current, target)


def test_rebalance_when_drift_exceeds_band():
    current = {"SPY": 0.20, "Cash": 0.80}
    target  = {"SPY": 0.25, "Cash": 0.75}  # drift = 5% > 2% band
    assert needs_rebalance(current, target)


def test_rebalance_exactly_at_band_not_triggered():
    current = {"SPY": 0.20}
    target  = {"SPY": 0.22}  # drift = 2.0% exactly — not strictly greater
    assert not needs_rebalance(current, target, band=0.02)


def test_rebalance_new_asset_counts_as_drift():
    current = {"SPY": 0.80}
    target  = {"SPY": 0.70, "GLD": 0.10}  # GLD new → 10% drift
    assert needs_rebalance(current, target)


def test_rebalance_removed_asset_counts_as_drift():
    current = {"SPY": 0.60, "GLD": 0.20}
    target  = {"SPY": 0.60}  # GLD removed → 20% drift
    assert needs_rebalance(current, target)


def test_custom_band():
    current = {"SPY": 0.20}
    target  = {"SPY": 0.24}  # 4% drift
    assert not needs_rebalance(current, target, band=0.05)
    assert needs_rebalance(current, target, band=0.03)


# ── compute_trades ───────────────────────────────────────────────────────────

def test_buy_trade_generated():
    current = {"SPY": 0.20, "Cash": 0.80}
    target  = {"SPY": 0.30, "Cash": 0.70}
    trades = compute_trades(current, target, portfolio_value=10_000.0)
    spy_trade = next(t for t in trades if t["asset"] == "SPY")
    assert spy_trade["action"] == "BUY"
    assert spy_trade["value_change"] == pytest.approx(1000.0)


def test_sell_trade_generated():
    current = {"SPY": 0.40}
    target  = {"SPY": 0.20}
    trades = compute_trades(current, target, portfolio_value=10_000.0)
    assert trades[0]["action"] == "SELL"
    assert trades[0]["value_change"] == pytest.approx(-2000.0)


def test_no_trade_below_minimum_size():
    current = {"SPY": 0.20000}
    target  = {"SPY": 0.20050}  # drift = 0.05% < 0.1% minimum
    trades = compute_trades(current, target, portfolio_value=10_000.0)
    assert trades == []


def test_trade_count_matches_drifted_assets():
    current = {"SPY": 0.20, "GLD": 0.10, "Cash": 0.70}
    target  = {"SPY": 0.30, "GLD": 0.10, "Cash": 0.60}  # only SPY and Cash drift
    trades = compute_trades(current, target, portfolio_value=10_000.0)
    assert len(trades) == 2
