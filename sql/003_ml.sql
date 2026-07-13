-- Model registry, paper-mode predictions, and immutable grades.
CREATE SCHEMA IF NOT EXISTS NRFI_DB.ML;

CREATE TABLE IF NOT EXISTS NRFI_DB.ML.MODEL_STATUS (
    model_version              VARCHAR NOT NULL,
    trained_at                 TIMESTAMP_TZ,
    feature_version            VARCHAR,
    train_range                VARCHAR,
    cv_logloss                 FLOAT,
    cv_brier                   FLOAT,
    holdout_logloss            FLOAT,
    holdout_brier              FLOAT,
    holdout_baseline_logloss   FLOAT,
    holdout_baseline_brier     FLOAT,
    holdout_n                  INTEGER,
    holdout_passed             BOOLEAN,
    holdout_evaluated_at       TIMESTAMP_TZ,
    holdout_burned_rerun       BOOLEAN,
    gates_passed               BOOLEAN,
    gate_report                VARIANT,
    status                     VARCHAR, -- rejected | candidate | production | retired
    PRIMARY KEY (model_version)
);

-- Idempotent migration for warehouses initialized from an earlier schema.
ALTER TABLE NRFI_DB.ML.MODEL_STATUS ADD COLUMN IF NOT EXISTS holdout_baseline_logloss FLOAT;
ALTER TABLE NRFI_DB.ML.MODEL_STATUS ADD COLUMN IF NOT EXISTS holdout_baseline_brier FLOAT;
ALTER TABLE NRFI_DB.ML.MODEL_STATUS ADD COLUMN IF NOT EXISTS holdout_n INTEGER;
ALTER TABLE NRFI_DB.ML.MODEL_STATUS ADD COLUMN IF NOT EXISTS holdout_passed BOOLEAN;
ALTER TABLE NRFI_DB.ML.MODEL_STATUS ADD COLUMN IF NOT EXISTS holdout_evaluated_at TIMESTAMP_TZ;
ALTER TABLE NRFI_DB.ML.MODEL_STATUS ADD COLUMN IF NOT EXISTS holdout_burned_rerun BOOLEAN;

-- Paper-mode: probabilities + diagnostic edge. No action/staking column exists.
CREATE TABLE IF NOT EXISTS NRFI_DB.ML.PREDICTIONS (
    game_id          VARCHAR NOT NULL,
    predicted_at     TIMESTAMP_TZ NOT NULL,
    game_date        DATE,
    home_team        VARCHAR,
    away_team        VARCHAR,
    home_pitcher     VARCHAR,
    away_pitcher     VARCHAR,
    model_version    VARCHAR,
    p_yrfi           FLOAT,
    p_yrfi_market    FLOAT,
    edge             FLOAT,
    books_n          SMALLINT,
    odds_age_sec     INTEGER,
    lineup_confirmed BOOLEAN,
    tier             VARCHAR,
    status           VARCHAR,
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
    closing_p_yrfi_market   FLOAT,
    clv                     FLOAT,
    graded_at               TIMESTAMP_TZ,
    PRIMARY KEY (game_id)
);
