"""Build and write the public FlowMacro snapshot JSON.

Streamlit Community Cloud has no public REST API, and the hosted app currently
redirects unauthenticated requests (including /_stcore/health) to Streamlit
login. This module writes a static file that GitHub Actions can commit so
anyone can `curl` it from raw.githubusercontent.com without logging in.

The two numbers that were both labelled "confidence" are stored under
distinct keys:

* v2_axis_confidence — abs(growth-50)+abs(inflation-50), 0–100
  (this is `regime_history.confidence` / the weekly email "Confidence")
* v3_dominant_prob_pct — softmax probability of the top regime, 0–100
  (this is what the dashboard status bar showed as "Confidence")
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from flowmacro.regime.classifier import classify
from flowmacro.regime.probabilities import compute_regime_probabilities

BANGKOK = ZoneInfo("Asia/Bangkok")
PUBLIC_JSON_NAME = "public/latest.json"
SCHEMA_VERSION = 1


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def public_json_path(root: Path | None = None) -> Path:
    return (root or repo_root()) / PUBLIC_JSON_NAME


def axis_deviation_confidence(growth_score: float, inflation_score: float) -> float:
    """V2 confidence: average-axis deviation from 50, stored in regime_history."""
    return abs(growth_score - 50.0) + abs(inflation_score - 50.0)


def business_days_between(start: date, end: date) -> int:
    """Count Mon–Fri days strictly after `start` up to and including `end`.

    Weekends only; market holidays are not excluded (called out as [ไม่แน่ใจ]).
    """
    if end < start:
        return -business_days_between(end, start)
    days = 0
    cursor = start
    while cursor < end:
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:
            days += 1
    return days


def snapshot_is_fresh(as_of: date, today: date | None = None, max_business_days: int = 1) -> bool:
    today = today or datetime.now(BANGKOK).date()
    return business_days_between(as_of, today) <= max_business_days


def _json_safe(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, float):
        return round(value, 4)
    return value


def build_snapshot(
    *,
    as_of: date,
    growth_score: float,
    inflation_score: float,
    generated_at: datetime | None = None,
    blended_weights: dict[str, float] | None = None,
    v2_regime: str | None = None,
    regime_probs: dict[str, float] | None = None,
    stale: list[dict[str, Any]] | None = None,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(BANGKOK)
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=BANGKOK)
    else:
        generated_at = generated_at.astimezone(BANGKOK)

    probs = regime_probs or compute_regime_probabilities(growth_score, inflation_score)
    classified = classify(growth_score, inflation_score)
    v2_name = v2_regime or classified.regime
    v2_conf = round(float(classified.confidence), 1) if v2_regime is None else round(
        axis_deviation_confidence(growth_score, inflation_score), 1
    )
    dominant = max(probs, key=lambda r: probs[r])
    dominant_pct = round(float(probs[dominant]) * 100, 1)
    fresh_flag = snapshot_is_fresh(as_of, generated_at.date())

    stale_rows = list(stale or [])
    total = len(stale_rows)
    fresh_n = sum(1 for row in stale_rows if row.get("status") == "ok")
    quality_pct = round(fresh_n / total * 100, 1) if total else None

    return {
        "schema_version": SCHEMA_VERSION,
        "as_of": as_of.isoformat(),
        "timezone": "Asia/Bangkok",
        "generated_at": generated_at.isoformat(),
        "fresh": fresh_flag,
        "regime": {
            "v3_dominant": dominant,
            "v3_dominant_prob_pct": dominant_pct,
            "v2_classified": v2_name,
            "v2_axis_confidence": v2_conf,
        },
        "growth_score": round(float(growth_score), 1),
        "inflation_score": round(float(inflation_score), 1),
        "regime_probabilities": {k: round(float(v), 4) for k, v in probs.items()},
        "blended_weights": {k: round(float(v), 4) for k, v in (blended_weights or {}).items()},
        "data_quality": {
            "fresh_count": fresh_n if total else None,
            "total": total or None,
            "score_pct": quality_pct,
            "series": stale_rows,
        },
        "labels": {
            "v3_dominant_prob_pct": "V3 softmax probability of the leading regime (0–100)",
            "v2_axis_confidence": (
                "V2 axis-deviation confidence: |growth-50| + |inflation-50| (0–100). "
                "This is what regime_history.confidence and the weekly email used to call Confidence."
            ),
        },
        "notes": notes or [],
    }


def write_snapshot(data: dict[str, Any], path: Path | None = None) -> Path:
    path = path or public_json_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _json_safe(data)
    # Never persist env-like keys if a caller accidentally forwarded settings.
    for banned in ("api_key", "supabase_key", "password", "token", "secret"):
        if banned in payload:
            raise ValueError(f"refusing to write a snapshot that contains {banned}")
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def format_status_confidence(v3_dominant_prob_pct: float | None, v2_axis_confidence: float | None) -> str:
    """Status-bar text that does not reuse the bare word 'Confidence' for both metrics."""
    parts = []
    if v3_dominant_prob_pct is not None:
        parts.append(f"V3 {v3_dominant_prob_pct:.0f}%")
    if v2_axis_confidence is not None:
        parts.append(f"V2 {v2_axis_confidence:.1f}")
    return " · ".join(parts) if parts else "—"



def export_from_store(
    *,
    as_of: date,
    read_series=None,
    blended_weights: dict[str, float] | None = None,
    path: Path | None = None,
    notes: list[str] | None = None,
) -> Path:
    """Build a snapshot from already-written Supabase series (used by the daily job).

    `read_series` is injectable so tests never touch a real database or API key.
    """
    if read_series is None:
        from flowmacro.data.store import read_series as read_series  # noqa: PLW0621

    start = "2020-01-01"

    def last(series_id: str) -> tuple[float | None, date | None]:
        series = read_series(series_id, start=start)
        if series is None or getattr(series, "empty", True):
            return None, None
        valid = series.dropna()
        if valid.empty:
            return None, None
        idx = valid.last_valid_index()
        day = idx.date() if hasattr(idx, "date") else idx
        return float(valid.iloc[-1]), day

    growth, _ = last("growth_score")
    inflation, _ = last("inflation_score")
    if growth is None or inflation is None:
        raise ValueError("growth_score / inflation_score missing — run the weekly job first")

    probs: dict[str, float] = {}
    for regime, series_id in (
        ("GOLDILOCKS", "regime_prob_goldilocks"),
        ("REFLATION", "regime_prob_reflation"),
        ("STAGFLATION", "regime_prob_stagflation"),
        ("DEFLATION", "regime_prob_deflation"),
    ):
        value, _ = last(series_id)
        if value is not None:
            probs[regime] = value
    if len(probs) != 4:
        probs = None  # type: ignore[assignment]

    weights = dict(blended_weights or {})
    if not weights:
        # Optional: ignore missing blend weights; the snapshot still has regime data.
        pass

    data = build_snapshot(
        as_of=as_of,
        growth_score=growth,
        inflation_score=inflation,
        regime_probs=probs,
        blended_weights=weights or None,
        notes=notes,
    )
    return write_snapshot(data, path)


def _demo_snapshot(today: date | None = None) -> dict[str, Any]:
    """Deterministic sample for local curl demos. Not live market data."""
    today = today or datetime.now(BANGKOK).date()
    # The 13 Nov 2026 weekly run (growth=70.1, inflation=61.4) is the
    # pair that produced the reported 61% vs 31.6% labels.
    return build_snapshot(
        as_of=today,
        growth_score=70.1,
        inflation_score=61.4,
        generated_at=datetime.now(BANGKOK),
        notes=["demo snapshot — not live data; as_of set to today so local freshness checks pass"],
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write FlowMacro public/latest.json")
    parser.add_argument("--out", type=Path, default=None, help="Output path (default: repo public/latest.json)")
    parser.add_argument("--demo", action="store_true", help="Write a local demo snapshot (no API keys)")
    args = parser.parse_args(argv)
    if not args.demo:
        raise SystemExit("Refusing to hit live APIs from this CLI. Use --demo for a local fixture, "
                         "or run the daily/weekly job which already has credentials.")
    path = write_snapshot(_demo_snapshot(), args.out)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
