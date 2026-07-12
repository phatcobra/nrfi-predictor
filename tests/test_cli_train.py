"""End-to-end `nrfi train` smoke test against a synthetic on-disk store.

Generates several seasons of synthetic games in the exact store format,
then runs the real CLI entry point and checks every artifact it must emit.
No network access anywhere.
"""

import numpy as np
import pandas as pd

from nrfi.data.statsapi import GAME_COLUMNS


def synthetic_season(season: int, rng: np.random.Generator, n_teams: int = 12, games_per_day: int = 6):
    teams = [9000 + i for i in range(n_teams)]
    pitchers = {t: [600000 + t * 10 + s for s in range(6)] for t in teams}
    venues = {t: 7000 + t for t in teams}
    rows = []
    game_pk = season * 100000
    date = pd.Timestamp(f"{season}-04-01")
    for day in range(110):
        order = rng.permutation(teams)
        for i in range(games_per_day):
            home, away = int(order[2 * i]), int(order[2 * i + 1])
            hp = int(rng.choice(pitchers[home]))
            ap = int(rng.choice(pitchers[away]))
            # Half-inning scoring with a strong pitcher-quality effect so a
            # correctly wired pipeline MUST beat climatology; a feature/label
            # misalignment would push skill to ~0 and fail this test.
            hp_skill = (hp % 6) * 0.12
            ap_skill = (ap % 6) * 0.12
            fi_away = int(rng.poisson(0.15 + hp_skill))
            fi_home = int(rng.poisson(0.15 + ap_skill))
            d = (date + pd.Timedelta(days=day)).date().isoformat()
            rows.append(
                {
                    "game_pk": game_pk,
                    "season": season,
                    "game_date": d,
                    "game_datetime_utc": f"{d}T23:05:00Z",
                    "game_type": "R",
                    "status": "Final",
                    "day_night": "night" if game_pk % 3 else "day",
                    "double_header": "N",
                    "venue_id": venues[home],
                    "venue_name": f"Fixture Park {home}",
                    "home_team_id": home,
                    "home_team_name": f"Fixture Team {home}",
                    "away_team_id": away,
                    "away_team_name": f"Fixture Team {away}",
                    "home_probable_pitcher_id": hp,
                    "home_probable_pitcher_name": f"Fixture Pitcher {hp}",
                    "away_probable_pitcher_id": ap,
                    "away_probable_pitcher_name": f"Fixture Pitcher {ap}",
                    "innings_recorded": 9,
                    "first_inning_runs_away": fi_away,
                    "first_inning_runs_home": fi_home,
                }
            )
            game_pk += 1
    return pd.DataFrame(rows, columns=GAME_COLUMNS)


def test_cli_train_end_to_end(tmp_path, monkeypatch):
    rng = np.random.default_rng(11)
    data_dir = tmp_path / "data" / "processed"
    data_dir.mkdir(parents=True)
    for season in range(2013, 2021):
        synthetic_season(season, rng).to_csv(data_dir / f"games_{season}.csv", index=False)

    monkeypatch.setenv("NRFI_REPO_ROOT", str(tmp_path))
    from nrfi.cli import main

    assert main(["train"]) == 0

    assert (tmp_path / "models" / "nrfi_model.joblib").exists()
    assert (tmp_path / "models" / "nrfi_model_metadata.json").exists()
    assert (tmp_path / "reports" / "backtest.md").exists()
    assert (tmp_path / "reports" / "backtest_metrics.csv").exists()
    assert (tmp_path / "reports" / "calibration_table.csv").exists()
    assert (tmp_path / "reports" / "data_coverage.md").exists()

    metrics = pd.read_csv(tmp_path / "reports" / "backtest_metrics.csv")
    pooled = metrics[metrics["season"] == "ALL"].iloc[0]
    # The synthetic generator embeds real pitcher skill, so the model must
    # beat climatology out-of-time.
    assert pooled["brier_skill_score"] > 0
    assert pooled["roc_auc"] > 0.5
