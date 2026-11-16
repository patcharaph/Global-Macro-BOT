"""T7a: public snapshot JSON, freshness rule, and the 61% vs 31.6% label split."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from flowmacro.export.snapshot import (
    axis_deviation_confidence,
    build_snapshot,
    business_days_between,
    export_from_store,
    format_status_confidence,
    snapshot_is_fresh,
    write_snapshot,
)
from flowmacro.regime.classifier import classify
from flowmacro.regime.probabilities import compute_regime_probabilities

# Numbers from the 13 Nov 2026 weekly Actions log (no secrets).
# "Regime=REFLATION confidence=31.6% growth=70.1 inflation=61.4 | … REFL=61.14%"
_G, _I = 70.1, 61.4
BANGKOK = ZoneInfo("Asia/Bangkok")


def test_v2_and_v3_numbers_match_the_13_nov_weekly_run():
    v2 = classify(_G, _I)
    probs = compute_regime_probabilities(_G, _I)
    assert v2.regime == "REFLATION"
    assert v2.confidence == pytest.approx(31.5, abs=0.15)  # log printed 31.6
    assert axis_deviation_confidence(_G, _I) == pytest.approx(v2.confidence)
    assert max(probs, key=probs.get) == "REFLATION"
    assert probs["REFLATION"] * 100 == pytest.approx(61.14, abs=0.2)


def test_snapshot_keeps_the_two_confidence_metrics_separate():
    snap = build_snapshot(as_of=date(2026, 11, 13), growth_score=_G, inflation_score=_I,
                          generated_at=datetime(2026, 11, 13, 14, 30, tzinfo=BANGKOK))
    assert snap["as_of"] == "2026-11-13"
    assert snap["timezone"] == "Asia/Bangkok"
    assert snap["regime"]["v3_dominant"] == "REFLATION"
    assert snap["regime"]["v3_dominant_prob_pct"] == pytest.approx(61.1, abs=0.2)
    assert snap["regime"]["v2_classified"] == "REFLATION"
    assert snap["regime"]["v2_axis_confidence"] == pytest.approx(31.5, abs=0.15)
    # The two values must not be collapsed into one field called "confidence".
    assert "confidence" not in snap["regime"]
    assert snap["regime"]["v3_dominant_prob_pct"] != snap["regime"]["v2_axis_confidence"]


def test_status_bar_label_does_not_reuse_a_bare_confidence_word():
    text = format_status_confidence(61.14, 31.5)
    assert "V3 61%" in text and "V2 31.5" in text
    assert "Confidence" not in text


def test_business_day_freshness_treats_friday_as_fresh_on_monday():
    friday, monday = date(2026, 11, 13), date(2026, 11, 16)
    assert business_days_between(friday, monday) == 1
    assert snapshot_is_fresh(friday, today=monday, max_business_days=1)
    tuesday = date(2026, 11, 17)
    assert business_days_between(friday, tuesday) == 2
    assert not snapshot_is_fresh(friday, today=tuesday, max_business_days=1)
    assert snapshot_is_fresh(monday, today=monday, max_business_days=1)


def test_write_snapshot_is_curlable_json_and_rejects_secrets(tmp_path):
    path = tmp_path / "latest.json"
    snap = build_snapshot(as_of=date(2026, 11, 16), growth_score=_G, inflation_score=_I,
                          generated_at=datetime(2026, 11, 16, 21, 0, tzinfo=BANGKOK))
    write_snapshot(snap, path)
    text = path.read_text(encoding="utf-8")
    assert '"as_of": "2026-11-16"' in text
    assert "v3_dominant_prob_pct" in text
    for banned in ("sb_secret", "sk-or-", "FRED_API_KEY", "SUPABASE_KEY", "password"):
        assert banned not in text
    bad = dict(snap)
    bad["api_key"] = "should-not-be-written"
    with pytest.raises(ValueError, match="api_key"):
        write_snapshot(bad, tmp_path / "bad.json")
    assert not (tmp_path / "bad.json").exists()


def test_export_from_store_uses_injected_reader_and_needs_no_api_keys(tmp_path, monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_KEY", raising=False)
    monkeypatch.delenv("FRED_API_KEY", raising=False)

    idx = pd.to_datetime(["2026-11-13"])
    series = {
        "growth_score": pd.Series([_G], index=idx),
        "inflation_score": pd.Series([_I], index=idx),
        "regime_prob_goldilocks": pd.Series([0.200], index=idx),
        "regime_prob_reflation": pd.Series([0.611], index=idx),
        "regime_prob_stagflation": pd.Series([0.119], index=idx),
        "regime_prob_deflation": pd.Series([0.069], index=idx),
    }

    def fake_read(series_id, start="2020-01-01", end=None):
        return series.get(series_id, pd.Series(dtype=float, name=series_id))

    path = export_from_store(
        as_of=date(2026, 11, 16),
        read_series=fake_read,
        path=tmp_path / "latest.json",
        notes=["unit test"],
    )
    snap = path.read_text(encoding="utf-8")
    assert "2026-11-16" in snap and "REFLATION" in snap
    assert "61.1" in snap
