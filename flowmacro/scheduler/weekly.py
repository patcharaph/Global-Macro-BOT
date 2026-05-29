import sys
from datetime import date
import pandas as pd
from loguru import logger
from flowmacro.data.sources.fred import fetch_series
from flowmacro.data.store import upsert_series, read_series
from flowmacro.regime.indicators import INDICATORS, normalize
from flowmacro.regime.scorer import compute_scores
from flowmacro.regime.classifier import classify

_FRED_SERIES = [
    "T10Y2Y", "BAMLH0A0HYM2", "T5YIE", "USSLIND",
    "NAPM", "UNRATE", "A191RL1Q225SBEA", "CPIAUCSL",
]

_START_FETCH = "2005-01-01"
_START_COMPUTE = "2019-01-01"  # 6 years for 5-year rolling window + buffer


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
                # Forward-fill to daily so rolling window works for monthly/quarterly series
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

        # 5. Store in regime_history
        from supabase import create_client
        from flowmacro.config import settings
        create_client(settings.supabase_url, settings.supabase_key).table("regime_history").upsert({
            "run_date":       str(date.today()),
            "regime":         result.regime,
            "confidence":     result.confidence,
            "growth_score":   growth,
            "inflation_score": inflation,
        }).execute()

        # 6. Email alert
        from flowmacro.alerts.gmail import send_alert
        body = (
            f"Date:            {date.today()}\n"
            f"Regime:          {result.regime}\n"
            f"Confidence:      {result.confidence:.1f}%\n"
            f"Growth Score:    {growth:.1f}\n"
            f"Inflation Score: {inflation:.1f}\n"
            f"\nAvailable indicators ({len(normalized_latest)}): "
            f"{', '.join(normalized_latest.keys())}"
        )
        send_alert(f"Weekly Regime: {result.regime} ({result.confidence:.0f}%)", body)

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
