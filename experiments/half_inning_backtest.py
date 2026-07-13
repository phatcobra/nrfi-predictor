"""Leakage-safe experiment using the real game history from the alternate branch.

This file is intentionally isolated from the production package. It models each
half-inning as a separate event, combines the two probabilities into P(YRFI),
and evaluates strictly by future season against training climatology.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

PRIOR_HALF = 0.29


@dataclass
class State:
    total: float = 0.0
    count: int = 0
    recent: deque = field(default_factory=lambda: deque(maxlen=20))

    def add(self, value: float) -> None:
        self.total += value
        self.count += 1
        self.recent.append(value)

    def rate(self, prior: float, strength: float) -> float:
        return (self.total + prior * strength) / (self.count + strength)

    def recent_rate(self, prior: float, strength: float) -> float:
        n = len(self.recent)
        return (sum(self.recent) + prior * strength) / (n + strength)


def load_games(root: Path) -> pd.DataFrame:
    frames = [pd.read_csv(path) for path in sorted(root.glob("games_*.csv"))]
    games = pd.concat(frames, ignore_index=True)
    games = games[
        (games["status"] == "Final")
        & (games["game_type"] == "R")
        & games["first_inning_runs_away"].notna()
        & games["first_inning_runs_home"].notna()
        & games["home_probable_pitcher_id"].notna()
        & games["away_probable_pitcher_id"].notna()
    ].copy()
    games["game_date"] = pd.to_datetime(games["game_date"], errors="raise")
    games["game_pk"] = games["game_pk"].astype(str)
    games["yrfi"] = (
        games["first_inning_runs_away"].astype(float)
        + games["first_inning_runs_home"].astype(float)
        > 0
    ).astype(int)
    return games.sort_values(["game_date", "game_pk"]).reset_index(drop=True)


def build_half_features(games: pd.DataFrame) -> pd.DataFrame:
    teams: dict[tuple[int, str], State] = defaultdict(State)
    pitchers: dict[int, State] = defaultdict(State)
    venues: dict[tuple[int, str], State] = defaultdict(State)
    league: dict[str, State] = defaultdict(State)
    rows: list[dict] = []

    for game_date, slate in games.groupby("game_date", sort=True):
        pending: list[tuple[dict, int, int, int, str, float]] = []
        for game in slate.to_dict("records"):
            venue = int(game["venue_id"])
            night = float(str(game.get("day_night", "")).lower() == "night")
            halves = (
                (
                    "top",
                    int(game["away_team_id"]),
                    int(float(game["home_probable_pitcher_id"])),
                    float(game["first_inning_runs_away"] > 0),
                ),
                (
                    "bottom",
                    int(game["home_team_id"]),
                    int(float(game["away_probable_pitcher_id"])),
                    float(game["first_inning_runs_home"] > 0),
                ),
            )
            for side, offense, pitcher, target in halves:
                league_rate = league[side].rate(PRIOR_HALF, 500.0)
                offense_state = teams[(offense, side)]
                pitcher_state = pitchers[pitcher]
                venue_state = venues[(venue, side)]
                rows.append({
                    "game_pk": game["game_pk"],
                    "game_date": game_date,
                    "season": int(game["season"]),
                    "half": side,
                    "target": target,
                    "game_yrfi": int(game["yrfi"]),
                    "offense_rate": offense_state.rate(league_rate, 30.0),
                    "offense_recent": offense_state.recent_rate(league_rate, 10.0),
                    "pitcher_rate": pitcher_state.rate(league_rate, 20.0),
                    "pitcher_recent": pitcher_state.recent_rate(league_rate, 8.0),
                    "venue_rate": venue_state.rate(league_rate, 100.0),
                    "league_rate": league_rate,
                    "offense_log_n": np.log1p(offense_state.count),
                    "pitcher_log_n": np.log1p(pitcher_state.count),
                    "is_bottom": float(side == "bottom"),
                    "is_night": night,
                    "month_sin": np.sin(2 * np.pi * game_date.month / 12),
                    "month_cos": np.cos(2 * np.pi * game_date.month / 12),
                })
                pending.append((game, offense, pitcher, venue, side, target))

        # Same-day games are updated only after all same-day features exist.
        for _, offense, pitcher, venue, side, target in pending:
            teams[(offense, side)].add(target)
            pitchers[pitcher].add(target)
            venues[(venue, side)].add(target)
            league[side].add(target)

    return pd.DataFrame(rows)


FEATURES = [
    "offense_rate", "offense_recent", "pitcher_rate", "pitcher_recent",
    "venue_rate", "league_rate", "offense_log_n", "pitcher_log_n",
    "is_bottom", "is_night", "month_sin", "month_cos",
]


def pipeline(c_value: float) -> Pipeline:
    return Pipeline([
        ("impute", SimpleImputer(strategy="median", add_indicator=True)),
        ("scale", StandardScaler()),
        ("model", LogisticRegression(
            C=c_value,
            penalty="l2",
            max_iter=2000,
            random_state=42,
        )),
    ])


def game_probabilities(frame: pd.DataFrame, half_prob: np.ndarray) -> pd.DataFrame:
    scored = frame[["game_pk", "season", "game_yrfi", "half"]].copy()
    scored["half_probability"] = np.clip(half_prob, 1e-6, 1 - 1e-6)
    pivot = scored.pivot(index="game_pk", columns="half", values="half_probability")
    meta = scored.groupby("game_pk", as_index=True).agg(
        season=("season", "first"), actual=("game_yrfi", "first"))
    result = meta.join(pivot, how="inner").dropna(subset=["top", "bottom"])
    result["raw_probability"] = 1.0 - (
        1.0 - result["top"]) * (1.0 - result["bottom"])
    return result


def fit_calibrator(raw_probability: np.ndarray, actual: np.ndarray):
    logits = np.log(np.clip(raw_probability, 1e-6, 1 - 1e-6) /
                    np.clip(1 - raw_probability, 1e-6, 1 - 1e-6)).reshape(-1, 1)
    model = LogisticRegression(C=1.0, max_iter=1000, random_state=42)
    model.fit(logits, actual)
    return model


def apply_calibrator(model, raw_probability: np.ndarray) -> np.ndarray:
    logits = np.log(np.clip(raw_probability, 1e-6, 1 - 1e-6) /
                    np.clip(1 - raw_probability, 1e-6, 1 - 1e-6)).reshape(-1, 1)
    return model.predict_proba(logits)[:, 1]


def metrics(actual: np.ndarray, probability: np.ndarray) -> dict:
    probability = np.clip(probability, 1e-6, 1 - 1e-6)
    return {
        "n": int(len(actual)),
        "logloss": float(log_loss(actual, probability)),
        "brier": float(brier_score_loss(actual, probability)),
        "auc": float(roc_auc_score(actual, probability)),
        "mean_probability": float(np.mean(probability)),
        "actual_rate": float(np.mean(actual)),
    }


def backtest(half_frame: pd.DataFrame) -> dict:
    report: dict[str, dict] = {}
    for test_season in range(2021, 2026):
        validation_season = test_season - 1
        core = half_frame[half_frame["season"] < validation_season]
        validation = half_frame[half_frame["season"] == validation_season]
        train = half_frame[half_frame["season"] < test_season]
        test = half_frame[half_frame["season"] == test_season]
        if min(len(core), len(validation), len(test)) == 0:
            continue

        best_c = None
        best_loss = float("inf")
        for c_value in (0.005, 0.02, 0.1, 0.5, 2.0):
            candidate = pipeline(c_value).fit(core[FEATURES], core["target"])
            validation_half = candidate.predict_proba(validation[FEATURES])[:, 1]
            validation_games = game_probabilities(validation, validation_half)
            loss = log_loss(
                validation_games["actual"],
                np.clip(validation_games["raw_probability"], 1e-6, 1 - 1e-6),
            )
            if loss < best_loss:
                best_loss = float(loss)
                best_c = c_value

        half_model = pipeline(float(best_c)).fit(train[FEATURES], train["target"])
        validation_half = half_model.predict_proba(validation[FEATURES])[:, 1]
        validation_games = game_probabilities(validation, validation_half)
        calibrator = fit_calibrator(
            validation_games["raw_probability"].to_numpy(),
            validation_games["actual"].to_numpy(),
        )

        test_half = half_model.predict_proba(test[FEATURES])[:, 1]
        test_games = game_probabilities(test, test_half)
        probability = apply_calibrator(
            calibrator, test_games["raw_probability"].to_numpy())
        actual = test_games["actual"].to_numpy()
        model_metrics = metrics(actual, probability)

        train_games = train.groupby("game_pk", as_index=False).agg(
            actual=("game_yrfi", "first"))
        baseline_rate = float(train_games["actual"].mean())
        baseline = metrics(actual, np.full(len(actual), baseline_rate))
        report[str(test_season)] = {
            "selected_c": best_c,
            "validation_raw_logloss": best_loss,
            "model": model_metrics,
            "baseline": baseline,
            "logloss_improvement": baseline["logloss"] - model_metrics["logloss"],
            "brier_improvement": baseline["brier"] - model_metrics["brier"],
        }
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    args = parser.parse_args()
    games = load_games(Path(args.data))
    halves = build_half_features(games)
    report = backtest(halves)
    print(json.dumps({
        "games": int(len(games)),
        "half_rows": int(len(halves)),
        "report": report,
    }, indent=2))


if __name__ == "__main__":
    main()
