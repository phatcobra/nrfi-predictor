-- Phase 1 DDL: core schema (labels + market snapshots)
CREATE DATABASE IF NOT EXISTS NRFI_DB;
CREATE SCHEMA IF NOT EXISTS NRFI_DB.CORE;
CREATE SCHEMA IF NOT EXISTS NRFI_DB.RAW;

CREATE TABLE IF NOT EXISTS NRFI_DB.CORE.FIRST_INNING_OUTCOMES (
    game_id          VARCHAR NOT NULL,
    game_date        DATE,
    season           SMALLINT,
    home_team        VARCHAR,
    away_team        VARCHAR,
    home_sp_id       INTEGER,
    away_sp_id       INTEGER,
    venue_id         INTEGER,
    fi_runs_top      SMALLINT,        -- NULL until final
    fi_runs_bottom   SMALLINT,
    yrfi             BOOLEAN,         -- (top+bottom) > 0
    is_doubleheader  BOOLEAN,
    game_number      SMALLINT,
    source           VARCHAR,         -- 'statsapi' | 'retrosheet' | 'sportsdataio'
    ingested_at      TIMESTAMP_TZ,
    PRIMARY KEY (game_id)
);

CREATE TABLE IF NOT EXISTS NRFI_DB.CORE.ODDS_SNAPSHOTS (
    snapshot_id      VARCHAR NOT NULL, -- sha1(fixture|book|captured_at): dedupe key
    fixture_id       VARCHAR,
    game_id          VARCHAR,          -- mapped when fixture->gamePk mapping lands
    game_date        DATE,
    start_time       TIMESTAMP_TZ,
    home_team        VARCHAR,
    away_team        VARCHAR,
    sportsbook       VARCHAR,
    market_id        VARCHAR,          -- exact OpticOdds market id, pinned in config
    line             NUMBER(3,1),      -- must be 0.5
    yrfi_american    FLOAT,
    nrfi_american    FLOAT,
    yrfi_prob_raw    FLOAT,
    nrfi_prob_raw    FLOAT,
    yrfi_prob_novig  FLOAT,            -- raw/(raw_sum): vig removed at ingest
    nrfi_prob_novig  FLOAT,
    captured_at      TIMESTAMP_TZ,     -- from API payload
    PRIMARY KEY (snapshot_id)
);
