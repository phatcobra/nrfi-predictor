"""Weekly retrain -> evidence gates -> candidate PR for human release.

The locked holdout is never included in weekly training. A failed candidate is
registered as rejected but no loadable bundle is written, preventing serving
from accidentally selecting a failed retrain as the latest model.
"""
from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timezone

from nrfi._obs import logger, sentry_sdk
from nrfi.train import NFRIModelTrainer

GH_API = "https://api.github.com"


class GitHubClient:
    def __init__(self) -> None:
        self.token = os.getenv("GH_TOKEN")
        self.repo = os.getenv("GITHUB_REPO")

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.repo)

    def _req(self, method: str, path: str, **kwargs):
        import requests

        response = requests.request(
            method,
            f"{GH_API}/repos/{self.repo}{path}",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30,
            **kwargs,
        )
        response.raise_for_status()
        return response.json()

    def open_candidate_pr(self, version: str, files: dict[str, bytes],
                          report_md: str) -> str:
        main_sha = self._req("GET", "/git/ref/heads/main")["object"]["sha"]
        branch = f"retrain/{version}"
        self._req("POST", "/git/refs", json={
            "ref": f"refs/heads/{branch}", "sha": main_sha})
        for path, content in files.items():
            self._req("PUT", f"/contents/{path}", json={
                "message": f"retrain {version}: {path}",
                "content": base64.b64encode(content).decode(),
                "branch": branch,
            })
        pull_request = self._req("POST", "/pulls", json={
            "title": f"[retrain] candidate model {version} - HUMAN MERGE REQUIRED",
            "head": branch,
            "base": "main",
            "body": report_md,
        })
        return pull_request["html_url"]

    def open_issue(self, title: str, body: str) -> str:
        return self._req("POST", "/issues", json={
            "title": title,
            "body": body,
            "labels": ["retrain-gate-failed"],
        })["html_url"]


def gate_report_md(version: str, report: dict) -> str:
    stack = report.get("stack", {})
    baseline = report.get("baseline_constant", {})
    lines = [
        f"# Retrain candidate `{version}`",
        "",
        "**Human release review required.** This artifact emits calibrated "
        "probabilities and diagnostic market comparisons only.",
        "",
        "## Evidence boundaries",
        f"- training_start: `{report.get('training_start')}`",
        f"- training_end: `{report.get('training_end')}`",
        f"- locked_holdout_start: `{report.get('holdout_start')}`",
        f"- locked_holdout_end: `{report.get('holdout_end')}`",
        "",
        "## Gate results",
        f"- gates_passed: **{report.get('gates_passed')}**",
        f"- stack OOF log loss: {stack.get('logloss')}",
        f"- constant baseline log loss: {baseline.get('logloss')}",
        f"- stack OOF Brier: {stack.get('brier')}",
        "",
        "## Members",
    ]
    for name, metrics in report.get("members", {}).items():
        lines.append(
            f"- {name}: logloss {metrics['logloss']:.5f}, "
            f"brier {metrics['brier']:.5f} (n={metrics['n']})")
    if report.get("ablation"):
        lines.append("\n## Ablation gate")
        for name, ablation in report["ablation"].items():
            verdict = "SHIPPED" if ablation["passes_gate"] else "rejected"
            lines.append(
                f"- {name}: delta logloss {ablation['delta']:+.5f} -> {verdict}")
    lines.extend([
        "",
        "## Release holdout",
        "Run the locked holdout evaluator once for this exact candidate before "
        "changing its registry status to production.",
    ])
    return "\n".join(lines)


def main() -> None:
    trainer = NFRIModelTrainer()
    games = trainer.load_training_data(
        trainer.config.TRAIN_START_DATE, trainer.config.TRAIN_END_DATE)
    X, y, dates, kept = trainer.prepare_features(games)
    report = trainer.train(X, y, dates, kept)
    report.update({
        "training_start": trainer.config.TRAIN_START_DATE,
        "training_end": trainer.config.TRAIN_END_DATE,
        "holdout_start": trainer.config.HOLDOUT_START_DATE,
        "holdout_end": trainer.config.HOLDOUT_END_DATE,
    })
    version = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    markdown = gate_report_md(version, report)
    github = GitHubClient()

    if not report.get("gates_passed"):
        trainer.register_model(version, report, status="rejected")
        logger.error(f"gate FAILED for {version}; no model bundle was written")
        if github.enabled:
            github.open_issue(f"[retrain] gate failed for {version}", markdown)
        else:
            print(markdown)
        return

    trainer.save_model(trainer.config.MODEL_DIR, version=version, metrics=report)
    trainer.register_model(version, report, status="candidate")

    if github.enabled:
        model_dir = trainer.config.MODEL_DIR
        files: dict[str, bytes] = {}
        for name in (
            f"nrfi_bundle_{version}.joblib",
            f"nrfi_meta_{version}.json",
        ):
            with open(os.path.join(model_dir, name), "rb") as file_handle:
                files[f"models/{name}"] = file_handle.read()
        files[f"models/gate_report_{version}.md"] = markdown.encode()
        try:
            url = github.open_candidate_pr(version, files, markdown)
            logger.info(f"candidate PR opened: {url}")
        except Exception as exc:
            sentry_sdk.capture_exception(exc)
            logger.error(
                f"candidate PR creation failed: {exc}; artifact remains candidate")
    else:
        logger.warning(
            "GH_TOKEN/GITHUB_REPO not set. Candidate saved and registered, but "
            "cannot be released until the bundle, metadata, and gate report are "
            "reviewed and merged manually.")
        print(markdown)


if __name__ == "__main__":
    main()
