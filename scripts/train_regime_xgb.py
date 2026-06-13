"""
Phase 1 — Offline XGBoost Regime Detection Experiment

Design decisions:
- Features   : 16 normalized indicator scores (0-100), same as rule-based system
- Labels     : regime_history from Supabase + NBER episode overrides
- Walk-forward: expanding window, 5-year initial train, 1-year step
- Confidence : (top1_prob - top2_prob) × 100
- Success    : walk-forward accuracy > 70% AND NBER ≥ 5/6 episodes pass

Usage:
    python scripts/train_regime_xgb.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pickle
import pandas as pd
from loguru import logger

from flowmacro.data.store import read_series
from flowmacro.regime.indicators import INDICATORS, normalize

# ── NBER ground-truth episode overrides ──────────────────────────────────────
NBER_EPISODES = [
    ("2008-09-01", "2009-03-31", "DEFLATION"),
    ("2010-06-01", "2011-06-30", "REFLATION"),
    ("2013-01-01", "2015-12-31", "GOLDILOCKS"),
    ("2020-03-01", "2020-04-30", "DEFLATION"),
    ("2021-06-01", "2022-06-30", "REFLATION"),
    ("2022-09-01", "2023-09-30", "STAGFLATION"),
]

REGIME_ENCODE = {"GOLDILOCKS": 0, "REFLATION": 1, "STAGFLATION": 2, "DEFLATION": 3}
REGIME_DECODE = {v: k for k, v in REGIME_ENCODE.items()}

_START_WARMUP        = "2005-01-01"
_START_LABELS        = "2010-01-01"
_INITIAL_TRAIN_YEARS = 5   # first expanding window: 2010–2015
_STEP_YEARS          = 1
_XGB_PARAMS = dict(
    n_estimators=100, max_depth=4, learning_rate=0.1,
    subsample=0.8, colsample_bytree=0.8,
    eval_metric="mlogloss", random_state=42, verbosity=0,
)


# ── Feature matrix ────────────────────────────────────────────────────────────

def build_feature_matrix() -> pd.DataFrame:
    """Pull 16 raw series → normalize → resample to weekly Friday."""
    normalized: dict[str, pd.Series] = {}
    for ind in INDICATORS:
        try:
            raw = read_series(ind.series_id, start=_START_WARMUP)
            if raw.empty:
                logger.warning(f"  {ind.name} ({ind.series_id}): empty — skipped")
                continue
            daily  = raw.resample("D").ffill()
            normed = normalize(daily, ind, window_years=5)
            normalized[ind.name] = normed
        except Exception as exc:
            logger.warning(f"  {ind.name} failed: {exc}")

    df     = pd.DataFrame(normalized)
    weekly = df.resample("W-FRI").last().ffill().loc[_START_LABELS:]

    # Add pre-computed axis scores from regime_history as direct features.
    # XGBoost can then learn the quadrant boundary (growth>50, inflation>50)
    # explicitly rather than re-deriving it from 15 individual scores.
    from flowmacro.config import settings
    from supabase import create_client
    client = create_client(settings.supabase_url, settings.supabase_key)
    axis_rows = (
        client.table("regime_history")
        .select("run_date, growth_score, inflation_score")
        .gte("run_date", _START_LABELS)
        .order("run_date")
        .execute()
        .data
    )
    if axis_rows:
        axis_df = (
            pd.DataFrame(axis_rows)
            .assign(run_date=lambda d: pd.to_datetime(d["run_date"]))
            .set_index("run_date")
        )
        weekly = weekly.join(axis_df[["growth_score", "inflation_score"]], how="left")
        weekly[["growth_score", "inflation_score"]] = (
            weekly[["growth_score", "inflation_score"]].ffill()
        )

    logger.info(
        f"Feature matrix: {weekly.shape[1]} features × {weekly.shape[0]} weeks "
        f"({weekly.index.min().date()} → {weekly.index.max().date()})"
    )
    nan_counts = weekly.isnull().sum()
    if nan_counts.any():
        logger.info(f"  NaN counts:\n{nan_counts[nan_counts > 0].to_string()}")
    return weekly


# ── Labels ────────────────────────────────────────────────────────────────────

def get_labels() -> pd.Series:
    """regime_history → apply NBER overrides → drop TRANSITIONING."""
    from flowmacro.config import settings
    from supabase import create_client

    client = create_client(settings.supabase_url, settings.supabase_key)
    rows = (
        client.table("regime_history")
        .select("run_date, regime")
        .gte("run_date", _START_LABELS)
        .order("run_date")
        .execute()
        .data
    )
    if not rows:
        raise ValueError("regime_history empty — run backfill_regime_history.py first")

    labels = (
        pd.DataFrame(rows)
        .assign(run_date=lambda d: pd.to_datetime(d["run_date"]))
        .set_index("run_date")["regime"]
    )

    for start_dt, end_dt, override in NBER_EPISODES:
        mask = (labels.index >= start_dt) & (labels.index <= end_dt)
        if mask.any():
            labels.loc[mask] = override

    labels = labels[labels != "TRANSITIONING"]
    logger.info(f"Labels: {len(labels)} rows | {labels.value_counts().to_dict()}")
    return labels


# ── Walk-forward validation ───────────────────────────────────────────────────

def walk_forward_validate(X: pd.DataFrame, y: pd.Series, xgb_params: dict | None = None) -> dict:
    from xgboost import XGBClassifier
    from sklearn.metrics import accuracy_score, classification_report

    y_enc = y.map(REGIME_ENCODE)
    # Require at least 12 of the available features (tolerates sparse COT early history)
    min_features = max(8, X.shape[1] - 4)
    data = X.join(y_enc.rename("label"), how="inner").dropna(subset=["label"])
    data = data.dropna(thresh=min_features + 1)  # +1 for label column

    logger.info(f"Aligned dataset: {len(data)} rows after dropna(thresh={min_features})")
    if data.empty:
        raise ValueError("No aligned rows — check that regime_history dates match feature matrix index")

    start_date = data.index.min()
    end_date   = data.index.max()
    train_end  = start_date + pd.DateOffset(years=_INITIAL_TRAIN_YEARS)

    all_preds: list[int] = []
    all_true:  list[int] = []
    fold_results = []

    while train_end < end_date:
        test_end = train_end + pd.DateOffset(years=_STEP_YEARS)
        train = data[data.index <  train_end]
        test  = data[(data.index >= train_end) & (data.index < test_end)]

        if len(train) < 40 or len(test) < 4:
            train_end = test_end
            continue

        train_median = train.median()
        train = train.fillna(train_median)
        test  = test.fillna(train_median)   # use train median to avoid leakage
        X_tr, y_tr = train.drop("label", axis=1), train["label"]
        X_te, y_te = test.drop("label", axis=1),  test["label"]

        model = XGBClassifier(**(xgb_params or _XGB_PARAMS))
        model.fit(X_tr, y_tr)
        preds = model.predict(X_te)
        acc   = accuracy_score(y_te, preds)

        fold_results.append({
            "test_period": f"{train_end.strftime('%Y-%m')} → {test_end.strftime('%Y-%m')}",
            "n_train": len(train), "n_test": len(test), "accuracy": acc,
        })
        logger.info(
            f"  {fold_results[-1]['test_period']}  "
            f"train={len(train):3d}  test={len(test):3d}  acc={acc:.1%}"
        )
        all_preds.extend(preds.tolist())
        all_true.extend(y_te.tolist())
        train_end = test_end

    if not all_true:
        raise ValueError("Walk-forward produced no test predictions — check data alignment")
    overall = accuracy_score(all_true, all_preds)
    present = sorted(set(all_true))
    report  = classification_report(
        all_true, all_preds,
        labels=present,
        target_names=[REGIME_DECODE[i] for i in present],
        zero_division=0,
    )
    return {
        "folds": fold_results, "overall_accuracy": overall,
        "report": report, "all_preds": all_preds, "all_true": all_true,
    }


# ── Final model ───────────────────────────────────────────────────────────────

def train_final(X: pd.DataFrame, y: pd.Series, xgb_params: dict | None = None):
    from xgboost import XGBClassifier

    y_enc = y.map(REGIME_ENCODE)
    min_features = max(8, X.shape[1] - 4)
    data = X.join(y_enc.rename("label"), how="inner").dropna(subset=["label"])
    data = data.dropna(thresh=min_features + 1)
    data = data.fillna(data.median())
    X_all, y_all = data.drop("label", axis=1), data["label"]

    model = XGBClassifier(**(xgb_params or _XGB_PARAMS))
    model.fit(X_all, y_all)
    return model, X_all.columns.tolist()


# ── NBER episode accuracy ─────────────────────────────────────────────────────

def check_nber(X: pd.DataFrame, model) -> dict:
    # Impute NaN with column median so sparse features (e.g. cot_crude) don't block predictions
    X_imputed = X.fillna(X.median())
    results = []
    for start_dt, end_dt, expected in NBER_EPISODES:
        window = X_imputed[(X_imputed.index >= start_dt) & (X_imputed.index <= end_dt)]
        if window.empty:
            results.append({
                "episode": f"{start_dt[:7]}→{end_dt[:7]}", "expected": expected,
                "pct_correct": 0.0, "pass": False, "note": "no data (before feature start)",
            })
            continue
        preds = [REGIME_DECODE[int(p)] for p in model.predict(window)]
        pct   = preds.count(expected) / len(preds)
        results.append({
            "episode": f"{start_dt[:7]}→{end_dt[:7]}", "expected": expected,
            "pct_correct": pct, "pass": pct >= 0.60,
        })
    passed = sum(r["pass"] for r in results)
    return {"episodes": results, "passed": passed, "total": len(results)}


# ── Confidence helper (used by Phase 2 shadow mode) ──────────────────────────

def ml_confidence(proba_row: list[float]) -> float:
    """(top1 - top2) × 100 — measures how decisively the model chose its regime."""
    sorted_probs = sorted(proba_row, reverse=True)
    return (sorted_probs[0] - sorted_probs[1]) * 100


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logger.info("=== FlowMacro XGBoost Phase 1 — Offline Experiment ===")

    X = build_feature_matrix()
    y = get_labels()

    logger.info("\n--- Walk-Forward Validation (expanding window) ---")
    wf = walk_forward_validate(X, y)
    logger.info(f"\nOverall walk-forward accuracy: {wf['overall_accuracy']:.1%}")
    logger.info(f"\nPer-class breakdown:\n{wf['report']}")

    logger.info("--- Training Final Model (full dataset) ---")
    model, features = train_final(X, y)

    logger.info("--- NBER Episode Check ---")
    nber = check_nber(X, model)
    for ep in nber["episodes"]:
        status = "PASS" if ep["pass"] else "FAIL"
        note   = ep.get("note") or f"{ep['pct_correct']:.0%} correct"
        logger.info(f"  [{status}] {ep['episode']}  expected={ep['expected']}  {note}")
    logger.info(f"  Result: {nber['passed']}/{nber['total']} passed")

    logger.info("--- Feature Importance (top 10) ---")
    imp = pd.Series(model.feature_importances_, index=features).sort_values(ascending=False)
    for name, score in imp.head(10).items():
        logger.info(f"  {name:<25} {score:.4f}")

    out_path = Path(__file__).parent / "xgb_regime_phase1.pkl"
    with open(out_path, "wb") as f:
        pickle.dump({
            "model":    model,
            "features": features,
            "encode":   REGIME_ENCODE,
            "decode":   REGIME_DECODE,
        }, f)
    logger.info(f"\nModel saved → {out_path}")

    try:
        from flowmacro.regime.ml_predictor import upload_model
        upload_model(str(out_path))
    except Exception as exc:
        logger.warning(f"Supabase Storage upload failed — run upload_model() manually: {exc}")

    acc_ok  = wf["overall_accuracy"] > 0.70
    nber_ok = nber["passed"] >= 5
    logger.info("\n" + "=" * 55)
    logger.info("PHASE 1 SUMMARY")
    logger.info("=" * 55)
    logger.info(f"Walk-forward accuracy : {wf['overall_accuracy']:.1%}  {'OK' if acc_ok  else 'FAIL'}  (target >70%)")
    logger.info(f"NBER episodes passed  : {nber['passed']}/{nber['total']}  {'OK' if nber_ok else 'FAIL'}  (target >=5/6)")
    if acc_ok and nber_ok:
        logger.info("=> READY for Phase 2 (shadow mode integration)")
    else:
        logger.info("=> NOT ready — review features or tune hyperparameters")
