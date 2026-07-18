"""PostHog analytics client for nrfi-predictor."""
from __future__ import annotations

import atexit
import os

from posthog import Posthog

_client: Posthog | None = None

SYSTEM_DISTINCT_ID = "nrfi-predictor-system"


def get_client() -> Posthog | None:
    return _client


def init() -> None:
    global _client
    token = os.environ.get("POSTHOG_PROJECT_TOKEN", "")
    host = os.environ.get("POSTHOG_HOST", "https://us.i.posthog.com")
    if not token:
        return
    _client = Posthog(
        project_api_key=token,
        host=host,
        enable_exception_autocapture=True,
    )
    atexit.register(_client.shutdown)


def capture(event: str, properties: dict | None = None,
            distinct_id: str = SYSTEM_DISTINCT_ID) -> None:
    if _client is None:
        return
    _client.capture(distinct_id=distinct_id, event=event,
                    properties=properties or {})


def shutdown() -> None:
    if _client is not None:
        _client.shutdown()
