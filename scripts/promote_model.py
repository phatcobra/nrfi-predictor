"""Promote one proven candidate to production after human review."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nrfi.config import MODEL_DIR
from nrfi.model_registry import get_model_record, promote_candidate


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument(
        "--confirm",
        required=True,
        choices=["PROMOTE"],
        help="explicit human release gate",
    )
    args = parser.parse_args()

    bundle = MODEL_DIR / f"nrfi_bundle_{args.version}.joblib"
    metadata = MODEL_DIR / f"nrfi_meta_{args.version}.json"
    if not bundle.exists() or not metadata.exists():
        raise SystemExit(
            "candidate artifact is not present locally; promotion refused")
    with metadata.open(encoding="utf-8") as file_handle:
        meta = json.load(file_handle)
    if meta.get("version") != args.version:
        raise SystemExit("candidate metadata version mismatch")

    record = get_model_record(args.version)
    if record is None:
        raise SystemExit("candidate is not registered")
    promote_candidate(args.version)
    print(f"promoted model {args.version} to production")


if __name__ == "__main__":
    main()
