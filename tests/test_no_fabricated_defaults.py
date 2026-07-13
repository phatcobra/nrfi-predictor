"""CI gate: zero fabricated-data code paths in nrfi/.

Project redline: never fabricate valid-looking output from invalid inputs.
This test greps the package for the patterns that caused the V1/V2 incidents
(random stat fallbacks, invented league-average defaults, zero-imputed rates).
"""
from __future__ import annotations

import re
from pathlib import Path

PKG = Path(__file__).resolve().parents[1] / "nrfi"

FORBIDDEN = [
    (r"np\.random\.", "numpy random fallback (fabricated stats)"),
    (r"random\.uniform\(", "random fallback (fabricated stats)"),
    (r"random\.choice\(", "random fallback (fabricated prediction)"),
    (r"_get_default_", "invented default-stats helper"),
    (r"\.get\(\s*['\"]era['\"]\s*,\s*0\s*\)", "ERA zero-default (0 ERA = fabricated ace)"),
    (r"recommendation", "bet recommendation language (paper-mode redline)"),
    (r"recommended_action", "bet recommendation language (paper-mode redline)"),
]


def test_no_fabricated_defaults():
    violations = []
    for path in sorted(PKG.glob("*.py")):
        text = path.read_text()
        for pattern, why in FORBIDDEN:
            for m in re.finditer(pattern, text):
                line = text[: m.start()].count("\n") + 1
                violations.append(f"{path.name}:{line}: {why} [{pattern}]")
    assert not violations, "fabrication patterns found:\n" + "\n".join(violations)


def test_feature_missing_is_nan_not_default():
    """build_features.py must define NaN as the missing value and never
    import numpy-random."""
    text = (PKG / "build_features.py").read_text()
    assert 'NAN = float("nan")' in text
    assert "np.random" not in text
