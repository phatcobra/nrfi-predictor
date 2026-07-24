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
    (
        r"\.get\(\s*['\"]era['\"]\s*,\s*0\s*\)",
        "ERA zero-default (0 ERA = fabricated ace)",
    ),
    (r"recommendation", "bet recommendation language (paper-mode redline)"),
    (r"recommended_action", "bet recommendation language (paper-mode redline)"),
]

# Narrow, audited allowlist: filename -> {patterns exempted for THAT file only}.
# The sole entry is the audited, fully-seeded resampling module, which is the
# single permitted home for ``np.random`` (deterministic cluster bootstrap of
# real scores; see its docstring). Every OTHER pattern still applies to it, and
# every OTHER module remains fully guarded against ``np.random``.
ALLOWLIST: dict[str, set[str]] = {
    "deterministic_resampling.py": {r"np\.random\."},
}


def test_no_fabricated_defaults():
    violations = []
    for path in sorted(PKG.glob("*.py")):
        text = path.read_text()
        exempt = ALLOWLIST.get(path.name, set())
        for pattern, why in FORBIDDEN:
            if pattern in exempt:
                continue
            for m in re.finditer(pattern, text):
                line = text[: m.start()].count("\n") + 1
                violations.append(f"{path.name}:{line}: {why} [{pattern}]")
    assert not violations, "fabrication patterns found:\n" + "\n".join(violations)


def test_allowlist_is_narrow():
    """The np.random allowlist must stay limited to the audited module."""
    assert set(ALLOWLIST) == {"deterministic_resampling.py"}
    assert ALLOWLIST["deterministic_resampling.py"] == {r"np\.random\."}


def test_feature_missing_is_nan_not_default():
    """build_features.py must define NaN as the missing value and never
    import numpy-random."""
    text = (PKG / "build_features.py").read_text()
    assert 'NAN = float("nan")' in text
    assert "np.random" not in text
