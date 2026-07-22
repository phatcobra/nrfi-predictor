"""Tests for the NRFI_CORE_V2 evaluation harness (deterministic units)."""

from __future__ import annotations

import numpy as np

from nrfi import core_v2_evaluation as e


def test_domain_classification() -> None:
    assert e._domain_of("away_p_career_era") == "pitcher"
    assert e._domain_of("home_p_fi_nrfi_rate") == "pitcher"
    assert e._domain_of("away_t_fi_rpg") == "team"
    assert e._domain_of("park_factor") == "park"
    assert e._domain_of("altitude_ft") == "park"
    assert e._domain_of("away_ctx_starter_rest_days") == "workload"
    assert e._domain_of("home_ctx_park_factor") == "park"
    assert e._domain_of("away_ctx_rest_days") == "schedule_travel"
    assert e._domain_of("home_ctx_travel_miles") == "schedule_travel"


def test_ablations_are_the_predeclared_thirteen() -> None:
    assert len(e.ABLATIONS) == 13
    assert e.ABLATIONS["full_nrfi_core_v2"] == (
        "pitcher",
        "team",
        "park",
        "workload",
        "schedule_travel",
    )


def test_log_loss_and_logit_roundtrip() -> None:
    y = np.array([1.0, 0.0])
    p = np.array([0.9, 0.2])
    loss = e._log_loss(y, p)
    assert loss[0] < loss[1] or loss[0] < 0.2  # confident-correct has low loss
    p2 = np.array([0.3, 0.7, 0.5])
    assert np.allclose(1.0 / (1.0 + np.exp(-e._to_logit(p2))), p2)


def test_cluster_bootstrap_is_deterministic_and_seed_sensitive() -> None:
    rng = np.random.default_rng(0)
    paired = rng.normal(0.001, 0.5, size=400)
    dates = np.array([f"2024-04-{(i % 20) + 1:02d}" for i in range(400)])
    a = e._cluster_bootstrap_means(paired, dates, 500, 20260722)
    b = e._cluster_bootstrap_means(paired, dates, 500, 20260722)
    c = e._cluster_bootstrap_means(paired, dates, 500, 1)
    assert np.array_equal(a, b)  # same seed -> identical
    assert not np.array_equal(a, c)  # different seed -> different
    assert len(a) == 500


def test_design_matrix_null_and_bool() -> None:
    rows = [
        {"features": {"x": 1, "y": None, "z": True}},
        {"features": {"x": 2.5, "z": False}},
    ]
    d = e._design(rows, ["x", "y", "z"])
    assert d[0, 0] == 1.0
    assert np.isnan(d[0, 1])
    assert d[0, 2] == 1.0
    assert d[1, 2] == 0.0
    assert np.isnan(d[1, 1])
