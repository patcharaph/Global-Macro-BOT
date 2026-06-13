-- macro_features_v2: XGBoost v2 feature store (14 new leading indicators)
-- Run once in Supabase SQL editor before backfill_features_v2.py

CREATE TABLE IF NOT EXISTS macro_features_v2 (
    date DATE PRIMARY KEY,

    -- Group 2: Macro Leading (5 features)
    hy_spread_pr                FLOAT,   -- Moody's Baa spread (BAA10Y) percentile rank 260W
    tips_breakeven_5y_pr        FLOAT,   -- T5YIE percentile rank 260W
    china_pmi_pr                FLOAT,   -- OECD CLI China (BSCICP03CNM665S) percentile rank 260W
    copper_gold_ratio_pr        FLOAT,   -- HG=F/GC=F percentile rank 260W
    policy_forward_signal_pr    FLOAT,   -- (DGS1 - FEDFUNDS) percentile rank 260W

    -- Group 3: Price-Based Leading (9 features)
    spy_return_26w              FLOAT,   -- SPY 26W return percentile rank 260W
    spy_return_52w              FLOAT,   -- SPY 52W return percentile rank 260W
    eem_return_26w              FLOAT,   -- EEM 26W return percentile rank 260W
    tlt_return_13w              FLOAT,   -- TLT 13W return percentile rank 260W
    yield_curve_momentum_4w     FLOAT,   -- (DGS10-DGS2) delta vs 4W ago (raw bps)
    dxy_return_13w              FLOAT,   -- DX-Y.NYB 13W return percentile rank 260W
    dbc_return_13w              FLOAT,   -- DBC 13W return percentile rank 260W
    gld_return_13w              FLOAT,   -- GLD 13W return percentile rank 260W
    hy_spread_momentum_4w       FLOAT,   -- Moody's Baa spread delta vs 4W ago (raw %)

    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for range queries
CREATE INDEX IF NOT EXISTS idx_features_v2_date ON macro_features_v2 (date);
