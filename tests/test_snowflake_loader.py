"""Offline tests for Snowflake query dispatch without live credentials."""
from __future__ import annotations

from nrfi.snowflake_loader import execute_query_df


class FakeCursor:
    description = [("GAME_ID",), ("GAME_DATE",)]

    def __init__(self):
        self.executed = None
        self.closed = False

    def execute(self, query, params):
        self.executed = (query, params)

    def fetchall(self):
        return [("1", "2024-04-01")]

    def close(self):
        self.closed = True


class FakeRawConnection:
    def __init__(self):
        self.cursor_instance = FakeCursor()
        self.closed = False

    def cursor(self):
        return self.cursor_instance

    def close(self):
        self.closed = True


class FakeEngine:
    def __init__(self):
        self.raw = FakeRawConnection()

    def raw_connection(self):
        return self.raw


def test_positional_percent_s_query_uses_dbapi_cursor():
    engine = FakeEngine()
    frame = execute_query_df(
        "SELECT game_id, game_date FROM games WHERE game_date = %s",
        ["2024-04-01"],
        engine=engine,
    )
    assert engine.raw.cursor_instance.executed == (
        "SELECT game_id, game_date FROM games WHERE game_date = %s",
        ("2024-04-01",),
    )
    assert engine.raw.cursor_instance.closed is True
    assert engine.raw.closed is True
    assert frame.columns.tolist() == ["game_id", "game_date"]
    assert frame.iloc[0]["game_id"] == "1"
