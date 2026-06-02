import sys
from datetime import date, timedelta
import pandas as pd
from loguru import logger
from flowmacro.data.sources.fred import fetch_series
from flowmacro.data.store import upsert_series, read_series
from flowmacro.regime.indicators import INDICATORS, normalize
from flowmacro.regime.scorer import compute_scores
from flowmacro.regime.classifier import classify

_FRED_SERIES = [
    "T10Y2Y", "BAA10Y", "T5YIE", "ICSA",
    "IPMAN", "UNRATE", "A191RL1Q225SBEA", "CPIAUCSL",
]
_COT_SERIES = [
    "cot_sp500_net", "cot_treasury10y_net",
    "cot_gold_net",  "cot_crude_net",
]

_START_FETCH = "2005-01-01"
_START_COMPUTE = "2019-01-01"  # 6 years for 5-year rolling window + buffer
_START_COT = str(date.today().year - 1) + "-01-01"  # previous + current year

_REGIME_CODE = {
    "GOLDILOCKS": 1, "REFLATION": 2,
    "STAGFLATION": 3, "DEFLATION": 4, "TRANSITIONING": 0,
}
_REGIME_NAME = {v: k for k, v in _REGIME_CODE.items()}

_LOW_CONFIDENCE_THRESHOLD = 60.0


def _previous_regime() -> str | None:
    """Read last stored regime from Supabase. Returns regime name or None."""
    try:
        yesterday = str(date.today() - timedelta(days=1))
        series = read_series("regime_code", start="2019-01-01", end=yesterday)
        if series.empty:
            return None
        last_val = series.dropna().iloc[-1]
        return _REGIME_NAME.get(int(last_val))
    except Exception as exc:
        logger.warning(f"Could not read previous regime: {exc}")
        return "UNKNOWN"


def _should_alert(regime: str, confidence: float, previous: str | None) -> tuple[bool, str]:
    """Return (should_send, reason)."""
    if previous == "UNKNOWN":
        return False, ""
    if previous is None:
        return True, "first run — no previous regime recorded"
    if regime != previous:
        return True, f"regime changed: {previous} → {regime}"
    if confidence < _LOW_CONFIDENCE_THRESHOLD:
        return True, f"low confidence: {confidence:.1f}%"
    return False, ""


def run() -> None:
    logger.info("Weekly job: start")
    try:
        # 1. Run daily job first (update prices + derived indicators)
        from flowmacro.scheduler.daily import run as daily_run
        daily_run()

        # 2. Fetch and store FRED indicators
        for series_id in _FRED_SERIES:
            try:
                data = fetch_series(series_id, start=_START_FETCH)
                upsert_series(series_id, data.dropna())
            except Exception as exc:
                logger.warning(f"FRED {series_id} skipped: {exc}")

        # 2b. Fetch and store COT indicators
        from flowmacro.data.sources.cot import fetch_cot_net
        for cot_id in _COT_SERIES:
            try:
                cot_data = fetch_cot_net(cot_id, start=_START_COT)
                upsert_series(cot_id, cot_data)
            except Exception as exc:
                logger.warning(f"COT {cot_id} skipped: {exc}")

        # Compute CPI YoY (% change from 12 months ago)
        cpi_raw = read_series("CPIAUCSL", start="2004-01-01")
        if not cpi_raw.empty:
            cpi_yoy = cpi_raw.pct_change(12) * 100
            upsert_series("cpi_yoy", cpi_yoy.dropna())

        # 3. Read indicators from Supabase, resample to daily, compute current percentile
        normalized_latest: dict[str, float] = {}
        for ind in INDICATORS:
            try:
                raw = read_series(ind.series_id, start=_START_COMPUTE)
                if raw.empty:
                    logger.warning(f"No data for {ind.name} ({ind.series_id})")
                    continue
                daily = raw.resample("D").ffill()
                normed = normalize(daily, ind, window_years=5)
                last_idx = normed.last_valid_index()
                if last_idx is not None:
                    normalized_latest[ind.name] = float(normed.loc[last_idx])
            except Exception as exc:
                logger.warning(f"Indicator {ind.name} skipped: {exc}")

        if len(normalized_latest) < 5:
            raise ValueError(f"Only {len(normalized_latest)} indicators available — aborting")

        logger.info(f"Normalized indicators: {normalized_latest}")

        # 4. Score and classify
        scores_df = pd.DataFrame([normalized_latest], index=[pd.Timestamp(date.today())])
        axis_scores = compute_scores(scores_df)
        growth    = float(axis_scores["growth_score"].iloc[0])
        inflation = float(axis_scores["inflation_score"].iloc[0])
        result    = classify(growth, inflation)

        logger.info(
            f"Regime={result.regime} confidence={result.confidence:.1f}% "
            f"growth={growth:.1f} inflation={inflation:.1f}"
        )

        # 5. Store regime data
        today_ts = pd.Timestamp(date.today())
        upsert_series("regime_code",       pd.Series([float(_REGIME_CODE[result.regime])], index=[today_ts]))
        upsert_series("regime_confidence", pd.Series([result.confidence], index=[today_ts]))
        upsert_series("growth_score",      pd.Series([growth], index=[today_ts]))
        upsert_series("inflation_score",   pd.Series([inflation], index=[today_ts]))

        # 5b. Paper trading — update persistent virtual portfolio
        paper_summary = ""
        try:
            from flowmacro.broker.paper_portfolio import update as paper_update
            paper_summary = paper_update(result.regime, date.today())
            if paper_summary:
                logger.info(f"Paper portfolio updated:\n{paper_summary}")
        except Exception as exc:
            logger.warning(f"Paper portfolio update skipped: {exc}")

        # 6. Alert — only on regime change or low confidence
        previous = _previous_regime()
        should_send, reason = _should_alert(result.regime, result.confidence, previous)

        # 7. Generate AI thesis
        thesis_body = ""
        try:
            from flowmacro.thesis.generator import generate_thesis, save_thesis
            thesis = generate_thesis(result.regime, result.confidence, growth, inflation)
            save_thesis(thesis)
            thesis_body = (
                f"\n\n{'─'*40}\n"
                f"AI THESIS (conviction {thesis.conviction}/10)\n"
                f"คำแนะนำ:   {thesis.recommendation}\n"
                f"เหตุผล:     {thesis.reasoning}\n"
                f"ความเสี่ยง: {thesis.risks}"
            )
            logger.info(f"Thesis generated: conviction={thesis.conviction}/10")
        except Exception as exc:
            logger.warning(f"Thesis generation skipped: {exc}")

        if should_send:
            from flowmacro.alerts.gmail import send_alert
            prev_str = previous or "unknown"
            paper_section = f"\n\n{'─'*40}\n{paper_summary}" if paper_summary else ""
            body = (
                f"Date:            {date.today()}\n"
                f"Regime:          {result.regime}\n"
                f"Previous:        {prev_str}\n"
                f"Confidence:      {result.confidence:.1f}%\n"
                f"Growth Score:    {growth:.1f}\n"
                f"Inflation Score: {inflation:.1f}\n"
                f"Reason:          {reason}\n"
                f"\nIndicators ({len(normalized_latest)}): "
                f"{', '.join(normalized_latest.keys())}"
                f"{thesis_body}"
                f"{paper_section}"
            )
            send_alert(f"Regime: {result.regime} ({result.confidence:.0f}%)", body)
        else:
            logger.info(f"No alert — regime unchanged ({result.regime}, confidence={result.confidence:.1f}%)")

        logger.info("Weekly job: done")

    except Exception as exc:
        logger.error(f"Weekly job failed: {exc}")
        try:
            from flowmacro.alerts.gmail import send_alert
            send_alert("Weekly Job FAILED", str(exc))
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    run()
