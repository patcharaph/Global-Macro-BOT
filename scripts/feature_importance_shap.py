"""
Step 1: SHAP feature importance on current XGBoost model.

Shows which of the 17 existing features are redundant / low-signal,
so we can trim them before adding the 14 new v2 features to keep
the sample-to-feature ratio above 25:1.

Usage:
    python scripts/feature_importance_shap.py

Requirements:
    pip install shap
"""
import sys
import pickle
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd
from loguru import logger


def load_model() -> tuple:
    """Load model bundle from Supabase Storage, fall back to local pkl."""
    try:
        from flowmacro.regime.ml_predictor import _client, _BUCKET, _MODEL_KEY
        logger.info("Loading model from Supabase Storage...")
        client   = _client()
        response = client.storage.from_(_BUCKET).download(_MODEL_KEY)
        bundle   = pickle.loads(response)
        logger.info(f"Supabase model loaded: {len(bundle['features'])} features")
        return bundle["model"], bundle["features"]
    except Exception as exc:
        logger.warning(f"Supabase load failed: {exc}")

    local = Path(__file__).parent / "xgb_regime_phase1.pkl"
    if not local.exists():
        logger.error(f"No local model at {local} — run train_regime_xgb.py first")
        sys.exit(1)
    with open(local, "rb") as f:
        bundle = pickle.load(f)
    logger.info(f"Local model loaded: {len(bundle['features'])} features")
    return bundle["model"], bundle["features"]


def main() -> None:
    try:
        import shap
    except ImportError:
        logger.error("shap not installed — run: pip install shap")
        sys.exit(1)

    model, features = load_model()

    # Rebuild feature matrix using the same pipeline as train_regime_xgb.py
    logger.info("Building feature matrix...")
    from train_regime_xgb import build_feature_matrix, get_labels, REGIME_ENCODE

    X  = build_feature_matrix()
    y  = get_labels()
    y_enc = y.map(REGIME_ENCODE)

    # Keep only features the model knows, align with labels
    avail = [f for f in features if f in X.columns]
    data  = X[avail].join(y_enc.rename("label"), how="inner").dropna(subset=["label"])
    data  = data.fillna(data.median())
    X_tr  = data.drop("label", axis=1)
    logger.info(f"Training data: {X_tr.shape}")

    # SHAP TreeExplainer
    logger.info("Running SHAP TreeExplainer (may take ~30s)...")
    explainer   = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X_tr)

    # For multiclass XGBoost, shap_values is list[n_classes] each (n_samples, n_features)
    if isinstance(shap_values, list):
        mean_abs = np.mean([np.abs(sv).mean(axis=0) for sv in shap_values], axis=0)
    else:
        mean_abs = np.abs(shap_values).mean(axis=0)

    importance = (
        pd.DataFrame({"feature": avail, "shap_mean": mean_abs})
        .sort_values("shap_mean", ascending=False)
        .reset_index(drop=True)
    )

    print("\n=== SHAP Feature Importance — current 17-feature model ===")
    print(importance.to_string(index=False))

    low = importance[importance["shap_mean"] < 0.01]["feature"].tolist()
    keep = len(avail) - len(low)

    print(f"\nLow importance (shap_mean < 0.01): {low}")
    print(f"Candidates to remove before retrain: {len(low)}")
    print(f"\nAfter removal: {keep} old + 14 new = {keep + 14} total features")

    for threshold in [20, 25]:
        ratio = 712 / (keep + 14)
        status = "✅" if ratio >= threshold else "⚠️"
        print(f"  {status} Sample/feature ≥{threshold}: {ratio:.1f}:1")

    # Save importance table for reference
    out = Path(__file__).parent / "feature_importance_shap.csv"
    importance.to_csv(out, index=False)
    logger.info(f"Saved → {out}")


if __name__ == "__main__":
    main()
