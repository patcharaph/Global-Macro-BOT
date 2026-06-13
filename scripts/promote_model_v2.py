"""
Step 8 (final): Promote xgb_regime_v2.pkl → xgb_regime_latest.pkl.

ONLY run this after ALL graduation criteria are met (Dec 2026):
  ✅ Walk-forward accuracy > 66.3%
  ✅ NBER validation ≥ 5/6
  ✅ Agreement rate ≥ 70% over 26 live weeks
  ✅ Sharpe ML-blend > Rule-based over 6 months

Effect: next weekly run uses the v2 model for ML shadow predictions.
        Portfolio is unaffected — shadow mode continues until manual graduation.

Usage:
    python scripts/promote_model_v2.py           # interactive confirmation
    python scripts/promote_model_v2.py --confirm  # skip prompt (for CI)
"""
import sys
import pickle
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger


def main(confirmed: bool = False) -> None:
    from flowmacro.regime.ml_predictor import _client, _BUCKET, _MODEL_KEY, _MODEL_KEY_V2

    # Download v2 for pre-promotion summary
    logger.info(f"Downloading {_MODEL_KEY_V2} for pre-promotion check...")
    client  = _client()
    v2_data = client.storage.from_(_BUCKET).download(_MODEL_KEY_V2)
    bundle  = pickle.loads(v2_data)

    wf_acc    = bundle.get("wf_accuracy", None)
    nber_pass = bundle.get("nber_passed",  None)
    n_feat    = len(bundle.get("features", []))
    pruned    = bundle.get("pruned", [])

    print("\n=== v2 Model Pre-Promotion Summary ===")
    print(f"Walk-forward accuracy : {wf_acc:.1%}" if isinstance(wf_acc, float) else "Walk-forward accuracy : unknown")
    print(f"NBER episodes passed  : {nber_pass}/6" if isinstance(nber_pass, int) else "NBER episodes passed  : unknown")
    print(f"Feature count         : {n_feat}")
    print(f"Pruned old features   : {pruned}")

    acc_ok  = isinstance(wf_acc,    float) and wf_acc    > 0.663
    nber_ok = isinstance(nber_pass, int)   and nber_pass >= 5

    print(f"\n  Accuracy > 66.3%  : {'✅' if acc_ok  else '❌'}")
    print(f"  NBER ≥ 5/6        : {'✅' if nber_ok else '❌'}")
    print(f"  (Agreement ≥ 70% and Sharpe check — verify manually from dashboard)")

    if not (acc_ok and nber_ok):
        print("\n❌ Stored model does not meet accuracy/NBER criteria — aborting")
        print("   Re-run scripts/train_regime_xgb_v2.py and check results")
        sys.exit(1)

    if not confirmed:
        print(f"\nThis will copy {_MODEL_KEY_V2} → {_MODEL_KEY} in Supabase Storage.")
        print("The v1 model will be overwritten. This cannot be undone automatically.")
        answer = input("Proceed? [yes/no]: ").strip().lower()
        if answer != "yes":
            print("Aborted — no changes made")
            sys.exit(0)

    # Re-upload v2 bytes as the new "latest"
    logger.info(f"Promoting {_MODEL_KEY_V2} → {_MODEL_KEY}...")
    client.storage.from_(_BUCKET).upload(
        path=_MODEL_KEY,
        file=v2_data,
        file_options={"content-type": "application/octet-stream", "upsert": "true"},
    )

    # Invalidate in-process caches so next predict_ml uses the promoted model
    import flowmacro.regime.ml_predictor as _pred
    _pred._MODEL_CACHE.clear()
    _pred._MODEL_CACHE_V2.clear()

    logger.info(f"✅ Promoted: {_MODEL_KEY_V2} → {_MODEL_KEY}")
    logger.info("Next weekly run will use the v2 model for all ML predictions")
    logger.info("Monitor accuracy vs rule-based in dashboard for the first few weeks")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Promote v2 model to production")
    parser.add_argument("--confirm", action="store_true", help="Skip interactive prompt")
    args = parser.parse_args()
    main(confirmed=args.confirm)
