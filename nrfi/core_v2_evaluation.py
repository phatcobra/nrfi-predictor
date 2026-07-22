"""NRFI_CORE_V2 predeclared chronological evaluation, ablations, calibration.

Executes the frozen NRFI_CORE_V2 protocol on the canonical historical matrix:
walk-forward folds (train <=2021 -> 2022, <=2022 -> 2023, <=2023 -> 2024), the
predeclared domain ablations, logistic / spline-GAM / constrained-LightGBM
candidates raw and with prior-completed-fold out-of-fold sigmoid calibration,
an expanding-climatology baseline, official-date cluster-bootstrap intervals,
and the frozen promotion gate. Deterministic and leakage-free; the locked 2025
season is never read. The default and only-supported conclusion until the gate
is passed is PREDICTIVE SKILL NOT ESTABLISHED.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

from nrfi.deterministic_resampling import cluster_bootstrap_means
from nrfi.pregame_snapshot import canonical_json_bytes

EVAL_SCHEMA_VERSION = "nrfi_core_v2_evaluation.v1"
EXPECTED_MATRIX_IDENTITY = (
    "83003ad4445d3f6be0cc0c7b7d3637b63ee4d8f32e2de4b3cdb89f76f00ffb74"
)
PROMOTION_FOLDS = ((2021, 2022), (2022, 2023), (2023, 2024))
CALIB_INTERCEPT_BAND = (-0.15, 0.15)
CALIB_SLOPE_BAND = (0.8, 1.2)
BOOTSTRAP_REPLICATES = 2000
BOOTSTRAP_SEED = 20260722
EPS = 1e-12

ABLATIONS: dict[str, tuple[str, ...]] = {
    "pitcher_only": ("pitcher",),
    "team_only": ("team",),
    "park_only": ("park",),
    "workload_only": ("workload",),
    "schedule_travel_only": ("schedule_travel",),
    "pitcher_team": ("pitcher", "team"),
    "pitcher_park": ("pitcher", "park"),
    "pitcher_workload": ("pitcher", "workload"),
    "team_park": ("team", "park"),
    "pitcher_team_park": ("pitcher", "team", "park"),
    "pitcher_team_workload": ("pitcher", "team", "workload"),
    "pitcher_team_park_workload": ("pitcher", "team", "park", "workload"),
    "full_nrfi_core_v2": (
        "pitcher",
        "team",
        "park",
        "workload",
        "schedule_travel",
    ),
}


def _identity(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _domain_of(column: str) -> str:
    """Assign a feature column to exactly one NRFI_CORE_V2 domain."""
    if column in ("park_factor", "park_first_inning_runs_per_game", "altitude_ft"):
        return "park"
    body = column
    for side in ("away_", "home_"):
        if column.startswith(side):
            body = column[len(side) :]
            break
    if body.startswith("p_"):
        return "pitcher"
    if body.startswith("t_"):
        return "team"
    if body.startswith("ctx_"):
        rest = body[len("ctx_") :]
        if rest.startswith("starter_"):
            return "workload"
        if rest.startswith(("park", "league", "altitude")):
            return "park"
        return "schedule_travel"
    return "schedule_travel"


def load_matrix(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    rows.sort(key=lambda r: (r["prediction_cutoff"], r["game_pk"]))
    return rows


def _feature_columns(rows: Sequence[dict[str, Any]]) -> list[str]:
    cols: set[str] = set()
    for r in rows:
        cols.update(r["features"].keys())
    return sorted(cols)


def _log_loss(y: np.ndarray, p: np.ndarray) -> np.ndarray:
    p = np.clip(p, EPS, 1 - EPS)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def _calibration_fit(logit: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """1-D logistic (Platt) calibration on prior out-of-fold logits."""
    from sklearn.linear_model import LogisticRegression

    model = LogisticRegression(solver="lbfgs", C=1e6, max_iter=1000)
    model.fit(logit.reshape(-1, 1), y)
    coef = float(np.asarray(model.coef_).ravel()[0])
    inter = float(np.asarray(model.intercept_).ravel()[0])
    return coef, inter


def _apply_calibration(logit: np.ndarray, slope: float, intercept: float) -> np.ndarray:
    z = slope * logit + intercept
    return 1.0 / (1.0 + np.exp(-z))


def _to_logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, EPS, 1 - EPS)
    return np.log(p / (1 - p))


def _calibration_slope_intercept(y: np.ndarray, p: np.ndarray) -> tuple[float, float]:
    from sklearn.linear_model import LogisticRegression

    logit = _to_logit(p)
    model = LogisticRegression(solver="lbfgs", C=1e6, max_iter=1000)
    model.fit(logit.reshape(-1, 1), y)
    coef = float(np.asarray(model.coef_).ravel()[0])
    inter = float(np.asarray(model.intercept_).ravel()[0])
    return coef, inter


def _ece(y: np.ndarray, p: np.ndarray, bins: int = 10) -> float:
    edges = np.linspace(0.0, 1.0, bins + 1)
    total = len(y)
    ece = 0.0
    for i in range(bins):
        lo, hi = edges[i], edges[i + 1]
        mask = (p >= lo) & (p < hi) if i < bins - 1 else (p >= lo) & (p <= hi)
        if not mask.any():
            continue
        ece += (mask.sum() / total) * abs(p[mask].mean() - y[mask].mean())
    return float(ece)


def _design(rows: Sequence[dict[str, Any]], columns: Sequence[str]) -> np.ndarray:
    out = np.full((len(rows), len(columns)), np.nan, dtype=float)
    for i, r in enumerate(rows):
        f = r["features"]
        for j, c in enumerate(columns):
            v = f.get(c)
            if isinstance(v, bool):
                out[i, j] = 1.0 if v else 0.0
            elif isinstance(v, (int, float)):
                out[i, j] = float(v)
    return out


def _standardize_impute(
    x_train: np.ndarray, x_test: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    medians = np.nanmedian(x_train, axis=0)
    medians = np.where(np.isnan(medians), 0.0, medians)
    tr = np.where(np.isnan(x_train), medians, x_train)
    te = np.where(np.isnan(x_test), medians, x_test)
    mean = tr.mean(axis=0)
    std = tr.std(axis=0)
    std = np.where(std < EPS, 1.0, std)
    return (tr - mean) / std, (te - mean) / std


def _fit_logistic(x: np.ndarray, y: np.ndarray, x_test: np.ndarray) -> np.ndarray:
    from sklearn.linear_model import LogisticRegression

    xt, xe = _standardize_impute(x, x_test)
    model = LogisticRegression(solver="lbfgs", C=0.25, max_iter=1000, random_state=0)
    model.fit(xt, y)
    return np.asarray(model.predict_proba(xe))[:, 1]


def _spline_basis(col: np.ndarray, knots: np.ndarray) -> np.ndarray:
    """Truncated-power natural-ish cubic basis for one column (fixed knots)."""
    parts = [col]
    for k in knots:
        parts.append(np.clip(col - k, 0.0, None) ** 3)
    return np.column_stack(parts)


def _fit_spline_gam(x: np.ndarray, y: np.ndarray, x_test: np.ndarray) -> np.ndarray:
    from sklearn.linear_model import LogisticRegression

    xt, xe = _standardize_impute(x, x_test)
    tr_parts, te_parts = [], []
    for j in range(xt.shape[1]):
        uniq = np.unique(xt[:, j])
        if len(uniq) <= 2:
            tr_parts.append(xt[:, [j]])
            te_parts.append(xe[:, [j]])
            continue
        knots = np.quantile(xt[:, j], [0.1, 0.35, 0.65, 0.9])
        knots = np.unique(knots)
        tr_parts.append(_spline_basis(xt[:, j], knots))
        te_parts.append(_spline_basis(xe[:, j], knots))
    xtb = np.column_stack(tr_parts)
    xeb = np.column_stack(te_parts)
    model = LogisticRegression(solver="lbfgs", C=0.25, max_iter=2000, random_state=0)
    model.fit(xtb, y)
    return np.asarray(model.predict_proba(xeb))[:, 1]


def _fit_lightgbm(x: np.ndarray, y: np.ndarray, x_test: np.ndarray) -> np.ndarray:
    import lightgbm as lgb

    model = lgb.LGBMClassifier(
        objective="binary",
        learning_rate=0.03,
        num_leaves=7,
        max_depth=3,
        min_child_samples=60,
        n_estimators=160,
        reg_lambda=1.0,
        subsample=1.0,
        colsample_bytree=1.0,
        deterministic=True,
        force_col_wise=True,
        n_jobs=1,
        random_state=0,
        verbosity=-1,
    )
    model.fit(x, y)
    return np.asarray(model.predict_proba(x_test))[:, 1]


MODELS = {
    "logistic": _fit_logistic,
    "spline_gam": _fit_spline_gam,
    "lightgbm": _fit_lightgbm,
}


def evaluate(
    matrix_rows: Sequence[dict[str, Any]],
    models: Sequence[str],
) -> dict[str, Any]:
    all_cols = _feature_columns(matrix_rows)
    col_domain = {c: _domain_of(c) for c in all_cols}
    y_all = np.array([int(r["yrfi"]) for r in matrix_rows], dtype=float)
    season = np.array([int(r["season"]) for r in matrix_rows])
    dates = np.array([str(r["official_date"]) for r in matrix_rows])

    fold_reports: list[dict[str, Any]] = []
    variant_pool: dict[str, dict[str, list]] = {}

    for ablation, domains in ABLATIONS.items():
        cols = [c for c in all_cols if col_domain[c] in domains]
        x_all = _design(matrix_rows, cols)
        for model_name in models:
            for calibrated in (False, True):
                variant = f"{ablation}:{model_name}{'+sigmoid' if calibrated else ''}"
                variant_pool.setdefault(
                    variant, {"paired": [], "date": [], "y": [], "p": []}
                )

    for train_through, predict_year in PROMOTION_FOLDS:
        tr_mask = season <= train_through
        te_mask = season == predict_year
        y_tr, y_te = y_all[tr_mask], y_all[te_mask]
        dates_te = dates[te_mask]
        base_rate = float(y_tr.mean())
        base_pred = np.full(len(y_te), base_rate)
        base_loss = _log_loss(y_te, base_pred)
        fold_variants: dict[str, Any] = {}

        for ablation, domains in ABLATIONS.items():
            cols = [c for c in all_cols if col_domain[c] in domains]
            x_all = _design(matrix_rows, cols)
            x_tr, x_te = x_all[tr_mask], x_all[te_mask]
            for model_name in models:
                raw_p = MODELS[model_name](x_tr, y_tr, x_te)
                for calibrated in (False, True):
                    variant = (
                        f"{ablation}:{model_name}{'+sigmoid' if calibrated else ''}"
                    )
                    pool = variant_pool[variant]
                    p = raw_p
                    if calibrated:
                        prior_y = np.array(pool["y"], dtype=float)
                        prior_p = np.array(pool["p"], dtype=float)
                        if len(prior_y) >= 50 and len(np.unique(prior_y)) == 2:
                            slope, intercept = _calibration_fit(
                                _to_logit(prior_p), prior_y
                            )
                            p = _apply_calibration(_to_logit(raw_p), slope, intercept)
                    loss = _log_loss(y_te, p)
                    paired = base_loss - loss  # positive => better than climatology
                    fold_variants[variant] = {
                        "log_loss": float(loss.mean()),
                        "brier_score": float(np.mean((p - y_te) ** 2)),
                        "baseline_log_loss": float(base_loss.mean()),
                        "paired_improvement_mean": float(paired.mean()),
                        "ece": _ece(y_te, p),
                        "count": int(len(y_te)),
                    }
                    try:
                        slope_c, intercept_c = _calibration_slope_intercept(y_te, p)
                        fold_variants[variant]["calibration_slope"] = slope_c
                        fold_variants[variant]["calibration_intercept"] = intercept_c
                    except Exception:  # noqa: BLE001
                        fold_variants[variant]["calibration_slope"] = None
                        fold_variants[variant]["calibration_intercept"] = None
                    pool["paired"].extend(paired.tolist())
                    pool["date"].extend(dates_te.tolist())
                    pool["y"].extend(y_te.tolist())
                    pool["p"].extend(p.tolist())
        fold_reports.append(
            {
                "fold_id": f"train_le_{train_through}_predict_{predict_year}",
                "predict_year": predict_year,
                "train_rows": int(tr_mask.sum()),
                "test_rows": int(te_mask.sum()),
                "baseline_log_loss": float(base_loss.mean()),
                "base_rate_train": base_rate,
                "variants": fold_variants,
            }
        )

    # Family-wise error control: the frozen contract predeclared a whole family
    # of ablation x model x calibration variants, so a raw 95% interval on the
    # cherry-picked best variant is not evidence of skill. Apply a Bonferroni
    # correction across the predeclared family and additionally require the
    # per-fold calibration slope/intercept to sit inside the frozen bands.
    family_size = len(variant_pool)
    alpha = 0.05
    corrected_alpha = alpha / family_size
    lo_q, hi_q = 100.0 * alpha / 2.0, 100.0 * (1.0 - alpha / 2.0)
    clo_q = 100.0 * corrected_alpha / 2.0
    chi_q = 100.0 * (1.0 - corrected_alpha / 2.0)

    pooled: dict[str, Any] = {}
    for variant, pool in variant_pool.items():
        paired = np.array(pool["paired"], dtype=float)
        pdate = np.array(pool["date"])
        means = cluster_bootstrap_means(
            paired, pdate, replicates=BOOTSTRAP_REPLICATES, seed=BOOTSTRAP_SEED
        )
        lo, hi = (float(x) for x in np.percentile(means, [lo_q, hi_q]))
        clo, chi = (float(x) for x in np.percentile(means, [clo_q, chi_q]))
        per_fold_pos = all(
            fold["variants"][variant]["paired_improvement_mean"] > 0
            for fold in fold_reports
        )
        calib_ok = all(
            (
                fold["variants"][variant]["calibration_slope"] is not None
                and CALIB_SLOPE_BAND[0]
                <= fold["variants"][variant]["calibration_slope"]
                <= CALIB_SLOPE_BAND[1]
                and CALIB_INTERCEPT_BAND[0]
                <= fold["variants"][variant]["calibration_intercept"]
                <= CALIB_INTERCEPT_BAND[1]
            )
            for fold in fold_reports
        )
        pooled[variant] = {
            "pooled_paired_improvement_mean": float(paired.mean()),
            "ci95_low": lo,
            "ci95_high": hi,
            "family_bonferroni_ci_low": clo,
            "family_bonferroni_ci_high": chi,
            "raw_ci_excludes_zero": bool(lo > 0),
            "family_corrected_ci_excludes_zero": bool(clo > 0),
            "positive_on_every_fold": bool(per_fold_pos),
            "calibration_bands_ok_all_folds": bool(calib_ok),
            "skill_established": bool(per_fold_pos and clo > 0 and calib_ok),
        }

    any_skill = any(v["skill_established"] for v in pooled.values())
    decision = (
        "PREDICTIVE SKILL ESTABLISHED"
        if any_skill
        else "PREDICTIVE SKILL NOT ESTABLISHED"
    )
    best = max(pooled.items(), key=lambda kv: kv[1]["pooled_paired_improvement_mean"])
    return {
        "schema_version": EVAL_SCHEMA_VERSION,
        "contract_name": "NRFI_CORE_V2",
        "models": list(models),
        "ablation_count": len(ABLATIONS),
        "promotion_folds": [list(f) for f in PROMOTION_FOLDS],
        "target": "yrfi (P_FIRST_INNING_RUN); P_NRFI = 1 - P_YRFI",
        "baseline": "expanding_climatology",
        "bootstrap_replicates": BOOTSTRAP_REPLICATES,
        "primary_decision": decision,
        "any_variant_established_skill": any_skill,
        "best_variant": best[0],
        "best_variant_pooled": best[1],
        "folds": fold_reports,
        "pooled": pooled,
        "locked_2025_holdout_accessed": False,
        "wager_decision": "NO QUALIFIED WAGER",
    }


def generate(
    matrix_path: Path, output_dir: Path, models: Sequence[str]
) -> dict[str, Any]:
    rows = load_matrix(matrix_path)
    identity = _identity(rows)
    result = evaluate(rows, models)
    result["matrix_identity"] = identity
    result["matrix_identity_matches_expected"] = identity == EXPECTED_MATRIX_IDENTITY
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "core_v2_evaluation.json").write_bytes(canonical_json_bytes(result))
    summary = {
        "schema_version": "nrfi_core_v2_evaluation_summary.v1",
        "primary_decision": result["primary_decision"],
        "best_variant": result["best_variant"],
        "best_variant_pooled": result["best_variant_pooled"],
        "matrix_identity": identity,
        "matrix_identity_matches_expected": result["matrix_identity_matches_expected"],
        "models": list(models),
        "wager_decision": "NO QUALIFIED WAGER",
        "locked_2025_holdout_accessed": False,
    }
    (output_dir / "core_v2_evaluation_summary.json").write_bytes(
        canonical_json_bytes(summary)
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--models", default="logistic,spline_gam,lightgbm")
    args = parser.parse_args(argv)
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    summary = generate(args.matrix, args.output_dir, models)
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
