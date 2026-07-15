"""Temporary probe proving that the GitHub release gate fails closed."""


def test_ci_release_gate_controlled_failure():
    assert False, "intentional CI release-gate failure probe"
