"""Inductive Venn-ABERS calibration (IVAP).

For a calibration set (scores s_i, labels y_i) and a test score s:
  p0 = g0(s) where g0 = isotonic fit on calibration + (s, y=0)
  p1 = g1(s) where g1 = isotonic fit on calibration + (s, y=1)
Merged single probability (log-loss-optimal combination):
  p = p1 / (1 - p0 + p1)
The [p0, p1] interval width is an honest uncertainty diagnostic.

Straightforward per-point refit using sklearn IsotonicRegression. At NRFI
scale (<=16 scoring calls/day; gate evaluation a few thousand points) this
is fast enough; swap in the O(n log n) precomputed variant if it ever isn't.
"""
from __future__ import annotations

import numpy as np
from sklearn.isotonic import IsotonicRegression


class VennAbersCalibrator:
    def __init__(self) -> None:
        self._scores: np.ndarray | None = None
        self._labels: np.ndarray | None = None

    def fit(self, scores: np.ndarray, labels: np.ndarray) -> "VennAbersCalibrator":
        scores = np.asarray(scores, dtype=float)
        labels = np.asarray(labels, dtype=float)
        mask = ~np.isnan(scores)
        if mask.sum() < 50:
            raise ValueError("Venn-ABERS needs >=50 calibration points - refusing")
        self._scores = scores[mask]
        self._labels = labels[mask]
        return self

    def _p(self, s: float, hypothetical_label: float) -> float:
        iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
        xs = np.append(self._scores, s)
        ys = np.append(self._labels, hypothetical_label)
        iso.fit(xs, ys)
        return float(iso.predict([s])[0])

    def predict_interval(self, scores: np.ndarray) -> np.ndarray:
        """(n, 2) array of [p0, p1] per score."""
        if self._scores is None:
            raise RuntimeError("calibrator not fitted - refusing to guess")
        out = np.empty((len(scores), 2), dtype=float)
        for i, s in enumerate(np.asarray(scores, dtype=float)):
            if np.isnan(s):
                out[i] = (np.nan, np.nan)
                continue
            out[i, 0] = self._p(s, 0.0)
            out[i, 1] = self._p(s, 1.0)
        return out

    def predict(self, scores: np.ndarray) -> np.ndarray:
        """Merged single probability per score."""
        iv = self.predict_interval(scores)
        p0, p1 = iv[:, 0], iv[:, 1]
        denom = 1.0 - p0 + p1
        with np.errstate(invalid="ignore"):
            return np.where(denom > 0, p1 / denom, np.nan)

    # -- persistence (arrays only; no pickle needed) -------------------
    def to_arrays(self) -> dict:
        return {"scores": self._scores, "labels": self._labels}

    @classmethod
    def from_arrays(cls, arrays: dict) -> "VennAbersCalibrator":
        obj = cls()
        obj._scores = np.asarray(arrays["scores"], dtype=float)
        obj._labels = np.asarray(arrays["labels"], dtype=float)
        return obj
