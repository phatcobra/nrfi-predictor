"""Daily NRFI/YRFI scoring (paper-mode, fail-closed).

Redlines enforced here:
  - NO bet picks and NO staking output. What is emitted: a calibrated
    probability, a de-vigged market consensus, and a DIAGNOSTIC edge.
  - Odds older than ODDS_MAX_AGE_SECONDS => edge and market are null and the
    game is DEGRADED (reason recorded). Model probability may still display.
  - Feature coverage below FEATURE_COVERAGE_MIN, missing probable pitcher, or
    any feature-build exception => game is BLOCKED: no probability at all.
  - Unconfirmed lineup caps the confidence tier at MEDIUM.
  - Every row carries model_version and predicted_at (auditable history).
"""
from __future__ import annotations

import glob
import json
import logging
import os
import statistics
from datetime import datetime, timezone
from typing import Dict, List, Optional

import numpy as np
from nrfi._obs import sentry_sdk
from nrfi.config import Config, MIN_BOOKS_FOR_MARKET, TZ_ET
from nrfi.guards import coverage_blocks, market_usable, tier_for
from nrfi.build_features import FeatureBuilder, coverage
from nrfi.ensemble import n_eff_for_game, shrink_to_venue
from nrfi.ingest_opticodds import OpticOddsIngester
from nrfi.snowflake_loader import SnowflakeLoader
from nrfi.train import NFRIModelTrainer

logger = logging.getLogger(__name__)

if os.getenv("SENTRY_DSN"):
    sentry_sdk.init(dsn=os.getenv("SENTRY_DSN"),
                    environment=os.getenv("ENV", "production"),
                    traces_sample_rate=0.1)

PREDICTIONS_TABLE = "NRFI_DB.ML.PREDICTIONS"


class NFRIDailyPredictor:
    def __init__(self, model_version: Optional[str] = None,
                 config: Optional[Config] = None):
        self.config = config or Config()
        self.sf = SnowflakeLoader()
        self.builder = FeatureBuilder(self.sf)
        self.odds = OpticOddsIngester()
        self.trainer = NFRIModelTrainer()
        self.model_version = model_version or self._latest_model_version()
        self.trainer.load_model(self.config.MODEL_DIR, self.model_version)
        logger.info(f"loaded model {self.model_version}")

    def _latest_model_version(self) -> str:
        metas = glob.glob(os.path.join(self.config.MODEL_DIR, "nrfi_meta_*.json"))
        if not metas:
            raise RuntimeError("no trained model found - refusing to run without one")
        versions = sorted(m.split("nrfi_meta_")[-1].removesuffix(".json") for m in metas)
        return versions[-1]

    # -------------------------------------------------------------- schedule

    def get_todays_games(self, target_date: Optional[str] = None) -> List[Dict]:
        """Schedule + probable pitchers from the MLB Stats API (ET dates)."""
        import statsapi  # lazy: not needed for offline scoring tests
        target_date = target_date or datetime.now(TZ_ET).strftime("%Y-%m-%d")
        schedule = statsapi.schedule(date=target_date)
        games = []
        for g in schedule:
            games.append({
                "game_id": str(g.get("game_id")),
                "game_date": target_date,
                "home_team": g.get("home_name"),
                "away_team": g.get("away_name"),
                "home_pitcher_id": g.get("home_probable_pitcher_id") or None,
                "away_pitcher_id": g.get("away_probable_pitcher_id") or None,
                "home_pitcher_name": g.get("home_probable_pitcher") or None,
                "away_pitcher_name": g.get("away_probable_pitcher") or None,
                "venue_id": g.get("venue_id"),
                "game_time": g.get("game_datetime"),
                "is_doubleheader": g.get("doubleheader", "N") != "N",
                "lineups": None,            # wired in Phase 3 lineup feed
                "lineup_confirmed": False,  # honest default until feed exists
            })
        logger.info(f"{len(games)} games scheduled on {target_date}")
        return games

    # -------------------------------------------------------------- market

    @staticmethod
    def market_consensus(entry: Optional[dict], now_utc: datetime) -> Dict:
        """Median no-vig P(YRFI) across latest per-book snapshots + freshness."""
        out = {"p_yrfi_market": None, "books_n": 0, "odds_age_sec": None,
               "best_nrfi_american": None}
        if not entry or not entry.get("books"):
            return out
        books = entry["books"]
        out["books_n"] = len(books)
        newest = entry.get("newest_captured_at")
        if newest is not None:
            ts = str(newest)
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                out["odds_age_sec"] = int((now_utc - dt).total_seconds())
            except ValueError:
                out["odds_age_sec"] = None
        probs = [b["yrfi_prob_novig"] for b in books.values()
                 if b.get("yrfi_prob_novig") is not None]
        if len(probs) >= MIN_BOOKS_FOR_MARKET:
            out["p_yrfi_market"] = float(statistics.median(probs))
        nrfi_prices = [b["nrfi_american"] for b in books.values()
                       if b.get("nrfi_american") is not None]
        if nrfi_prices:
            out["best_nrfi_american"] = max(nrfi_prices)
        return out

    # -------------------------------------------------------------- scoring

    def score_game(self, game: Dict, odds_by_matchup: dict,
                   now_utc: datetime) -> Dict:
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
            "p_yrfi": None, "p_yrfi_market": None, "edge": None,
            "books_n": 0, "odds_age_sec": None,
            "tier": None, "status": "OK", "block_reason": None,
        }

        # ---- fail-closed gate 1: probable pitchers
        if game.get("home_pitcher_id") is None or game.get("away_pitcher_id") is None:
            row.update(status="BLOCKED", block_reason="no_probable_pitcher")
            return row

        # ---- features (exception or low coverage => BLOCKED)
        try:
            feats = self.builder.build_game(game)
        except Exception as e:
            sentry_sdk.capture_exception(e)
            row.update(status="BLOCKED", block_reason=f"feature_error:{type(e).__name__}")
            return row
        cov = coverage(feats)
        block = coverage_blocks(cov)
        if block:
            row.update(status="BLOCKED", block_reason=block)
            return row

        X = np.array([[feats.get(n, np.nan) for n in self.trainer.feature_names]],
                     dtype=float)
        p_cal = float(self.trainer.predict_proba(X)[0])
        venue_rate = self.trainer.venue_yrfi_rates.get(str(game.get("venue_id")))
        row["p_yrfi"] = shrink_to_venue(p_cal, venue_rate,
                                        n_eff_for_game(feats, cov))

        # ---- market (stale/missing => DEGRADED, edge stays null)
        m = self.market_consensus(
            odds_by_matchup.get((game["home_team"], game["away_team"])), now_utc)
        row.update(books_n=m["books_n"], odds_age_sec=m["odds_age_sec"])
        usable, reason = market_usable(m["p_yrfi_market"], m["books_n"],
                                       m["odds_age_sec"])
        if usable:
            row["p_yrfi_market"] = m["p_yrfi_market"]
            row["edge"] = row["p_yrfi"] - m["p_yrfi_market"]  # diagnostic only
        else:
            row.update(status="DEGRADED", block_reason=reason)

        row["tier"] = tier_for(row["status"], row["lineup_confirmed"], cov,
                               m["books_n"])
        return row

    def run(self, target_date: Optional[str] = None) -> List[Dict]:
        now_utc = datetime.now(timezone.utc)
        games = self.get_todays_games(target_date)
        if not games:
            logger.warning("no games scheduled")
            return []
        date_str = games[0]["game_date"]
        self.builder.prepare(max_date=date_str)  # bulk pull once, leakage-safe
        odds_by_matchup = self.odds.get_nrfi_odds(date_str)

        rows = [self.score_game(g, odds_by_matchup, now_utc) for g in games]
        self.sf.bulk_insert(PREDICTIONS_TABLE, rows)

        ok = sum(1 for r in rows if r["status"] == "OK")
        degraded = sum(1 for r in rows if r["status"] == "DEGRADED")
        blocked = sum(1 for r in rows if r["status"] == "BLOCKED")
        logger.info(f"scored {len(rows)} games: {ok} OK, {degraded} DEGRADED, "
                    f"{blocked} BLOCKED (paper-mode, diagnostic edge only)")
        return rows


def main() -> None:
    predictor = NFRIDailyPredictor()
    rows = predictor.run()
    print(json.dumps(rows, indent=2, default=str))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    main()
