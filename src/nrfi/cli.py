"""Single CLI for the autonomous pipeline: ingest / train / predict.

These are the exact commands GitHub Actions runs; a human can run the same
commands locally and get identical behavior.
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys

import pandas as pd

from nrfi.backtest import render_backtest_report, walk_forward_backtest
from nrfi.config import DEFAULT_START_SEASON, Paths, TrainConfig
from nrfi.data import statsapi, store
from nrfi.data import weather as weather_mod
from nrfi.features import build_training_frame
from nrfi.model import NRFIModel, fit_model, trainable_rows
from nrfi.predict import fetch_slate, predict_slate, render_predictions_markdown, today_et

log = logging.getLogger("nrfi")


def cmd_ingest(args: argparse.Namespace) -> int:
    paths = Paths().ensure()
    end_season = args.end_season or dt.date.today().year
    seasons = range(args.start_season, end_season + 1)

    venues_rows = statsapi.fetch_venues()
    store.write_venues(paths.data_dir, venues_rows)
    log.info("venues: %d rows", len(venues_rows))

    for season in seasons:
        path = store.season_path(paths.data_dir, season)
        is_closed_past_season = season < end_season
        if path.exists() and is_closed_past_season and not args.force:
            log.info("season %d already stored, skipping (use --force to refetch)", season)
            continue
        rows = statsapi.fetch_season_games(season)
        if not rows and season < end_season:
            log.warning("season %d returned zero games", season)
        store.write_season(paths.data_dir, season, rows)

    if args.weather:
        games = store.load_games(paths.data_dir)
        venues = store.load_venues(paths.data_dir)
        existing = store.load_weather(paths.data_dir)
        if existing is not None and not existing.empty:
            missing = games[~games["game_pk"].isin(existing["game_pk"])]
        else:
            missing = games
        # Only completed games need archive weather.
        missing = missing[missing["status"] == "Final"]
        log.info("fetching archive weather for %d games", len(missing))
        if not missing.empty:
            fetched = weather_mod.fetch_weather_for_games(missing, venues)
            combined = (
                pd.concat([existing, fetched], ignore_index=True)
                if existing is not None and not existing.empty
                else fetched
            )
            combined = combined.drop_duplicates("game_pk", keep="last")
            store.write_weather(paths.data_dir, combined)
            log.info("weather store now has %d rows", len(combined))
    return 0


def cmd_train(args: argparse.Namespace) -> int:
    paths = Paths().ensure()
    cfg = TrainConfig()
    games = store.load_games(paths.data_dir)
    weather = store.load_weather(paths.data_dir)
    log.info("loaded %d games, weather rows: %s", len(games), 0 if weather is None else len(weather))

    features_frame = build_training_frame(games, weather=weather)
    _write_coverage_report(paths, games, features_frame)

    metrics, pooled, calibration = walk_forward_backtest(features_frame, cfg)
    model = fit_model(features_frame, cfg)
    model.metadata["walk_forward_pooled"] = (
        metrics.loc[metrics["season"] == "ALL"].iloc[0].drop("season").to_dict()
    )

    report = render_backtest_report(metrics, calibration, model.metadata)
    (paths.reports_dir / "backtest.md").write_text(report)
    metrics.to_csv(paths.reports_dir / "backtest_metrics.csv", index=False)
    calibration.to_csv(paths.reports_dir / "calibration_table.csv", index=False)
    pooled.to_csv(paths.reports_dir / "backtest_predictions.csv", index=False)

    model_path, meta_path = model.save(paths.models_dir)
    log.info("model saved: %s (+ %s)", model_path, meta_path)

    pooled_row = metrics.loc[metrics["season"] == "ALL"].iloc[0]
    print(
        "WALK-FORWARD (pooled): "
        f"n={int(pooled_row['n_games'])} "
        f"logloss={pooled_row['log_loss_model']:.4f} (baseline {pooled_row['log_loss_baseline']:.4f}) "
        f"brier={pooled_row['brier_model']:.4f} (baseline {pooled_row['brier_baseline']:.4f}) "
        f"skill={pooled_row['brier_skill_score']:.4f} auc={pooled_row['roc_auc']:.4f}"
    )
    return 0


def cmd_predict(args: argparse.Namespace) -> int:
    paths = Paths().ensure()
    date = args.date or today_et()
    model = NRFIModel.load(paths.models_dir)
    history = store.load_games(paths.data_dir)

    slate = fetch_slate(date)
    weather = None
    if args.weather and not slate.empty:
        venues = store.load_venues(paths.data_dir)
        if venues is not None:
            weather = weather_mod.fetch_forecast_for_slate(slate, venues)

    predictions = predict_slate(history, slate, model, weather=weather)
    csv_path = paths.predictions_dir / f"{date}.csv"
    predictions.to_csv(csv_path, index=False)
    md = render_predictions_markdown(predictions, date)
    (paths.predictions_dir / "latest.md").write_text(md)
    print(md)
    log.info("wrote %s (%d games)", csv_path, len(predictions))
    return 0


def _write_coverage_report(paths: Paths, games: pd.DataFrame, features_frame: pd.DataFrame) -> None:
    per_season = []
    trainable = trainable_rows(features_frame)
    for season, group in games.groupby("season"):
        finals = group[group["status"] == "Final"]
        both_probables = finals["home_probable_pitcher_id"].notna() & finals["away_probable_pitcher_id"].notna()
        season_trainable = trainable[trainable["season"] == season]
        per_season.append(
            {
                "season": int(season),
                "games_stored": len(group),
                "finals": len(finals),
                "probable_pitcher_coverage": round(float(both_probables.mean()), 4) if len(finals) else 0.0,
                "trainable_rows": len(season_trainable),
                "yrfi_rate": round(float(season_trainable["yrfi"].mean()), 4)
                if len(season_trainable)
                else float("nan"),
            }
        )
    table = pd.DataFrame(per_season)
    lines = [
        "# Data coverage",
        "",
        "Per-season ingest coverage. `trainable_rows` requires a Final game,",
        "a valid first-inning label, and both probable pitchers recorded.",
        "",
        table.to_markdown(index=False),
        "",
    ]
    (paths.reports_dir / "data_coverage.md").write_text("\n".join(lines))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nrfi", description="NRFI/YRFI autonomous pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="fetch/refresh historical seasons from MLB StatsAPI")
    p_ingest.add_argument("--start-season", type=int, default=DEFAULT_START_SEASON)
    p_ingest.add_argument("--end-season", type=int, default=0, help="default: current year")
    p_ingest.add_argument("--force", action="store_true", help="refetch seasons already stored")
    p_ingest.add_argument("--weather", action=argparse.BooleanOptionalAction, default=False)
    p_ingest.set_defaults(func=cmd_ingest)

    p_train = sub.add_parser("train", help="walk-forward backtest + fit and save final model")
    p_train.set_defaults(func=cmd_train)

    p_predict = sub.add_parser("predict", help="predict a day's slate")
    p_predict.add_argument("--date", type=str, default="", help="YYYY-MM-DD (default: today US/Eastern)")
    p_predict.add_argument("--weather", action=argparse.BooleanOptionalAction, default=True)
    p_predict.set_defaults(func=cmd_predict)
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
