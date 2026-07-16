"""Offline consistency checks for the Phase 2 contract package."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

PHASE2 = Path(__file__).resolve().parents[1] / "docs" / "phase2"
REPORT_NAMES = (
    "acquisition_plan",
    "coverage_report",
    "data_gap_report",
    "rejected_assets_report",
    "reuse_plan",
    "schema_report",
)


def _load(name: str) -> dict:
    with (PHASE2 / f"{name}.json").open(encoding="utf-8") as handle:
        return json.load(handle)


def test_phase2_catalog_and_reports_are_reconciled():
    catalog = _load("data_contracts")
    asset_ids = catalog["asset_ids"]
    contract_ids = catalog["contract_ids"]
    assert len(asset_ids) == len(set(asset_ids)) == 12
    assert len(contract_ids) == len(set(contract_ids)) == 19
    assert sorted(asset_ids) == sorted(asset["asset_id"] for asset in catalog["assets"])
    assert sorted(contract_ids) == sorted(
        contract["id"] for contract in catalog["contracts"]
    )

    for name in REPORT_NAMES:
        report = _load(name)
        assert report["asset_ids"] == asset_ids
        assert report["contract_ids"] == contract_ids
        assert report["generated_from"] == catalog["generated_from"]


def test_every_asset_attribute_has_exactly_one_evidence_state():
    catalog = _load("data_contracts")
    required = set(catalog["required_asset_attributes"])
    assert len(required) == 25
    for asset in catalog["assets"]:
        covered = list(asset["known"])
        covered.extend(
            attribute
            for record in asset["unknown"]
            for attribute in record["attributes"]
        )
        covered.extend(
            attribute
            for record in asset["not_applicable"]
            for attribute in record["attributes"]
        )
        assert set(covered) == required, asset["asset_id"]
        assert all(count == 1 for count in Counter(covered).values()), asset["asset_id"]


def test_contract_time_roles_assets_and_gaps_fail_closed():
    catalog = _load("data_contracts")
    asset_ids = set(catalog["asset_ids"])
    time_roles = set(catalog["time_roles"])
    gaps = _load("data_gap_report")
    gap_ids = {record["gap_id"] for record in gaps["gap_records"]}
    gap_ids.update(record["gap_id"] for record in gaps["resolved_evidence_gaps"])

    for contract in catalog["contracts"]:
        assert set(contract["candidate_asset_ids"]) <= asset_ids, contract["id"]
        assert set(contract["gap_ids"]) <= gap_ids, contract["id"]
        assert set(contract["time_fields"]) == time_roles, contract["id"]
        for role, column in contract["time_fields"].items():
            has_gap = role in contract["time_gap_codes"]
            assert (column is None) == has_gap, (contract["id"], role)


def test_no_asset_is_admitted_and_acquisition_is_unauthorized():
    catalog = _load("data_contracts")
    statuses = Counter(asset["admission_status"] for asset in catalog["assets"])
    assert statuses == {"unadmitted": 5, "quarantined": 6, "rejected": 1}
    assert catalog["admission_policy"]["new_data_acquisition_authorized"] is False
    assert catalog["admission_policy"]["locked_evaluation_access_authorized"] is False
    assert catalog["admission_policy"]["private_data_publication_authorized"] is False

    plan = _load("acquisition_plan")
    assert plan["authorized"] is False
    assert len(plan["proposals"]) == 7
    for proposal in plan["proposals"]:
        assert proposal["authorized"] is False
        for field in (
            "credential_action",
            "network_action",
            "payment_action",
            "subscription_action",
        ):
            assert proposal[field] == "prohibited"


def test_phase2_paths_are_public_aliases_only():
    for path in (PHASE2.parent.parent / "DATA_CONTRACTS.md", *PHASE2.glob("*.json")):
        content = path.read_text(encoding="utf-8")
        assert "C:\\Users\\" not in content
        assert "Users\\ameis" not in content
        assert "Documents\\Codex" not in content
