"""Property checks for stable fail-closed guard boundaries."""

from hypothesis import given, strategies as st

from nrfi.config import ODDS_MAX_AGE_SECONDS
from nrfi.guards import odds_fresh


@given(st.one_of(st.none(), st.integers()))
def test_odds_fresh_matches_the_closed_valid_interval(age_seconds):
    expected = age_seconds is not None and 0 <= age_seconds <= ODDS_MAX_AGE_SECONDS
    assert odds_fresh(age_seconds) is expected
