"""
ML regime predictor — XGBoost shadow mode.

Loads the trained model from Supabase Storage and makes predictions
alongside the rule-based system. Not used for live portfolio decisions
until it graduates from shadow mode (agreement >= 70%, NBER >= 5/6,
Sharpe ML > rule-based over 6 months of live data).

Confidence = (top1_prob - top2_prob) × 100 per grill-session design.
"""
import pickle
import pandas as pd
from loguru import logger

_BUCKET        = "flowmacro-models"
_MODEL_KEY     = "xgb_regime_latest.pkl"
_MODEL_KEY_V2  = "xgb_regime_v2.pkl"
_MODEL_CACHE:    dict = {}
_MODEL_CACHE_V2: dict = {}


def _client():
    from flowmacro.config import settings
    from supabase import create_client
    return create_client(settings.supabase_url, settings.supabase_key)


def upload_model(local_path: str) -> None:
    """Upload trained model pkl to Supabase Storage (upsert)."""
    client = _client()
    with open(local_path, "rb") as f:
        data = f.read()
    client.storage.from_(_BUCKET).upload(
        path=_MODEL_KEY,
        file=data,
        file_options={"content-type": "application/octet-stream", "upsert": "true"},
    )
    logger.info(f"Model uploaded → Supabase Storage {_BUCKET}/{_MODEL_KEY}")


def load_model(force_reload: bool = False) -> dict:
    """Download model from Supabase Storage. Cached in-process per deployment."""
    global _MODEL_CACHE
    if _MODEL_CACHE and not force_reload:
        return _MODEL_CACHE
    client = _client()
    data = client.storage.from_(_BUCKET).download(_MODEL_KEY)
    _MODEL_CACHE = pickle.loads(data)
    logger.debug("ML model loaded from Supabase Storage")
    return _MODEL_CACHE


def upload_model_v2(local_path: str) -> None:
    """Upload v2 model to Supabase Storage as xgb_regime_v2.pkl (NOT overwriting latest)."""
    client = _client()
    with open(local_path, "rb") as f:
        data = f.read()
    client.storage.from_(_BUCKET).upload(
        path=_MODEL_KEY_V2,
        file=data,
        file_options={"content-type": "application/octet-stream", "upsert": "true"},
    )
    logger.info(f"v2 model uploaded → Supabase Storage {_BUCKET}/{_MODEL_KEY_V2}")


def load_model_v2(force_reload: bool = False) -> dict:
    """Download v2 model from Supabase Storage. Cached in-process."""
    global _MODEL_CACHE_V2
    if _MODEL_CACHE_V2 and not force_reload:
        return _MODEL_CACHE_V2
    client = _client()
    data = client.storage.from_(_BUCKET).download(_MODEL_KEY_V2)
    _MODEL_CACHE_V2 = pickle.loads(data)
    logger.debug("ML v2 model loaded from Supabase Storage")
    return _MODEL_CACHE_V2


def predict_ml_v2(feature_scores: dict[str, float]) -> tuple[str, float]:
    """
    Predict regime using the v2 model (pruned old + 14 new features).

    feature_scores: dict containing BOTH old indicator scores AND new features_v2 values.
    Returns: (regime_name, confidence) where confidence = (top1 - top2) × 100.
    """
    artifact  = load_model_v2()
    model     = artifact["model"]
    features  = artifact["features"]
    decode    = artifact["decode"]

    row = {f: feature_scores.get(f, float("nan")) for f in features}
    X   = pd.DataFrame([row])

    proba      = model.predict_proba(X)[0]
    top_idx    = int(proba.argmax())
    regime     = decode[top_idx]
    sorted_p   = sorted(proba, reverse=True)
    confidence = (sorted_p[0] - sorted_p[1]) * 100

    return regime, round(confidence, 2)


def predict_ml(feature_scores: dict[str, float]) -> tuple[str, float]:
    """
    Predict regime from normalized indicator scores + pre-computed axis scores.

    feature_scores: dict keyed by indicator name (e.g. 'yield_curve') plus
                    'growth_score' and 'inflation_score' from the axis scorer.
    Returns: (regime_name, confidence) where confidence = (top1 - top2) × 100.
    """
    artifact  = load_model()
    model     = artifact["model"]
    features  = artifact["features"]
    decode    = artifact["decode"]

    row = {f: feature_scores.get(f, float("nan")) for f in features}
    X   = pd.DataFrame([row])

    proba      = model.predict_proba(X)[0]
    top_idx    = int(proba.argmax())
    regime     = decode[top_idx]
    sorted_p   = sorted(proba, reverse=True)
    confidence = (sorted_p[0] - sorted_p[1]) * 100

    return regime, round(confidence, 2)
