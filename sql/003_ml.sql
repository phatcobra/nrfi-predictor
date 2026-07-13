-- Phase 1 DDL: model registry, predictions (paper-mode), grades
CREATE SCHEMA IF NOT EXISTS NRFI_DB.ML;

CREATE TABLE IF NOT EXISTS NRFI_DB.ML.MODEL_STATUS (
    model_version    VARCHAR NOT NULL,
    trained_at       TIMESTAMP_TZ,
    feature_version  VARCHAR,
    train_range      VARCHAR,
    cv_logloss       FLOAT,
    cv_brier         FLOAT,
    holdout_logloss  FLOAT,             -- 2025 locked holdout: written ONCE at release
    holdout_brier    FLOAT,
    gates_passed     BOOLEAN,
    gate_report      VARIANT,
    status           VARCHAR,           -- 'candidate' | 'production' | 'retired'
    PRIMARY KEY (model_version)
);

-- Paper-mode: probabilities + diagnostic edge. No recommendation column
-- exists by design (project redline).
CREATE TABLE IF NOT EXISTS NRFI_DB.ML.PREDICTIONS (
    game_id          VARCHAR NOT NULL,
    predicted_at     TIMESTAMP_TZ NOT NULL,
    game_date        DATE,
    home_team        VARCHAR,
    away_team        VARCHAR,
    home_pitcher     VARCHAR,
    away_pitcher     VARCHAR,
    model_version    VARCHAR,
    p_yrfi           FLOAT,             -- calibrated; NULL when BLOCKED
    p_yrfi_market    FLOAT,             -- no-vig median consensus; NULL when stale/missing
    edge             FLOAT,             -- p_yrfi - p_yrfi_market (DIAGNOSTIC display only)
    books_n          SMALLINT,
    odds_age_sec     INTEGER,
    lineup_confirmed BOOLEAN,
    tier             VARCHAR,           -- 'HIGH' | 'MEDIUM' | 'LOW'
    status           VARCHAR,           -- 'OK' | 'DEGRADED' | 'BLOCKED'
    block_reason     VARCHAR,
    PRIMARY KEY (game_id, predicted_at)
);

CREATE TABLE IF NOT EXISTS NRFI_DB.ML.PREDICTION_GRADES (
    game_id                 VARCHAR NOT NULL,
    model_version           VARCHAR,
    p_yrfi                  FLOAT,
    yrfi_actual             BOOLEAN,
    brier                   FLOAT,
    logloss                 FLOAT,
    closing_p_yrfi_market   FLOAT,      -- consensus at last pre-game snapshot
    clv                     FLOAT,      -- closing market prob vs prob at prediction time
    graded_at               TIMESTAMP_TZ,
    PRIMARY KEY (game_id)
);
