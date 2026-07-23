"""Tests for the restricted (natural) cubic spline basis."""

from __future__ import annotations

import numpy as np

from nrfi import restricted_cubic_spline as rcs


def _knots() -> np.ndarray:
    rng = np.random.default_rng(0)  # test-only fixture generator
    x = rng.normal(0.0, 1.0, size=5000)
    return rcs.rcs_knots(x)


def test_column_count_is_k_minus_one() -> None:
    knots = _knots()
    assert knots.shape[0] == 4  # four distinct quantile knots
    basis = rcs.rcs_basis(np.linspace(-3, 3, 50), knots)
    assert basis.shape == (50, 3)  # K-1 columns


def test_linear_tails_second_difference_is_zero() -> None:
    knots = _knots()
    lo, hi = knots[0], knots[-1]
    # points strictly beyond both boundary knots, equally spaced
    right = np.array([hi + 1.0, hi + 2.0, hi + 3.0, hi + 4.0])
    left = np.array([lo - 4.0, lo - 3.0, lo - 2.0, lo - 1.0])
    for pts in (left, right):
        basis = rcs.rcs_basis(pts, knots)
        # each column must be affine in x beyond the boundary knots
        second_diff = np.diff(basis, n=2, axis=0)
        assert np.allclose(second_diff, 0.0, atol=1e-9)


def test_basis_is_cubic_between_knots() -> None:
    knots = _knots()
    mid = np.linspace(knots[0], knots[-1], 40)
    basis = rcs.rcs_basis(mid, knots)
    # interior curvature must be non-trivial (not linear everywhere)
    second_diff = np.diff(basis[:, 1:], n=2, axis=0)
    assert np.abs(second_diff).max() > 1e-6


def test_replay_byte_identical() -> None:
    knots = _knots()
    x = np.linspace(-2, 2, 101)
    a = rcs.rcs_basis(x, knots)
    b = rcs.rcs_basis(x, knots)
    assert a.tobytes() == b.tobytes()


def test_knots_are_training_only_and_deterministic() -> None:
    x = np.array([0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0])
    k1 = rcs.rcs_knots(x)
    k2 = rcs.rcs_knots(x)
    assert np.array_equal(k1, k2)
    expected = np.unique(np.quantile(x, [0.10, 0.35, 0.65, 0.90]))
    assert np.allclose(k1, expected)
    # NaNs in the (training) input are ignored, not imputed
    xn = np.concatenate([x, [np.nan, np.nan]])
    assert np.allclose(rcs.rcs_knots(xn), expected)


def test_degenerate_knots_fall_back_to_linear() -> None:
    x = np.zeros(100)  # all identical -> < 3 distinct knots
    knots = rcs.rcs_knots(x)
    basis = rcs.rcs_basis(np.array([1.0, 2.0, 3.0]), knots)
    assert basis.shape[1] == 1  # single linear column
