-- Normalized source tables consumed by nrfi.build_features.FeatureBuilder.
-- Values must be observed historical data. Missing fields remain NULL.
CREATE DATABASE IF NOT EXISTS NRFI_DB;
CREATE SCHEMA IF NOT EXISTS NRFI_DB.RAW;

CREATE TABLE IF NOT EXISTS NRFI_DB.RAW.PITCHER_GAME_LOGS (
    pitcher_id       INTEGER NOT NULL,
    game_id          VARCHAR NOT NULL,
    game_date        DATE NOT NULL,
    opponent_team    VARCHAR,
    earned_runs      FLOAT,
    runs_allowed     FLOAT,
    hits              FLOAT,
    walks             FLOAT,
    strikeouts        FLOAT,
    innings_pitched   FLOAT,
    source            VARCHAR,
    ingested_at       TIMESTAMP_TZ,
    PRIMARY KEY (pitcher_id, game_id)
);

CREATE TABLE IF NOT EXISTS NRFI_DB.RAW.PITCHER_INNING_LOGS (
    pitcher_id              INTEGER NOT NULL,
    game_id                 VARCHAR NOT NULL,
    game_date               DATE NOT NULL,
    inning                  SMALLINT NOT NULL,
    first_inning_runs       FLOAT,
    first_inning_hits       FLOAT,
    first_inning_walks      FLOAT,
    first_inning_strikeouts FLOAT,
    first_inning_pa         FLOAT,
    source                  VARCHAR,
    ingested_at             TIMESTAMP_TZ,
    PRIMARY KEY (pitcher_id, game_id, inning)
);

CREATE TABLE IF NOT EXISTS NRFI_DB.RAW.STATCAST_PITCHER_DAILY (
    pitcher_id        INTEGER NOT NULL,
    game_date         DATE NOT NULL,
    exit_velocity_sum FLOAT,
    barrels           FLOAT,
    hard_hits         FLOAT,
    whiffs            FLOAT,
    swings            FLOAT,
    batted_balls      FLOAT,
    source            VARCHAR,
    ingested_at       TIMESTAMP_TZ,
    PRIMARY KEY (pitcher_id, game_date)
);

CREATE TABLE IF NOT EXISTS NRFI_DB.RAW.TEAM_GAME_LOGS (
    team              VARCHAR NOT NULL,
    game_id           VARCHAR NOT NULL,
    game_date         DATE NOT NULL,
    runs              FLOAT,
    hits              FLOAT,
    at_bats           FLOAT,
    total_bases       FLOAT,
    times_on_base     FLOAT,
    plate_appearances FLOAT,
    woba_num          FLOAT,
    woba_den          FLOAT,
    source            VARCHAR,
    ingested_at       TIMESTAMP_TZ,
    PRIMARY KEY (team, game_id)
);

CREATE TABLE IF NOT EXISTS NRFI_DB.RAW.TEAM_INNING_LOGS (
    team               VARCHAR NOT NULL,
    game_id            VARCHAR NOT NULL,
    game_date          DATE NOT NULL,
    inning             SMALLINT NOT NULL,
    first_inning_runs  FLOAT,
    source             VARCHAR,
    ingested_at        TIMESTAMP_TZ,
    PRIMARY KEY (team, game_id, inning)
);

CREATE TABLE IF NOT EXISTS NRFI_DB.RAW.BATTER_GAME_LOGS (
    batter_id          INTEGER NOT NULL,
    game_id            VARCHAR NOT NULL,
    game_date          DATE NOT NULL,
    woba_num           FLOAT,
    woba_den           FLOAT,
    times_on_base      FLOAT,
    plate_appearances  FLOAT,
    source             VARCHAR,
    ingested_at        TIMESTAMP_TZ,
    PRIMARY KEY (batter_id, game_id)
);

-- One pre-training, externally validated factor row per venue. Do not replace
-- this table with factors computed using the locked holdout or future games.
CREATE TABLE IF NOT EXISTS NRFI_DB.RAW.PARK_FACTORS (
    venue_id           INTEGER NOT NULL,
    runs_factor        FLOAT,
    hr_factor          FLOAT,
    hits_factor        FLOAT,
    calculated_through DATE,
    source             VARCHAR,
    ingested_at        TIMESTAMP_TZ,
    PRIMARY KEY (venue_id)
);
