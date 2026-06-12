-- Migration: create paper_portfolio_ml table for Portfolio B (ML-blend A/B test)
-- Run once in Supabase SQL Editor: https://app.supabase.com → SQL Editor
--
-- Portfolio B tracks a virtual ML-assisted portfolio alongside the live rule-based
-- Portfolio A, enabling a 26-week A/B comparison without risking live capital.

CREATE TABLE IF NOT EXISTS paper_portfolio_ml (
    date            DATE PRIMARY KEY,
    ml_blend_probs  JSONB,                      -- blended probabilities (30% ML + 70% rule)
    ml_raw_probs    JSONB,                      -- ML-only probability vector (audit trail)
    rule_probs      JSONB,                      -- rule-based softmax probs (reference copy)
    blend_weights   JSONB,                      -- resulting asset weights after momentum + vol filter
    portfolio_value FLOAT,                      -- virtual portfolio value in USD (starts $3,000)
    period_return   FLOAT,                      -- week-over-week return (decimal, e.g. 0.012 = +1.2%)
    ml_regime       TEXT,                       -- XGBoost predicted regime
    ml_confidence   FLOAT,                      -- XGBoost confidence 0–100
    ml_weight_used  FLOAT NOT NULL DEFAULT 0.30 -- ML blend weight used this week
);

-- Index for time-range queries (dashboard equity curve)
CREATE INDEX IF NOT EXISTS idx_paper_portfolio_ml_date
    ON paper_portfolio_ml (date DESC);
