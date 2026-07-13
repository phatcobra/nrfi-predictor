-- Phase 1 DDL: versioned feature store (populated set-based in Phase 2)
CREATE SCHEMA IF NOT EXISTS NRFI_DB.FEATURES;

CREATE TABLE IF NOT EXISTS NRFI_DB.FEATURES.GAME_FEATURES (
    game_id          VARCHAR NOT NULL,
    feature_version  VARCHAR NOT NULL,   -- immutable; models pin this
    computed_at      TIMESTAMP_TZ,
    as_of            TIMESTAMP_TZ,       -- info cutoff for every window (leakage guard)
    f                VARCHAR,            -- JSON text, ~60 features; null = missing (never a default)
    missing_ct       SMALLINT,
    coverage         FLOAT,              -- < 0.85 => game is BLOCKED, not scored
    PRIMARY KEY (game_id, feature_version)
);
