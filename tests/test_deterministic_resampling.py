"""Tests for the audited deterministic resampling module."""

from __future__ import annotations

import numpy as np
import pytest

from nrfi import deterministic_resampling as dr


def _sample() -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(7)  # test-only fixture generator
    values = rng.normal(0.001, 0.5, size=600)
    keys = np.array([f"2024-04-{(i % 25) + 1:02d}" for i in range(600)])
    return values, keys


def test_seed_is_mandatory() -> None:
    values, keys = _sample()
    with pytest.raises(dr.SeedRequiredError):
        dr.cluster_bootstrap_means(values, keys, replicates=100, seed=None)  # type: ignore[arg-type]
    with pytest.raises(dr.SeedRequiredError):
        dr.cluster_bootstrap_means(values, keys, replicates=100, seed=True)  # type: ignore[arg-type]
    with pytest.raises(dr.SeedRequiredError):
        dr.seeded_generator("nope")  # type: ignore[arg-type]


def test_byte_identical_replay_same_seed() -> None:
    values, keys = _sample()
    a = dr.cluster_bootstrap_means(values, keys, replicates=500, seed=20260722)
    b = dr.cluster_bootstrap_means(values, keys, replicates=500, seed=20260722)
    assert a.tobytes() == b.tobytes()  # byte-identical replay
    assert len(a) == 500


def test_seed_sensitive() -> None:
    values, keys = _sample()
    a = dr.cluster_bootstrap_means(values, keys, replicates=500, seed=20260722)
    c = dr.cluster_bootstrap_means(values, keys, replicates=500, seed=1)
    assert not np.array_equal(a, c)


def test_rejects_bad_inputs() -> None:
    values, keys = _sample()
    with pytest.raises(ValueError):
        dr.cluster_bootstrap_means(values, keys, replicates=0, seed=1)
    with pytest.raises(ValueError):
        dr.cluster_bootstrap_means(values[:10], keys[:5], replicates=10, seed=1)
    with pytest.raises(ValueError):
        dr.cluster_bootstrap_means(np.array([]), np.array([]), replicates=10, seed=1)


def test_cluster_resampling_preserves_mean_scale() -> None:
    values = np.concatenate([np.zeros(50), np.ones(50)])
    keys = np.array([f"d{i}" for i in range(100)])
    means = dr.cluster_bootstrap_means(values, keys, replicates=2000, seed=5)
    # bootstrap mean distribution should centre near the sample mean (0.5)
    assert abs(float(means.mean()) - 0.5) < 0.05
