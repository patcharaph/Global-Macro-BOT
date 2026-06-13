"""
Steps 5–8 (prep): XGBoost v2 training pipeline — 31-feature model.

SAFE TO RUN: saves to xgb_regime_v2.pkl only — does NOT touch xgb_regime_latest.pkl.
Current v1 shadow model is unaffected until explicit promotion (promote_model_v2.py).

Step 5: SHAP prune — drop old features with shap_mean < PRUNE_THRESHOLD (default 0.01)
Step 6: Retrain XGBoost with (pruned old) + (14 new Group 2+3 features)
Step 7: Walk-forward validation — must beat v1 accuracy (66.3%)
Step 8: Upload xgb_regime_v2.pkl to Supabase Storage (not promoting to latest)

Prerequisites:
    1. Run scripts/backfill_features_v2.py first (macro_features_v2 must be populated)
    2. pip install shap   (optional — skips pruning if missing, uses all 17 old features)

Usage:
    python scripts/train_regime_xgb_v2.py
    python scripts/train_regime_xgb_v2.py --no-shap
    python scripts/train_regime_xgb_v2.py --prune-threshold 0.005

Promote only after graduation criteria met (Dec 2026):
    python scripts/promote_model_v2.py
"""
import sys
import argparse
import pickle
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

import numpy as np
import pandas as pd
from loguru import logger

from flowmacro.data.store import read_features_v2

# Reuse labels, validation helpers, and constants from the v1 training script
from train_regime_xgb import (
    get_labels,
    walk_forward_validate,
    check_nber,
    train_final,
    REGIME_ENCODE,
    REGIME_DECODE,
    _XGB_PARAMS,
    _START_LABELS,
)

_PRUNE_THRESHOLD   = 0.01
_V2_FILENAME       = "xgb_regime_v2.pkl"


# ── Step 5: SHAP pruning ──────────────────────────────────────────────────────

def shap_prune(X_old: pd.DataFrame, threshold: float) -> list[str]:
    """Return list of old feature names to drop (SHAP mean < threshold).
    Falls back to empty list if shap is not installed or current model unavailable.
    """
    try:
        import shap
    except ImportError:
        logger.warning("shap not installed — skipping pruning (all 17 old features kept)")
        logger.warning("  Install with: pip install shap")
        return []

    try:
        from flowmacro.regime.ml_predictor import load_model
        artifact = load_model()
        model    = artifact["model"]
        feat_v1  = artifact["features"]

        avail = [f for f in feat_v1 if f in X_old.columns]
        X_imp = X_old[avail].fillna(X_old[avail].median())

        logger.info(f"SHAP analysis on {len(avail)} features × {len(X_imp)} samples...")
        explainer   = shap.TreeExplainer(model)
        shap_values = explainer.shap_values(X_imp)

        # shap < 0.45:  list of (n_samples, n_features) per class
        # shap >= 0.45: single 3D array (n_samples, n_features, n_classes)
        if isinstance(shap_values, list):
            mean_abs = np.mean([np.abs(sv).mean(axis=0) for sv in shap_values], axis=0)
        elif shap_values.ndim == 3:
            mean_abs = np.abs(shap_values).mean(axis=(0, 2))
        else:
            mean_abs = np.abs(shap_values).mean(axis=0)

        imp    = pd.Series(mean_abs, index=avail).sort_values(ascending=False)
        pruned = imp[imp < threshold].index.tolist()

        logger.info(f"SHAP importance (all features):\n{imp.to_string()}")
        logger.info(f"Pruning {len(pruned)} features (< {threshold}): {pruned}")
        return pruned

    except Exception as exc:
        logger.warning(f"SHAP analysis failed: {exc} — all old features kept")
        return []


# ── Feature matrix ────────────────────────────────────────────────────────────

def build_combined_features(
    prune_threshold: float,
    use_shap: bool,
) -> tuple[pd.DataFrame, list[str]]:
    """
    Returns:
      X:       Combined feature DataFrame (pruned old + 14 new)
      pruned:  Old feature names that were removed
    """
    logger.info("Loading old feature matrix (v1 17 features)...")
    from train_regime_xgb import build_feature_matrix
    old_X = build_feature_matrix()

    pruned = shap_prune(old_X, prune_threshold) if use_shap else []
    kept_X = old_X.drop(columns=pruned, errors="ignore")
    logger.info(f"Old features kept: {kept_X.shape[1]}  pruned: {len(pruned)}")

    logger.info("Loading features_v2 from Supabase (macro_features_v2)...")
    new_df = read_features_v2(start=_START_LABELS)
    if new_df.empty:
        raise ValueError(
            "macro_features_v2 is empty — run scripts/backfill_features_v2.py first"
        )
    logger.info(f"features_v2: {new_df.shape[1]} features × {new_df.shape[0]} weeks")

    # Inner join: only weeks where both old AND new features exist
    combined = kept_X.join(new_df, how="inner")
    nan_pct  = combined.isnull().mean().mean() * 100
    logger.info(
        f"Combined: {combined.shape[1]} features × {combined.shape[0]} weeks  "
        f"NaN={nan_pct:.1f}%"
    )

    overlap = set(kept_X.columns) & set(new_df.columns)
    if overlap:
        logger.warning(f"Feature name overlap (unexpected): {overlap}")

    return combined, pruned


# ── Acceptance criteria ───────────────────────────────────────────────────────

def print_summary(
    wf: dict,
    nber: dict,
    pruned: list[str],
    n_features: int,
    n_samples: int,
) -> bool:
    """Print v2 summary and return True if all criteria met."""
    acc_ok   = wf["overall_accuracy"] > 0.663
    nber_ok  = nber["passed"] >= 5
    ratio    = n_samples / n_features
    ratio_ok = ratio >= 20

    print("\n" + "=" * 65)
    print("XGBoost v2 SUMMARY  (v1 baseline: 66.3% acc, NBER 5/6)")
    print("=" * 65)
    print(f"Walk-forward accuracy : {wf['overall_accuracy']:.1%}  "
          f"{'✅' if acc_ok  else '❌'}  (must beat 66.3%)")
    print(f"NBER episodes passed  : {nber['passed']}/{nber['total']}  "
          f"{'✅' if nber_ok else '❌'}  (need ≥5/6)")
    print(f"Sample/feature ratio  : {ratio:.1f}:1   "
          f"{'✅' if ratio_ok else '❌'}  (need ≥20:1)")
    print(f"Features              : {n_features}  (pruned old: {pruned})")

    per_class_lines = [
        l for l in wf["report"].splitlines() if l.strip()
    ]
    print("\nPer-class accuracy:\n" + "\n".join(per_class_lines))
    print()

    return acc_ok and nber_ok and ratio_ok


# ── Main ──────────────────────────────────────────────────────────────────────

def main(prune_threshold: float = _PRUNE_THRESHOLD, use_shap: bool = True) -> None:
    logger.info("=== FlowMacro XGBoost v2 — Training Pipeline ===")
    logger.info(
        f"SHAP pruning: {'enabled' if use_shap else 'disabled'}  "
        f"threshold={prune_threshold}"
    )

    # Steps 5+6: combined features + pruning
    X, pruned = build_combined_features(prune_threshold, use_shap)
    y         = get_labels()

    ratio = len(y) / X.shape[1]
    logger.info(f"Feature count: {X.shape[1]}  Sample/feature: {ratio:.1f}:1")
    if ratio < 20:
        logger.warning(f"Ratio {ratio:.1f}:1 < 20:1 — consider higher prune threshold")

    # Step 7: Walk-forward validation
    logger.info("\n--- Walk-Forward Validation ---")
    wf = walk_forward_validate(X, y)
    logger.info(f"Overall walk-forward accuracy: {wf['overall_accuracy']:.1%}")

    # Step 6: Train final model (full dataset)
    logger.info("--- Training Final Model ---")
    model_v2, feat_names = train_final(X, y)

    # NBER check
    logger.info("--- NBER Episode Check ---")
    nber = check_nber(X, model_v2)
    for ep in nber["episodes"]:
        status = "PASS" if ep["pass"] else "FAIL"
        note   = ep.get("note") or f"{ep['pct_correct']:.0%} correct"
        logger.info(f"  [{status}] {ep['episode']}  expected={ep['expected']}  {note}")
    logger.info(f"  Result: {nber['passed']}/{nber['total']} passed")

    # Feature importance
    imp = pd.Series(model_v2.feature_importances_, index=feat_names).sort_values(ascending=False)
    logger.info("--- Feature Importance (top 15) ---")
    for name, score in imp.head(15).items():
        logger.info(f"  {name:<35} {score:.4f}")

    # Summary + acceptance check
    all_ok = print_summary(wf, nber, pruned, len(feat_names), len(y))

    # Step 8a: Save locally
    out_path = Path(__file__).parent / _V2_FILENAME
    bundle = {
        "model":        model_v2,
        "features":     feat_names,
        "encode":       REGIME_ENCODE,
        "decode":       REGIME_DECODE,
        "pruned":       pruned,
        "wf_accuracy":  wf["overall_accuracy"],
        "nber_passed":  nber["passed"],
    }
    with open(out_path, "wb") as f:
        pickle.dump(bundle, f)
    logger.info(f"Model saved locally → {out_path}")

    # Step 8b: Upload to Supabase as xgb_regime_v2.pkl (NOT promoting to latest)
    try:
        from flowmacro.regime.ml_predictor import upload_model_v2
        upload_model_v2(str(out_path))
    except Exception as exc:
        logger.warning(f"Supabase upload failed: {exc} — model saved locally only")

    print()
    if all_ok:
        print("✅ All criteria met — READY for graduation promotion")
        print("   When Dec 2026 graduation criteria are satisfied, run:")
        print("   python scripts/promote_model_v2.py")
    else:
        print("⚠️  Some criteria not met — review results and retrain before promoting")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train XGBoost v2 regime model")
    parser.add_argument(
        "--no-shap", action="store_true",
        help="Skip SHAP pruning (use all 17 old features)",
    )
    parser.add_argument(
        "--prune-threshold", type=float, default=_PRUNE_THRESHOLD,
        help=f"SHAP mean threshold for pruning old features (default {_PRUNE_THRESHOLD})",
    )
    args = parser.parse_args()
    main(prune_threshold=args.prune_threshold, use_shap=not args.no_shap)
