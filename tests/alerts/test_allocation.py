"""Tests for flowmacro.alerts.allocation — allocation section formatting."""
from flowmacro.alerts.allocation import format_allocation_section


# ── Single portfolio, no previous week ────────────────────────────────────

def test_no_previous_shows_plain_percentages_no_arrows():
    result = format_allocation_section(current_a={"SPY": 0.20, "GLD": 0.30}, prev_a=None)
    assert "->" not in result
    assert "20.0%" in result
    assert "30.0%" in result
    assert "[Port A - Rule-based]" in result


def test_no_real_cash_key_adds_full_residual_as_cash():
    result = format_allocation_section(current_a={"SPY": 0.60}, prev_a=None)
    assert "CASH" in result
    assert "40.0%" in result


# ── Week-over-week diff ───────────────────────────────────────────────────

def test_changed_asset_shows_diff_arrow_and_delta():
    result = format_allocation_section(
        current_a={"SPY": 0.30}, prev_a={"SPY": 0.20},
    )
    assert "20.0% -> 30.0%" in result
    assert "(+10.0%)" in result


def test_decreased_asset_shows_negative_delta():
    result = format_allocation_section(
        current_a={"SPY": 0.20}, prev_a={"SPY": 0.30},
    )
    assert "30.0% -> 20.0%" in result
    assert "(-10.0%)" in result


def test_change_below_threshold_shown_as_flat_no_arrow():
    result = format_allocation_section(
        current_a={"SPY": 0.201}, prev_a={"SPY": 0.200},
    )
    assert "->" not in result
    assert "20.1%" in result


def test_asset_below_threshold_in_both_periods_is_omitted():
    result = format_allocation_section(
        current_a={"SPY": 0.50, "SLV": 0.001},
        prev_a={"SPY": 0.50, "SLV": 0.002},
    )
    assert "SLV" not in result


# ── Real "Cash" key (momentum_filter.py) vs synthetic CASH residual ───────
# Regression tests for the bug where a real "Cash" position (freed weight
# from a momentum cut) and the synthetic leftover-to-100% "CASH" residual
# showed up as two separate, contradictory lines.

def test_real_cash_key_merges_with_synthetic_residual():
    result = format_allocation_section(
        current_a={"SPY": 0.20, "Cash": 0.50}, prev_a=None,
    )
    assert result.count("CASH") == 1
    assert "80.0%" in result  # 0.50 real Cash + 0.30 residual (1 - 0.20 - 0.50)


def test_real_cash_key_week_over_week_diff_is_single_line():
    result = format_allocation_section(
        current_a={"SPY": 0.20, "Cash": 0.50},
        prev_a={"SPY": 0.30, "Cash": 0.20},
    )
    assert result.count("CASH") == 1
    # prev: 0.20 real + 0.50 residual (1-0.30-0.20) = 70.0%
    # cur:  0.50 real + 0.30 residual (1-0.20-0.50) = 80.0%
    assert "70.0% -> 80.0%" in result
    assert "(+10.0%)" in result


# ── Port A vs Port B ───────────────────────────────────────────────────────

def test_current_b_none_shows_only_port_a():
    result = format_allocation_section(current_a={"SPY": 0.50}, prev_a=None, current_b=None)
    assert "[Port A - Rule-based]" in result
    assert "Port B" not in result


def test_matching_portfolios_show_single_merged_section():
    weights = {"SPY": 0.50}
    result = format_allocation_section(current_a=weights, prev_a=None, current_b=dict(weights))
    assert "[Port A = Port B]" in result
    assert "[Port B - ML-blend (paper)]" not in result


def test_diverging_portfolios_show_both_sections_separately():
    result = format_allocation_section(
        current_a={"SPY": 0.50}, prev_a=None, current_b={"SPY": 0.10},
    )
    assert "A != B" in result
    assert "[Port A - Rule-based]" in result
    assert "[Port B - ML-blend (paper)]" in result
