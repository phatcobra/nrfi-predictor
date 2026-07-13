"""Daily NRFI/YRFI scoring in paper mode with fail-closed behavior.

Only the registry-approved production artifact may score games. Missing or
stale market data hides market fields without inventing values; missing model
inputs block the game entirely.
"""
from __future__ import annotations

import json
import logging
import os
import statistics
from datetime import datetime, timezone
from typing import Dict, List, Optional

import numpy as np

from nrfi._obs import sentry_sdk
from nrfi.build_features import FeatureBuilder, coverage
from nrfi.config import Config, MIN_BOOKS_FOR_MARKET, TZ_ET
from nrfi.ensemble import n_eff_for_game, shrink_to_venue
from nrfi.guards import coverage_blocks, market_usable, tier_for
from nrfi.ingest_opticodds import OpticOddsIngester
from nrfi.model_registry import production_model_version
from nrfi.snowflake_loader import SnowflakeLoader
from nrfi.train import NFRIModelTrainer

logger = logging.getLogger(__name__)

if os.getenv("SENTRY_DSN"):
    sentry_sdk.init(
        dsn=os.getenv("SENTRY_DSN"),
        environment=os.getenv("ENV", "production"),
        traces_sample_rate=0.1,
    )

PREDICTIONS_TABLE = "NRFI_DB.ML.PREDICTIONS"


def _as_utc(value: object) -> datetime:
    """Parse a timestamp and normalize it to timezone-aware UTC."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    else:
        raise ValueError("timestamp must be a datetime or ISO-8601 string")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class NFRIDailyPredictor:
    def __init__(self, model_version: Optional[str] = None,
                 config: Optional[Config] = None):
        self.config = config or Config()
        self.sf = SnowflakeLoader()
        approved_version = production_model_version(self.sf)
        if model_version is not None and model_version != approved_version:
            raise ValueError(
                f"requested model {model_version} is not the approved production "
                f"version {approved_version}")
        self.model_version = approved_version
        self.builder = FeatureBuilder(self.sf)
        self.odds = OpticOddsIngester()
        self.trainer = NFRIModelTrainer()
        self.trainer.load_model(self.config.MODEL_DIR, self.model_version)
        logger.info(f"loaded registry-approved production model {self.model_version}")

    def get_todays_games(self, target_date: Optional[str] = None) -> List[Dict]:
        """Read the target slate and probable pitchers from MLB Stats API."""
        import statsapi

        target_date = target_date or datetime.now(TZ_ET).strftime("%Y-%m-%d")
        schedule = statsapi.schedule(date=target_date)
        games = []
        for game in schedule:
            game_id = game.get("game_id")
            if game_id is None:
                continue
            games.append({
                "game_id": str(game_id),
                "game_date": target_date,
                "home_team": game.get("home_name"),
                "away_team": game.get("away_name"),
                "home_pitcher_id": game.get("home_probable_pitcher_id") or None,
                "away_pitcher_id": game.get("away_probable_pitcher_id") or None,
                "home_pitcher_name": game.get("home_probable_pitcher") or None,
                "away_pitcher_name": game.get("away_probable_pitcher") or None,
                "venue_id": game.get("venue_id"),
                "game_time": game.get("game_datetime"),
                "is_doubleheader": game.get("doubleheader", "N") != "N",
                "lineups": None,
                "lineup_confirmed": False,
            })
        logger.info(f"{len(games)} games scheduled on {target_date}")
        return games

    @staticmethod
    def market_consensus(entry: Optional[dict], now_utc: datetime) -> Dict:
        """Median no-vig P(YRFI) across latest valid per-book snapshots."""
        result = {
            "p_yrfi_market": None,
            "books_n": 0,
            "odds_age_sec": None,
            "best_nrfi_american": None,
        }
        if not entry or not entry.get("books"):
            return result

        books = entry["books"]
        result["books_n"] = len(books)
        newest = entry.get("newest_captured_at")
        if newest is not None:
            try:
                captured_at = _as_utc(newest)
                result["odds_age_sec"] = int(
                    (_as_utc(now_utc) - captured_at).total_seconds())
            except (TypeError, ValueError, OverflowError):
                result["odds_age_sec"] = None

        probabilities = []
        for book in books.values():
            try:
                probability = float(book.get("yrfi_prob_novig"))
            except (TypeError, ValueError):
                continue
            if np.isfinite(probability) and 0.0 <= probability <= 1.0:
                probabilities.append(probability)
        if len(probabilities) >= MIN_BOOKS_FOR_MARKET:
            result["p_yrfi_market"] = float(statistics.median(probabilities))

        nrfi_prices = []
        for book in books.values():
            try:
                price = float(book.get("nrfi_american"))
            except (TypeError, ValueError):
                continue
            if np.isfinite(price) and price != 0:
                nrfi_prices.append(price)
        if nrfi_prices:
            result["best_nrfi_american"] = max(nrfi_prices)
        return result

    def score_game(self, game: Dict, odds_by_matchup: dict,
                   now_utc: datetime) -> Dict:
        now_utc = _as_utc(now_utc)
        row = {
            "game_id": game["game_id"],
            "game_date": game["game_date"],
            "home_team": game["home_team"],
            "away_team": game["away_team"],
            "home_pitcher": game.get("home_pitcher_name"),
            "away_pitcher": game.get("away_pitcher_name"),
            "model_version": self.model_version,
            "predicted_at": now_utc.isoformat(),
            "lineup_confirmed": bool(game.get("lineup_confirmed", False)),
            "p_yrfi": None,
            "p_yrfi_market": None,
            "edge": None,
            "books_n": 0,
            "odds_age_sec": None,
            "tier": None,
            "status": "OK",
            "block_reason": None,
        }

        if game.get("home_pitcher_id") is None or game.get("away_pitcher_id") is None:
            row.update(status="BLOCKED", block_reason="no_probable_pitcher")
            return row

        try:
            features = self.builder.build_game(game)
        except Exception as exc:
            sentry_sdk.capture_exception(exc)
            row.update(
                status="BLOCKED",
                block_reason=f"feature_error:{type(exc).__name__}")
            return row

        feature_coverage = coverage(features)
        block_reason = coverage_blocks(feature_coverage)
        if block_reason:
            row.update(status="BLOCKED", block_reason=block_reason)
            return row

        matrix = np.array([[
            features.get(name, np.nan) for name in self.trainer.feature_names
        ]], dtype=float)
        calibrated_probability = float(self.trainer.predict_proba(matrix)[0])
        if not np.isfinite(calibrated_probability) or not 0.0 <= calibrated_probability <= 1.0:
            row.update(status="BLOCKED", block_reason="invalid_model_probability")
            return row

        venue_rate = self.trainer.venue_yrfi_rates.get(str(game.get("venue_id")))
        row["p_yrfi"] = float(shrink_to_venue(
            calibrated_probability,
            venue_rate,
            n_eff_for_game(features, feature_coverage),
        ))

        market = self.market_consensus(
            odds_by_matchup.get((game["home_team"], game["away_team"])),
            now_utc,
        )
        row.update(
            books_n=market["books_n"],
            odds_age_sec=market["odds_age_sec"],
        )
        usable, reason = market_usable(
            market["p_yrfi_market"],
            market["books_n"],
            market["odds_age_sec"],
        )
        if usable:
            row["p_yrfi_market"] = market["p_yrfi_market"]
            row["edge"] = row["p_yrfi"] - market["p_yrfi_market"]
        else:
            row.update(status="DEGRADED", block_reason=reason)

        row["tier"] = tier_for(
            row["status"],
            row["lineup_confirmed"],
            feature_coverage,
            market["books_n"],
        )
        return row

    def run(self, target_date: Optional[str] = None) -> List[Dict]:
        now_utc = datetime.now(timezone.utc)
        games = self.get_todays_games(target_date)
        if not games:
            logger.warning("no games scheduled")
            return []

        date_string = games[0]["game_date"]
        self.builder.prepare(max_date=date_string)
        odds_by_matchup = self.odds.get_nrfi_odds(date_string)
        rows = [
            self.score_game(game, odds_by_matchup, now_utc)
            for game in games
        ]
        self.sf.bulk_insert(PREDICTIONS_TABLE, rows)

        ok_count = sum(1 for row in rows if row["status"] == "OK")
        degraded_count = sum(1 for row in rows if row["status"] == "DEGRADED")
        blocked_count = sum(1 for row in rows if row["status"] == "BLOCKED")
        logger.info(
            f"scored {len(rows)} games: {ok_count} OK, "
            f"{degraded_count} DEGRADED, {blocked_count} BLOCKED")
        return rows


def main() -> None:
    predictor = NFRIDailyPredictor()
    print(json.dumps(predictor.run(), indent=2, default=str))


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    main()
