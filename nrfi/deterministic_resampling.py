"""Audited deterministic statistical resampling - the ONLY np.random site.

This module is the single, audited home for pseudo-random resampling anywhere
in the package. It exists solely for deterministic, fully-seeded statistical
inference (official-date / cluster bootstrap of paired evaluation scores).

Integrity contract:
  * every public entry point REQUIRES an explicit integer seed - there is no
    unseeded execution path, and a missing/invalid seed raises
    ``SeedRequiredError``;
  * given the same inputs and seed the output is byte-identical (covered by
    ``tests/test_deterministic_resampling.py``);
  * it is NEVER used to fabricate features, fill missing values with defaults,
    synthesize source data, or generate predictions - only to quantify
    uncertainty of already-computed real scores;
  * the ``tests/test_no_fabricated_defaults.py`` integrity gate allowlists ONLY
    this file for ONLY the ``np.random.`` pattern; every other fabrication
    pattern still applies here, and every other module remains fully guarded.
"""

from __future__ import annotations

import numpy as np

__all__ = [
    "SeedRequiredError",
    "seeded_generator",
    "cluster_bootstrap_means",
]


class SeedRequiredError(ValueError):
    """Raised when a resampling routine is invoked without an explicit seed."""


def seeded_generator(seed: int) -> np.random.Generator:
    """Return a deterministic generator; a real integer seed is mandatory."""
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise SeedRequiredError("an explicit integer seed is mandatory")
    return np.random.default_rng(seed)


def cluster_bootstrap_means(
    values: np.ndarray,
    cluster_keys: np.ndarray,
    *,
    replicates: int,
    seed: int,
) -> np.ndarray:
    """Deterministic cluster bootstrap of the mean of ``values``.

    Whole clusters (e.g. official dates) are resampled with replacement to
    preserve within-cluster correlation. Uses cluster sums / sizes so each
    replicate is an O(n_clusters) operation. Fully seeded and deterministic.
    """
    if not isinstance(replicates, int) or isinstance(replicates, bool):
        raise ValueError("replicates must be an integer")
    if replicates <= 0:
        raise ValueError("replicates must be positive")
    rng = seeded_generator(seed)
    values_arr = np.asarray(values, dtype=float)
    keys_arr = np.asarray(cluster_keys)
    if values_arr.shape[0] != keys_arr.shape[0]:
        raise ValueError("values and cluster_keys must have equal length")
    if values_arr.shape[0] == 0:
        raise ValueError("cannot bootstrap an empty sample")
    order = np.argsort(keys_arr, kind="stable")
    values_sorted = values_arr[order]
    keys_sorted = keys_arr[order]
    _, starts = np.unique(keys_sorted, return_index=True)
    groups = np.split(values_sorted, starts[1:])
    sums = np.array([g.sum() for g in groups], dtype=float)
    sizes = np.array([len(g) for g in groups], dtype=float)
    n = len(groups)
    means = np.empty(replicates, dtype=float)
    for b in range(replicates):
        idx = rng.integers(0, n, size=n)
        means[b] = sums[idx].sum() / sizes[idx].sum()
    return means
