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


def test_no_asset_is_admitted_and_only_statsapi_development_is_authorized():
    catalog = _load("data_contracts")
    statuses = Counter(asset["admission_status"] for asset in catalog["assets"])
    assert statuses == {"unadmitted": 5, "quarantined": 6, "rejected": 1}
    assert catalog["admission_policy"]["new_data_acquisition_authorized"] is False
    assert catalog["admission_policy"]["locked_evaluation_access_authorized"] is False
    assert catalog["admission_policy"]["private_data_publication_authorized"] is False

    plan = _load("acquisition_plan")
    assert plan["authorized"] is False
    vertical_slice = plan["bounded_development_vertical_slice"]
    assert vertical_slice == {
        "authorized": True,
        "authorization_scope": (
            "internal_development_normalization_testing_and_"
            "chronological_evaluation_only"
        ),
        "credential_action": "prohibited",
        "end_date": "2024-05-31",
        "locked_holdout_access": "prohibited",
        "network_action": "unauthenticated_http_get_official_mlb_statsapi_only",
        "no_cost_gate": "passed_no_paid_service_authorized",
        "no_raw_payload_redistribution": True,
        "output_policy": (
            "normalized_derived_records_checksums_source_references_and_timestamps_only"
        ),
        "payment_action": "prohibited",
        "pitcher_feature_policy": (
            "actual_starters_postgame_attribution_only_no_pregame_backfill"
        ),
        "prohibited_domains": [
            "aws",
            "injuries",
            "lineups",
            "market_prices",
            "production_deployment",
            "sportsbook_connections",
            "umpires",
            "wagering",
            "weather",
        ],
        "quarantined_asset_access": "prohibited",
        "source": "https://statsapi.mlb.com",
        "start_date": "2024-04-01",
        "subscription_action": "prohibited",
        "vertical_slice_id": "nrfi.real_vertical_slice.2024-04-01_2024-05-31.v1",
    }
    multi_season = plan["multi_season_development_engine"]
    assert multi_season["authorized"] is True
    assert multi_season["development_seasons"] == [2021, 2022, 2023, 2024]
    assert multi_season["source"] == "https://statsapi.mlb.com"
    assert multi_season["network_action"] == (
        "unauthenticated_http_get_official_mlb_statsapi_only"
    )
    assert multi_season["deterministic_replay_required"] is True
    assert multi_season["locked_holdout_access"] == "prohibited"
    assert multi_season["quarantined_asset_access"] == "prohibited"
    assert multi_season["credential_action"] == "prohibited"
    assert multi_season["payment_action"] == "prohibited"
    assert multi_season["subscription_action"] == "prohibited"
    assert "market_prices" in multi_season["prohibited_domains"]
    assert "wagering" in multi_season["prohibited_domains"]
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
