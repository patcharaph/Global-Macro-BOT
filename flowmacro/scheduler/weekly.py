import sys
from datetime import date, timedelta
import pandas as pd
from loguru import logger
from flowmacro.data.sources.fred import fetch_series
from flowmacro.data.store import upsert_series, read_series
from flowmacro.regime.indicators import INDICATORS, normalize
from flowmacro.regime.scorer import compute_scores
from flowmacro.regime.classifier import classify
from flowmacro.regime.probabilities import compute_regime_probabilities
from flowmacro.portfolio.allocator import REGIME_WEIGHTS, compute_blended_weights
from flowmacro.portfolio.momentum_filter import apply_momentum_filter
from flowmacro.portfolio.vol_targeting import apply_vol_targeting
from flowmacro.portfolio.rebalance import needs_rebalance, compute_trades

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

_LOW_CONFIDENCE_THRESHOLD = 25.0  # was 60 — historical max confidence is 68.8, so 60
                                   # fired on 99.3% of weeks regardless of regime change.
                                   # 25 ~= p75-p80 of 854wk history → fires ~21% of weeks,
                                   # comparable to natural regime-change frequency (~1/4.8wk).
_USE_ML_V2 = False   # flip to True after graduation + promote_model_v2.py

# Live trading gate — set FLOWMACRO_LIVE_TRADING=true in GitHub Actions secrets to enable
# Requires: IB Gateway running + IBKR_HOST/IBKR_PORT/IBKR_CLIENT_ID env vars
import os as _os
_LIVE_TRADING   = _os.getenv("FLOWMACRO_LIVE_TRADING", "").lower() == "true"
_LIVE_DRY_RUN   = _os.getenv("FLOWMACRO_DRY_RUN", "").lower() == "true"  # connect but don't submit


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
    """Return (should_send, reason).

    should_send only controls the [ALERT] vs [Update] subject tag — the weekly
    job sends an email every Friday regardless (see run(), step 6). Every branch
    returns a reason that is true on its own terms; never assert "no regime
    change" / "confidence normal" when that genuinely isn't known (UNKNOWN
    previous-regime read failure, NaN confidence).
    """
    if previous == "UNKNOWN":
        return True, "previous regime unknown — Supabase read failed, cannot verify if it changed"
    if previous is None:
        return True, "first run — no previous regime recorded"
    if pd.isna(confidence):
        return True, "confidence is NaN — growth/inflation score unavailable this week"
    if regime != previous:
        return True, f"regime changed: {previous} → {regime}"
    if confidence < _LOW_CONFIDENCE_THRESHOLD:
        return True, f"low confidence: {confidence:.1f}%"
    return False, "routine weekly update — no regime change, confidence normal"


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
        result    = classify(growth, inflation)  # kept for ML comparison + dominant label

        # V3 Step 2: Softmax regime probabilities
        regime_probs = compute_regime_probabilities(growth, inflation)
        dominant_regime = max(regime_probs, key=lambda r: regime_probs[r])

        logger.info(
            f"Regime={result.regime} confidence={result.confidence:.1f}% "
            f"growth={growth:.1f} inflation={inflation:.1f} | "
            + " ".join(f"{r[:4]}={p:.2%}" for r, p in regime_probs.items())
        )

        # V3 Step 3: Blended allocation
        blended_weights = compute_blended_weights(regime_probs)
        logger.info(f"Blended weights (pre-filter): {blended_weights}")

        # V3 Steps 4–5: Momentum filter + vol targeting using 26W price history
        _lookback_start = str(date.today() - timedelta(weeks=32))
        _all_blend_tickers = list(blended_weights.keys())
        _price_frames: dict[str, pd.Series] = {}
        for _ticker in _all_blend_tickers:
            try:
                _raw = read_series(_ticker, start=_lookback_start)
                if not _raw.empty:
                    _price_frames[_ticker] = _raw.resample("W").last().dropna()
            except Exception as _exc:
                logger.warning(f"Price history for {_ticker} skipped: {_exc}")

        if _price_frames:
            price_history = pd.DataFrame(_price_frames)
            returns_df = price_history.pct_change().dropna()
            blended_weights = apply_momentum_filter(blended_weights, price_history)
            blended_weights = apply_vol_targeting(blended_weights, returns_df)
            logger.info(f"Final blended weights (post-filter): {blended_weights}")
        else:
            logger.warning("No price history available — skipping momentum filter and vol targeting")

        # V3 Step 6: Rebalance band check (informational for paper trading)
        # end=yesterday excludes any row already written by an earlier run today
        # (e.g. a manual re-run after the scheduled one) — mirrors the same
        # guard read_last_portfolio_b_weights() applies for Portfolio B.
        _prev_weights: dict[str, float] = {}
        try:
            _prev_weights_end = str(date.today() - timedelta(days=1))
            for _asset in _all_blend_tickers:
                _s = read_series(
                    f"blend_weight_{_asset.lower().replace('-', '_')}",
                    start=str(date.today() - timedelta(days=8)),
                    end=_prev_weights_end,
                )
                if not _s.empty:
                    _prev_weights[_asset] = float(_s.dropna().iloc[-1])
        except Exception:
            pass

        if _prev_weights:
            _should_rebal = needs_rebalance(_prev_weights, blended_weights)
            _trades = compute_trades(_prev_weights, blended_weights, 100_000.0) if _should_rebal else []
            logger.info(f"Rebalance needed: {_should_rebal} | {len(_trades)} trades")

        # V3 Step 6B: Live IBKR execution (only when FLOWMACRO_LIVE_TRADING=true)
        _exec_summary: dict = {}
        if _LIVE_TRADING or _LIVE_DRY_RUN:
            try:
                from flowmacro.broker.ibkr import IBKRBroker
                from flowmacro.broker.executor import execute_rebalance
                from flowmacro.broker.risk_guards import RiskGuardTripped
                _broker = IBKRBroker.connect()
                try:
                    _exec_summary = execute_rebalance(
                        broker         = _broker,
                        target_weights = blended_weights,
                        dry_run        = _LIVE_DRY_RUN,
                    )
                    logger.info(
                        f"IBKR execution: {_exec_summary['orders']} orders  "
                        f"portfolio=${_exec_summary['portfolio_value']:,.0f}  "
                        f"dry_run={_exec_summary['dry_run']}"
                    )
                    if _exec_summary["errors"]:
                        logger.error(f"IBKR order errors: {_exec_summary['errors']}")
                except RiskGuardTripped as rg:
                    logger.error(f"RISK GUARD TRIPPED — trading halted this week: {rg}")
                    try:
                        from flowmacro.alerts.gmail import send_alert
                        send_alert(
                            "[ALERT] FlowMacro RISK GUARD TRIPPED — trading halted",
                            f"Risk guard fired at {date.today()}:\n\n{rg}\n\n"
                            "No orders were submitted. Manual review required before next Friday.",
                        )
                    except Exception:
                        pass
                finally:
                    _broker.disconnect()
            except RiskGuardTripped:
                pass  # already handled above
            except Exception as exc:
                logger.error(f"IBKR execution failed: {exc}")
                try:
                    from flowmacro.alerts.gmail import send_alert
                    send_alert("FlowMacro IBKR Execution FAILED", str(exc))
                except Exception:
                    pass
        else:
            logger.info("Live trading disabled (FLOWMACRO_LIVE_TRADING != true) — paper only")

        # 5. Store regime data
        today_ts = pd.Timestamp(date.today())
        upsert_series("regime_code",       pd.Series([float(_REGIME_CODE[result.regime])], index=[today_ts]))
        upsert_series("regime_confidence", pd.Series([result.confidence], index=[today_ts]))
        upsert_series("growth_score",      pd.Series([growth], index=[today_ts]))
        upsert_series("inflation_score",   pd.Series([inflation], index=[today_ts]))

        # V3: Store regime probabilities and blended weights
        for _regime, _prob in regime_probs.items():
            upsert_series(
                f"regime_prob_{_regime.lower()}",
                pd.Series([_prob], index=[today_ts]),
            )
        for _asset, _w in blended_weights.items():
            _sid = f"blend_weight_{_asset.lower().replace('-', '_')}"
            upsert_series(_sid, pd.Series([_w], index=[today_ts]))

        # 5c. Write to regime_history (queryable history table, one row per week)
        from flowmacro.data.store import upsert_regime_history
        upsert_regime_history(
            str(date.today()), result.regime, result.confidence, growth, inflation
        )

        # 5d. Shadow ML prediction (does not affect portfolio — logging only)
        ml_regime = None
        ml_confidence = None
        try:
            from flowmacro.regime.ml_predictor import predict_ml
            from flowmacro.data.store import upsert_ml_regime_history
            ml_features = {**normalized_latest, "growth_score": growth, "inflation_score": inflation}
            ml_regime, ml_confidence = predict_ml(ml_features)
            agrees = ml_regime == result.regime
            upsert_ml_regime_history(str(date.today()), ml_regime, ml_confidence, result.regime)
            logger.info(
                f"ML shadow: regime={ml_regime} confidence={ml_confidence:.1f} "
                f"agrees_with_rb={agrees}"
            )
        except Exception as exc:
            logger.error(f"ML shadow failed: {exc}")
            try:
                from flowmacro.alerts.gmail import send_alert
                send_alert("FlowMacro ML Shadow FAILED", str(exc))
            except Exception:
                pass

        # 5b. Paper trading — update persistent virtual portfolio
        paper_summary = ""
        try:
            from flowmacro.broker.paper_portfolio import update as paper_update
            paper_summary = paper_update(result.regime, date.today())
            if paper_summary:
                logger.info(f"Paper portfolio updated:\n{paper_summary}")
        except Exception as exc:
            logger.warning(f"Paper portfolio update skipped: {exc}")

        # Step 6B: Portfolio B (ML-assisted) — virtual only, no live trades
        _pb_weights_final: dict[str, float] | None = None
        _prev_b_weights: dict[str, float] | None = None
        if ml_regime is not None:
            try:
                from flowmacro.regime.probabilities import compute_ml_blended_probs
                from flowmacro.broker.paper_portfolio import compute_virtual_b_value
                from flowmacro.data.store import upsert_paper_portfolio_ml, read_last_portfolio_b_weights

                _prev_b_weights = read_last_portfolio_b_weights(str(date.today()))

                blend_result = compute_ml_blended_probs(
                    rule_probs=regime_probs,
                    ml_regime=ml_regime,
                    ml_confidence=ml_confidence,
                    ml_weight=0.30,
                )
                _pb_weights = compute_blended_weights(blend_result.blended)
                if _price_frames:
                    _pb_weights = apply_momentum_filter(_pb_weights, price_history)
                    _pb_weights = apply_vol_targeting(_pb_weights, returns_df)

                _pb_prev_series = read_series(
                    "paper_total_value_b",
                    start=str(date.today() - timedelta(days=10)),
                )
                _pb_prev = (
                    float(_pb_prev_series.dropna().iloc[-1])
                    if not _pb_prev_series.empty else 3_000.0
                )

                _pb_value = compute_virtual_b_value(_pb_weights, date.today())
                _pb_return = (_pb_value - _pb_prev) / _pb_prev if _pb_prev > 0 else 0.0

                upsert_paper_portfolio_ml(
                    run_date=str(date.today()),
                    ml_blend_probs=blend_result.blended,
                    ml_raw_probs=blend_result.ml_raw,
                    rule_probs=blend_result.rule,
                    blend_weights=_pb_weights,
                    portfolio_value=_pb_value,
                    period_return=_pb_return,
                    ml_regime=ml_regime,
                    ml_confidence=ml_confidence,
                )
                logger.info(
                    f"Portfolio B: ml={ml_regime} conf={ml_confidence:.1f} "
                    f"week={_pb_return*100:+.2f}% value=${_pb_value:,.2f}"
                )
                _pb_weights_final = _pb_weights
            except Exception as exc:
                logger.warning(f"Portfolio B Step 6B failed: {exc}")

        # 5e. Features v2 — fetch latest values for macro_features_v2 table
        # Collects leading indicator data weekly; NOT used for model training until Dec 2026
        _v2_feat_dict: dict[str, float] = {}   # shared with step 5f below
        try:
            from flowmacro.data.features_v2 import build_features_v2
            from flowmacro.data.store import upsert_features_v2, read_features_v2

            # Need 260W window + max 52W return period + buffer
            _fv2_start = str(date.today() - timedelta(weeks=325))
            _fv2_df    = build_features_v2(start=_fv2_start)

            if not _fv2_df.empty:
                _fv2_latest = _fv2_df.iloc[-1]

                # Fallback: if latest row is all-NaN, use last stored value
                if _fv2_latest.isna().all():
                    _fv2_stored = read_features_v2(
                        start=str(date.today() - timedelta(days=14))
                    )
                    if not _fv2_stored.empty:
                        _fv2_latest = _fv2_stored.iloc[-1]
                        logger.warning("features_v2: all-NaN latest row — using last stored values as fallback")

                _v2_feat_dict = {col: float(val) for col, val in _fv2_latest.items() if pd.notna(val)}
                upsert_features_v2(str(date.today()), _v2_feat_dict)
                logger.info(f"features_v2 stored: {len(_v2_feat_dict)}/14 features for {date.today()}")
            else:
                logger.warning("features_v2: build returned empty DataFrame — skipped")
        except Exception as exc:
            logger.warning(f"features_v2 weekly update skipped: {exc}")

        # 5f. ML v2 shadow (gated — set _USE_ML_V2 = True after promote_model_v2.py)
        # Combines old indicator scores + new features_v2 → predict_ml_v2
        if _USE_ML_V2:
            try:
                from flowmacro.regime.ml_predictor import predict_ml_v2
                # Merge old features + new features_v2 into one dict
                _v2_combined = {
                    **normalized_latest,
                    "growth_score":    growth,
                    "inflation_score": inflation,
                    **_v2_feat_dict,
                }
                _ml_v2_regime, _ml_v2_conf = predict_ml_v2(_v2_combined)
                logger.info(
                    f"ML v2 shadow: regime={_ml_v2_regime} confidence={_ml_v2_conf:.1f} "
                    f"(v1={ml_regime}  agrees={_ml_v2_regime == ml_regime})"
                )
            except Exception as exc:
                logger.warning(f"ML v2 shadow failed: {exc}")

        # 6. Determine urgency — but ALWAYS send a weekly update (job only runs Fridays).
        #    should_send=True (regime changed / low confidence / first run) -> tagged ALERT.
        #    should_send=False (routine, no change)                          -> tagged Update.
        previous = _previous_regime()
        should_send, reason = _should_alert(result.regime, result.confidence, previous)
        _tag = "ALERT" if should_send else "Update"

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

        from flowmacro.alerts.gmail import send_alert
        prev_str = previous or "unknown"
        paper_section = f"\n\n{'─'*40}\n{paper_summary}" if paper_summary else ""
        _exec_section = ""
        if _exec_summary:
            _mode = "DRY-RUN" if _exec_summary.get("dry_run") else "LIVE"
            _exec_section = (
                f"\n\n{'─'*40}\n"
                f"IBKR Execution [{_mode}]\n"
                f"  Orders submitted: {_exec_summary['orders']}\n"
                f"  Portfolio value:  ${_exec_summary['portfolio_value']:,.2f}\n"
                f"  Order IDs:        {', '.join(_exec_summary['order_ids']) or '—'}\n"
                + (f"  ERRORS: {'; '.join(_exec_summary['errors'])}\n" if _exec_summary["errors"] else "")
            )

        # Format regime probabilities for email
        sorted_probs = sorted(regime_probs.items(), key=lambda x: x[1], reverse=True)
        _bar_width = 20
        probs_lines = "\n".join(
            f"  {r:<12} {p*100:5.1f}%  {'#' * round(p * _bar_width)}"
            for r, p in sorted_probs
        )
        top2_str = f"{sorted_probs[0][0]} {sorted_probs[0][1]:.1%}  >  {sorted_probs[1][0]} {sorted_probs[1][1]:.1%}"

        from flowmacro.alerts.allocation import format_allocation_section
        alloc_section = format_allocation_section(
            current_a=blended_weights,
            prev_a=_prev_weights or None,
            current_b=_pb_weights_final,
            prev_b=_prev_b_weights,
        )

        body = (
            f"Date:            {date.today()}\n"
            f"Regime:          {result.regime}\n"
            f"Previous:        {prev_str}\n"
            f"Confidence:      {result.confidence:.1f}%\n"
            f"Growth Score:    {growth:.1f}\n"
            f"Inflation Score: {inflation:.1f}\n"
            f"Reason:          {reason}\n"
            f"\nRegime Probabilities (V3 blend):\n{probs_lines}\n"
            f"Top 2: {top2_str}\n"
            f"\n{alloc_section}\n"
            f"\nIndicators ({len(normalized_latest)}): "
            f"{', '.join(normalized_latest.keys())}"
            f"{thesis_body}"
            f"{paper_section}"
            f"{_exec_section}"
        )
        _subject = f"[{_tag}] Regime: {result.regime} ({result.confidence:.0f}%)  [{top2_str}]"
        send_alert(_subject, body)
        logger.info(f"Weekly email sent [{_tag}]: {reason}")

        from flowmacro.alerts.line import send_line
        send_line(f"{_subject}\n\n{body}")

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
