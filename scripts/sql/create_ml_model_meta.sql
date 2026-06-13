-- ml_model_meta: lightweight metadata for ML model versions
-- Dashboard reads this instead of downloading the full pkl

CREATE TABLE IF NOT EXISTS ml_model_meta (
    id           BIGSERIAL PRIMARY KEY,
    model_key    TEXT        NOT NULL,   -- e.g. 'xgb_regime_v2'
    trained_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    wf_accuracy  FLOAT,
    nber_passed  INT,
    n_features   INT,
    pruned_features TEXT[],             -- array of pruned old feature names
    notes        TEXT
);

CREATE INDEX IF NOT EXISTS idx_ml_model_meta_key_time
    ON ml_model_meta (model_key, trained_at DESC);
