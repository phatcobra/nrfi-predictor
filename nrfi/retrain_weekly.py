"""Weekly retrain -> gate check -> PR for HUMAN MERGE (never self-deploys).

Gate pass: opens a PR containing the model bundle + gate report via the
GitHub REST API (GH_TOKEN + GITHUB_REPO env). Gate fail: opens an Issue.
No token configured => artifacts + report land locally/registry and the job
logs exactly what a human must do. Nothing ever touches 'production' status
without a human merging the PR and flipping MODEL_STATUS.
"""
from __future__ import annotations

import base64
import json
import os
from datetime import datetime

from nrfi._obs import logger, sentry_sdk
from nrfi.train import NFRIModelTrainer

GH_API = "https://api.github.com"


class GitHubClient:
    def __init__(self) -> None:
        self.token = os.getenv("GH_TOKEN")
        self.repo = os.getenv("GITHUB_REPO")  # e.g. phatcobra/nrfi-predictor

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.repo)

    def _req(self, method: str, path: str, **kw):
        import requests
        r = requests.request(
            method, f"{GH_API}/repos/{self.repo}{path}",
            headers={"Authorization": f"Bearer {self.token}",
                     "Accept": "application/vnd.github+json"},
            timeout=30, **kw)
        r.raise_for_status()
        return r.json()

    def open_candidate_pr(self, version: str, files: dict[str, bytes],
                          report_md: str) -> str:
        main_sha = self._req("GET", "/git/ref/heads/main")["object"]["sha"]
        branch = f"retrain/{version}"
        self._req("POST", "/git/refs",
                  json={"ref": f"refs/heads/{branch}", "sha": main_sha})
        for path, content in files.items():
            self._req("PUT", f"/contents/{path}", json={
                "message": f"retrain {version}: {path}",
                "content": base64.b64encode(content).decode(),
                "branch": branch,
            })
        pr = self._req("POST", "/pulls", json={
            "title": f"[retrain] candidate model {version} - HUMAN MERGE REQUIRED",
            "head": branch, "base": "main", "body": report_md,
        })
        return pr["html_url"]

    def open_issue(self, title: str, body: str) -> str:
        return self._req("POST", "/issues",
                         json={"title": title, "body": body,
                               "labels": ["retrain-gate-failed"]})["html_url"]


def gate_report_md(version: str, report: dict) -> str:
    lines = [
        f"# Retrain candidate `{version}`",
        "",
        "**Merge = deploy on next release. A human must review this gate "
        "report before merging.** Paper-mode redlines apply: this model "
        "emits probabilities and diagnostic edge only.",
        "",
        "## Gate results",
        f"- gates_passed: **{report.get('gates_passed')}**",
        f"- stack OOF log loss: {report.get('stack', {}).get('logloss'):.5f} "
        f"(constant baseline {report.get('baseline_constant', {}).get('logloss'):.5f})",
        f"- stack OOF Brier: {report.get('stack', {}).get('brier'):.5f}",
        "",
        "## Members",
    ]
    for name, m in report.get("members", {}).items():
        lines.append(f"- {name}: logloss {m['logloss']:.5f}, brier {m['brier']:.5f} "
                     f"(n={m['n']})")
    if report.get("ablation"):
        lines.append("\n## Ablation gate")
        for name, a in report["ablation"].items():
            verdict = "SHIPPED" if a["passes_gate"] else "rejected"
            lines.append(f"- {name}: delta logloss {a['delta']:+.5f} -> {verdict}")
    lines.append("\n## Not in this PR\n- 2025 holdout: run "
                 "`python scripts/evaluate_holdout.py --version "
                 f"{version}` ONCE at release.")
    return "\n".join(lines)


def main() -> None:
    trainer = NFRIModelTrainer()
    games = trainer.load_training_data("2015-04-01",
                                       datetime.now().strftime("%Y-%m-%d"))
    X, y, dates, kept = trainer.prepare_features(games)
    report = trainer.train(X, y, dates, kept)
    version = trainer.save_model(trainer.config.MODEL_DIR, metrics=report)
    trainer.register_model(version, report, status="candidate")
    md = gate_report_md(version, report)

    gh = GitHubClient()
    if not report.get("gates_passed"):
        logger.error(f"gate FAILED for {version}; production model untouched")
        if gh.enabled:
            gh.open_issue(f"[retrain] gate failed for {version}", md)
        return

    if gh.enabled:
        model_dir = trainer.config.MODEL_DIR
        files = {}
        for name in (f"nrfi_bundle_{version}.joblib", f"nrfi_meta_{version}.json"):
            with open(os.path.join(model_dir, name), "rb") as fh:
                files[f"models/{name}"] = fh.read()
        files[f"models/gate_report_{version}.md"] = md.encode()
        try:
            url = gh.open_candidate_pr(version, files, md)
            logger.info(f"candidate PR opened (human merge required): {url}")
        except Exception as e:
            sentry_sdk.capture_exception(e)
            logger.error(f"PR creation failed: {e}; candidate stays local + registry")
    else:
        logger.warning(
            "GH_TOKEN/GITHUB_REPO not set. Candidate saved locally + registered "
            f"as 'candidate'. HUMAN: commit models/nrfi_bundle_{version}.joblib "
            "+ meta + this gate report on a branch and open the PR yourself.")
        print(md)


if __name__ == "__main__":
    main()
