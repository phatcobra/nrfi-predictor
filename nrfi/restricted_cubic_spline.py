"""Deterministic restricted (natural) cubic spline basis - Harrell parameterization.

A genuine RESTRICTED cubic spline: cubic between the outer knots and LINEAR in
both tails (natural boundary constraints), unlike a plain truncated-power basis.
For K knots t_1 < ... < t_K it yields K-1 columns (one linear term plus K-2
restricted cubic terms). Knots are taken ONLY from the training fold; nothing is
estimated on the evaluated fold. The basis is a pure deterministic function of
(x, knots), so two calls are byte-identical.

Reference: Harrell, Regression Modeling Strategies, restricted cubic spline
basis. For j = 1..K-2:

    c_j(x) = [ (x-t_j)_+^3
               - (x-t_{K-1})_+^3 (t_K - t_j)/(t_K - t_{K-1})
               + (x-t_K)_+^3     (t_{K-1} - t_j)/(t_K - t_{K-1}) ] / (t_K - t_1)^2

The first column is x itself. The natural constraints force the second and third
derivatives to vanish beyond t_1 and t_K, giving linear tails.
"""

from __future__ import annotations

import numpy as np

__all__ = ["rcs_knots", "rcs_basis", "DEFAULT_KNOT_QUANTILES"]

DEFAULT_KNOT_QUANTILES: tuple[float, ...] = (0.10, 0.35, 0.65, 0.90)


def rcs_knots(
    x_train: np.ndarray,
    quantiles: tuple[float, ...] = DEFAULT_KNOT_QUANTILES,
) -> np.ndarray:
    """Training-fold quantile knots, de-duplicated and sorted ascending."""
    values = np.asarray(x_train, dtype=float)
    values = values[~np.isnan(values)]
    if values.size == 0:
        return np.asarray([], dtype=float)
    knots = np.quantile(values, np.asarray(quantiles, dtype=float))
    return np.unique(knots)


def rcs_basis(x: np.ndarray, knots: np.ndarray) -> np.ndarray:
    """Restricted cubic spline basis (n, K-1) with linear tails.

    With fewer than 3 distinct knots there is no restricted cubic term and the
    basis is the single linear column, so tails are trivially linear.
    """
    x_arr = np.asarray(x, dtype=float)
    knot_arr = np.asarray(knots, dtype=float)
    k = knot_arr.shape[0]
    if k < 3:
        return x_arr.reshape(-1, 1)
    t1 = knot_arr[0]
    t_k = knot_arr[-1]
    t_km1 = knot_arr[-2]
    denom = (t_k - t1) ** 2
    span = t_k - t_km1

    def cube_pos(u: np.ndarray) -> np.ndarray:
        return np.clip(u, 0.0, None) ** 3

    columns: list[np.ndarray] = [x_arr]
    for j in range(k - 2):
        t_j = knot_arr[j]
        term = (
            cube_pos(x_arr - t_j)
            - cube_pos(x_arr - t_km1) * (t_k - t_j) / span
            + cube_pos(x_arr - t_k) * (t_km1 - t_j) / span
        ) / denom
        columns.append(term)
    return np.column_stack(columns)
