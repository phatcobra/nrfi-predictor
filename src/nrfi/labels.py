"""YRFI/NRFI labels with explicit validity rules.

YRFI = 1 when at least one run scores in the first inning (both halves
combined). Rules, applied to each game row:

- The game must be Final.
- If the away team scored >= 1 in the top of the 1st, the label is 1 no
  matter what happened afterwards (the event already occurred).
- If the home team scored >= 1 in the bottom of the 1st, the label is 1.
- A label of 0 requires both halves recorded as 0 runs AND at least five
  recorded innings, so rain-shortened or suspended partial linescores can
  never produce a false NRFI.
- Anything else is invalid and excluded from training/evaluation.

No label is ever inferred; missing linescore data means no label.
"""

from __future__ import annotations

import pandas as pd

LABEL_COLUMN = "yrfi"
VALID_COLUMN = "label_valid"
MIN_INNINGS_FOR_ZERO = 5


def attach_labels(games: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of ``games`` with ``yrfi`` and ``label_valid`` columns."""
    out = games.copy()
    labels: list[float] = []
    valids: list[bool] = []
    for row in out.itertuples():
        label, valid = label_game(
            status=str(getattr(row, "status", "")),
            fi_away=getattr(row, "first_inning_runs_away", None),
            fi_home=getattr(row, "first_inning_runs_home", None),
            innings_recorded=getattr(row, "innings_recorded", 0),
        )
        labels.append(label if label is not None else float("nan"))
        valids.append(valid)
    out[LABEL_COLUMN] = labels
    out[VALID_COLUMN] = valids
    return out


def label_game(
    status: str,
    fi_away: object,
    fi_home: object,
    innings_recorded: object,
) -> tuple[int | None, bool]:
    """Label one game. Returns (label, valid)."""
    if status != "Final":
        return None, False

    away = _as_runs(fi_away)
    home = _as_runs(fi_home)
    innings = _as_runs(innings_recorded) or 0

    if away is not None and away >= 1:
        return 1, True
    if home is not None and home >= 1:
        return 1, True
    if away == 0 and home == 0 and innings >= MIN_INNINGS_FOR_ZERO:
        return 0, True
    return None, False


def _as_runs(value: object) -> int | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
