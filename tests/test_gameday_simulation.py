"""Phase 3 release gate: a simulated game-day with injected failures.

SYSTEM_DESIGN_V3 SS12 Phase 3 exit criterion: stale odds, missing lineups,
missing pitchers, and ingest exceptions must produce DEGRADED/BLOCKED states
and hidden fields - never a fabricated number. Fully offline.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from nrfi.build_features import FeatureBuilder
from nrfi.guards import data_health, display_fields
from nrfi.predict_daily import NFRIDailyPredictor

NOW = datetime(2026, 7, 12, 14, 0, tzinfo=timezone.utc)


# ------------------------------------------------------------ scaffolding


class StubTrainer:
    """Model math is covered by test_ensemble; here we test the guards."""

    feature_names = ["x"]
    venue_yrfi_rates = {"7": 0.52}

    def predict_proba(self, X):
        return np.array([0.61])


class RichBuilder(FeatureBuilder):
    """Builder over synthetic-but-complete frames (high coverage)."""

    def __init__(self):
        n = 30
        dates = pd.date_range(end="2026-07-11", periods=n).strftime("%Y-%m-%d")
        pg = pd.DataFrame(
            {
                "pitcher_id": [1] * n + [2] * n,
                "game_date": list(dates) * 2,
                "earned_runs": 2,
                "runs_allowed": 2,
                "hits": 5,
                "walks": 2,
                "strikeouts": 6,
                "innings_pitched": 6.0,
                "opponent_team": "X",
            }
        )
        pfi = pd.DataFrame(
            {
                "pitcher_id": [1] * n + [2] * n,
                "game_date": list(dates) * 2,
                "first_inning_runs": [0, 1] * n,
                "first_inning_hits": 1,
                "first_inning_walks": 0,
            }
        )
        sc = pd.DataFrame(
            {
                "pitcher_id": [1] * n + [2] * n,
                "game_date": list(dates) * 2,
                "exit_velocity_sum": 880.0,
                "barrels": 1,
                "hard_hits": 4,
                "whiffs": 10,
                "swings": 40,
                "batted_balls": 10,
            }
        )
        tg = pd.DataFrame(
            {
                "team": ["NYY"] * n + ["BOS"] * n,
                "game_date": list(dates) * 2,
                "runs": 4,
                "hits": 9,
                "at_bats": 34,
                "total_bases": 15,
                "times_on_base": 12,
                "plate_appearances": 39,
                "woba_num": 11.0,
                "woba_den": 39.0,
            }
        )
        tfi = pd.DataFrame(
            {
                "team": ["NYY"] * n + ["BOS"] * n,
                "game_date": list(dates) * 2,
                "first_inning_runs": [0, 0, 1] * (2 * n // 3),
            }
        )
        bat = pd.DataFrame(
            {
                "batter_id": sum([[i] * n for i in (11, 12, 13, 21, 22, 23)], []),
                "game_date": list(dates) * 6,
                "woba_num": 1.4,
                "woba_den": 4.2,
                "times_on_base": 2,
                "plate_appearances": 4,
            }
        )
        parks = pd.DataFrame(
            {
                "venue_id": [7],
                "runs_factor": [1.02],
                "hr_factor": [1.0],
                "hits_factor": [1.0],
            }
        )
        super().__init__(
            sf=None,
            raw_frames={
                "pitcher_games": pg,
                "pitcher_fi": pfi,
                "statcast_pitcher": sc,
                "team_games": tg,
                "team_fi": tfi,
                "batters": bat,
                "parks": parks,
            },
        )
        self.prepare(max_date="2026-07-12")


class ExplodingBuilder:
    def build_game(self, game):
        raise ConnectionError("snowflake blew up mid-ingest")


def _predictor(builder) -> NFRIDailyPredictor:
    p = object.__new__(NFRIDailyPredictor)
    p.trainer = StubTrainer()
    p.builder = builder
    p.model_version = "test"
    return p


def _game(**kw):
    g = {
        "game_id": "g1",
        "game_date": "2026-07-12",
        "home_team": "BOS",
        "away_team": "NYY",
        "home_pitcher_id": 2,
        "away_pitcher_id": 1,
        "home_pitcher_name": "H",
        "away_pitcher_name": "A",
        "venue_id": 7,
        "is_dome": True,
        "weather": None,
        "cf_azimuth_deg": None,
        "lineups": {"away": [11, 12, 13], "home": [21, 22, 23]},
        "lineup_confirmed": False,
    }
    g.update(kw)
    return g


def _odds(age_sec=120, books=3, p_novig=(0.47, 0.48, 0.49)):
    captured = (NOW - timedelta(seconds=age_sec)).isoformat()
    return {
        ("BOS", "NYY"): {
            "books": {
                f"book{i}": {
                    "yrfi_prob_novig": p_novig[i % len(p_novig)],
                    "nrfi_american": -120 - i,
                    "captured_at": captured,
                }
                for i in range(books)
            },
            "newest_captured_at": captured,
        }
    }


# ------------------------------------------------------------ scenarios


def test_happy_path_ok_with_diagnostic_edge():
    row = _predictor(RichBuilder()).score_game(_game(), _odds(), NOW)
    assert row["status"] == "OK"
    assert row["p_yrfi"] is not None
    assert row["p_yrfi_market"] == pytest.approx(0.48)  # median of 3 books
    assert row["edge"] == pytest.approx(row["p_yrfi"] - 0.48)
    assert row["tier"] == "MEDIUM"  # lineup not confirmed -> capped
    assert "recommend" not in str(row)  # paper-mode language ban


def test_missing_pitcher_blocks_without_probability():
    row = _predictor(RichBuilder()).score_game(
        _game(home_pitcher_id=None), _odds(), NOW
    )
    assert row["status"] == "BLOCKED"
    assert row["block_reason"] == "no_probable_pitcher"
    assert row["p_yrfi"] is None and row["edge"] is None


def test_ingest_exception_blocks_that_game_only():
    row = _predictor(ExplodingBuilder()).score_game(_game(), _odds(), NOW)
    assert row["status"] == "BLOCKED"
    assert row["block_reason"].startswith("feature_error:ConnectionError")
    assert row["p_yrfi"] is None


def test_low_coverage_blocks():
    empty = FeatureBuilder(
        sf=None,
        raw_frames={
            k: pd.DataFrame()
            for k in (
                "pitcher_games",
                "pitcher_fi",
                "statcast_pitcher",
                "team_games",
                "team_fi",
                "batters",
                "parks",
            )
        },
    )
    empty.prepare(max_date="2026-07-12")
    row = _predictor(empty).score_game(_game(is_dome=False, lineups=None), _odds(), NOW)
    assert row["status"] == "BLOCKED"
    assert row["block_reason"].startswith("coverage_")


def test_stale_odds_hide_edge_but_keep_model_prob():
    row = _predictor(RichBuilder()).score_game(_game(), _odds(age_sec=900), NOW)
    assert row["status"] == "DEGRADED"
    assert row["block_reason"] == "odds_stale_900s"
    assert row["p_yrfi"] is not None  # model prob still displays
    assert row["p_yrfi_market"] is None and row["edge"] is None  # edge hidden


def test_missing_market_degrades():
    row = _predictor(RichBuilder()).score_game(_game(), {}, NOW)
    assert row["status"] == "DEGRADED"
    assert row["block_reason"] == "no_market_consensus"
    assert row["edge"] is None


def test_one_book_is_not_a_consensus():
    row = _predictor(RichBuilder()).score_game(_game(), _odds(books=1), NOW)
    assert row["status"] == "DEGRADED"
    assert row["block_reason"] == "no_market_consensus"


def test_daily_probability_is_exact_canonical_model_output():
    row = _predictor(RichBuilder()).score_game(_game(), _odds(), NOW)
    assert row["p_yrfi"] == pytest.approx(0.61)


# ------------------------------------------------------------ dashboard


def test_data_health_dot():
    fresh = NOW.isoformat()
    ok = {"status": "OK", "predicted_at": fresh}
    assert data_health([ok, ok], NOW) == "green"
    assert (
        data_health([ok, {"status": "DEGRADED", "predicted_at": fresh}], NOW) == "amber"
    )
    assert data_health([], NOW) == "red"
    stale = (NOW - timedelta(hours=7)).isoformat()
    assert data_health([{"status": "OK", "predicted_at": stale}], NOW) == "red"


def test_display_contract_zero_edge_and_nulls():
    assert (
        display_fields({"p_yrfi": 0.4, "p_yrfi_market": 0.4, "edge": 0.0})["edge_pct"]
        == 0.0
    )  # 0.0 is a value
    blocked = display_fields({"p_yrfi": None, "p_yrfi_market": None, "edge": None})
    assert blocked == {
        "nrfi_pct": None,
        "market_nrfi_pct": None,
        "edge_pct": None,
    }  # renders BLOCKED/UNAVAILABLE
    d = display_fields({"p_yrfi": 0.388, "p_yrfi_market": 0.416, "edge": 0.388 - 0.416})
    assert d["nrfi_pct"] == 61.2 and d["market_nrfi_pct"] == 58.4
    assert d["edge_pct"] == pytest.approx(2.8)  # NRFI orientation
