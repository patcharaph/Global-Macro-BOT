import math
import pytest
from flowmacro.scheduler.weekly import _should_alert, _LOW_CONFIDENCE_THRESHOLD


# ---------------------------------------------------------------------------
# _should_alert() — should_send controls only the [ALERT]/[Update] tag; the
# weekly job sends an email every Friday regardless. Every branch must return
# a reason that is true on its own terms — never assert "no regime change" /
# "confidence normal" when that isn't actually known.
# ---------------------------------------------------------------------------

def test_unknown_previous_is_flagged_not_silenced():
    """Supabase read failure: must NOT claim 'no regime change' — we can't know that."""
    should_send, reason = _should_alert("REFLATION", 45.0, "UNKNOWN")
    assert should_send is True
    assert "regime change" not in reason.lower() or "cannot verify" in reason.lower()
    assert "unknown" in reason.lower() or "failed" in reason.lower()


def test_first_run_alerts():
    should_send, reason = _should_alert("REFLATION", 45.0, None)
    assert should_send is True
    assert "first run" in reason.lower()


def test_nan_confidence_is_flagged_not_silenced():
    """NaN confidence: must NOT claim 'confidence normal' — it's unknown, not normal."""
    should_send, reason = _should_alert("REFLATION", float("nan"), "REFLATION")
    assert should_send is True
    assert "normal" not in reason.lower()
    assert "nan" in reason.lower()


def test_regime_changed_alerts():
    should_send, reason = _should_alert("STAGFLATION", 45.0, "REFLATION")
    assert should_send is True
    assert "REFLATION" in reason and "STAGFLATION" in reason


def test_low_confidence_alerts():
    low_conf = _LOW_CONFIDENCE_THRESHOLD - 1
    should_send, reason = _should_alert("REFLATION", low_conf, "REFLATION")
    assert should_send is True
    assert "low confidence" in reason.lower()


def test_routine_week_does_not_alert_but_has_accurate_reason():
    high_conf = _LOW_CONFIDENCE_THRESHOLD + 10
    should_send, reason = _should_alert("REFLATION", high_conf, "REFLATION")
    assert should_send is False
    assert "no regime change" in reason.lower()
    assert "confidence normal" in reason.lower()


@pytest.mark.parametrize("regime,confidence,previous", [
    ("REFLATION", 45.0, "UNKNOWN"),
    ("REFLATION", 45.0, None),
    ("REFLATION", float("nan"), "REFLATION"),
    ("STAGFLATION", 45.0, "REFLATION"),
    ("REFLATION", 5.0, "REFLATION"),
    ("REFLATION", 90.0, "REFLATION"),
])
def test_reason_is_never_empty(regime, confidence, previous):
    """Every branch must produce a non-empty reason — the caller no longer
    has a fallback string, so an empty reason would surface as blank text
    in a live email."""
    _, reason = _should_alert(regime, confidence, previous)
    assert reason != ""
    assert not (isinstance(reason, float) and math.isnan(reason))
