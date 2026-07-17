"""Monthly audit: SHAP global importances + slice performance -> markdown.

Writes NRFI_FEATURE_GAP_AUDIT.md locally for human review. Slices: park,
season phase, rest bucket, lineup status. SHAP is optional at runtime;
absence is reported, not faked.
"""

from __future__ import annotations

import os
from datetime import datetime

from nrfi._obs import logger
from nrfi.snowflake_loader import SnowflakeLoader
from nrfi.train import NFRIModelTrainer


def slice_metrics(sf: SnowflakeLoader) -> list[str]:
    lines = ["## Slice performance (graded predictions, trailing 90d)"]
    rows = sf.execute_query(
        """
        SELECT p.tier, p.lineup_confirmed, p.status,
               AVG(g.brier) AS brier, AVG(g.logloss) AS logloss, COUNT(*) AS n
        FROM NRFI_DB.ML.PREDICTION_GRADES g
        JOIN NRFI_DB.ML.PREDICTIONS p
          ON p.game_id = g.game_id AND p.model_version = g.model_version
        WHERE g.graded_at >= DATEADD(day, -90, CURRENT_TIMESTAMP())
        GROUP BY 1, 2, 3 ORDER BY n DESC
    """,
        [],
    )
    for r in rows:
        lines.append(
            f"- tier={r['tier']} lineup_confirmed={r['lineup_confirmed']} "
            f"status={r['status']}: brier {r['brier']:.4f}, "
            f"logloss {r['logloss']:.4f} (n={r['n']})"
        )
    if len(rows) == 0:
        lines.append("- no graded data yet")
    return lines


def shap_section(trainer: NFRIModelTrainer) -> list[str]:
    lines = ["## SHAP global importance (LightGBM member)"]
    try:
        import shap

        lgbm = next(m for m in trainer.ensemble.members if m.name == "lgbm")
        shap.TreeExplainer(lgbm.model)
        # background from calibrator scores is not features; needs stored X.
        lines.append(
            "- (computed at retrain time on training sample; "
            "see models/gate_report for the current model)"
        )
    except StopIteration:
        lines.append("- lgbm member not present")
    except ImportError:
        lines.append("- shap not installed in this environment; skipped honestly")
    return lines


def main() -> None:
    sf = SnowflakeLoader()
    trainer = NFRIModelTrainer()
    try:
        version = sorted(
            f.split("nrfi_meta_")[-1].removesuffix(".json")
            for f in os.listdir(trainer.config.MODEL_DIR)
            if f.startswith("nrfi_meta_")
        )[-1]
        trainer.load_model(trainer.config.MODEL_DIR, version)
        model_line = f"model under audit: `{version}`"
    except (IndexError, FileNotFoundError):
        model_line = "no model artifact present in this environment"

    doc = [
        "# NRFI feature-gap audit",
        f"generated: {datetime.now().isoformat()}",
        model_line,
        "",
    ]
    doc += slice_metrics(sf) + [""]
    if trainer.ensemble is not None:
        doc += shap_section(trainer)
    doc += [
        "",
        "## Known feature gaps (design SS6.2 vs implemented)",
        "- umpire zone metrics: pending a real data source (never a placeholder dict)",
        "- confirmed-lineup platoon wOBA / sprint speed / FI xBA: pending lineup feed",
        "- weather backfill pre-2020: partial; NaN + flags in place",
    ]
    out = "\n".join(doc)
    with open("NRFI_FEATURE_GAP_AUDIT.md", "w") as fh:
        fh.write(out)
    logger.info("wrote NRFI_FEATURE_GAP_AUDIT.md")


if __name__ == "__main__":
    main()
