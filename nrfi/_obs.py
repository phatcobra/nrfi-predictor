"""Observability shim: real sentry/loguru in production, no-op stubs in CI.

Keeps offline tests and CI light without letting production silently lose
telemetry: requirements.txt pins the real packages for deploys.
"""
from __future__ import annotations

import atexit
import contextlib
import logging
import os

try:  # pragma: no cover
    import sentry_sdk  # type: ignore
except ImportError:  # CI / offline
    class _SentryStub:
        def init(self, *a, **k): pass
        def capture_exception(self, *a, **k): pass
        def capture_message(self, *a, **k): pass
        @contextlib.contextmanager
        def start_span(self, *a, **k): yield None
        @contextlib.contextmanager
        def start_transaction(self, *a, **k): yield None
    sentry_sdk = _SentryStub()  # type: ignore

try:  # pragma: no cover
    from loguru import logger  # type: ignore
except ImportError:
    logger = logging.getLogger("nrfi")
    if not logger.handlers:
        logging.basicConfig(level=logging.INFO,
                            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

try:  # pragma: no cover
    from posthog import Posthog

    posthog_client = Posthog(
        project_api_key=os.environ.get("POSTHOG_PROJECT_TOKEN", ""),
        host=os.environ.get("POSTHOG_HOST", "https://us.i.posthog.com"),
        enable_exception_autocapture=True,
        disabled=not os.environ.get("POSTHOG_PROJECT_TOKEN", ""),
    )
    atexit.register(posthog_client.shutdown)
except ImportError:  # CI / offline
    class _PostHogStub:
        def capture(self, *a, **k): pass
        def capture_exception(self, *a, **k): pass
        def shutdown(self): pass
        def flush(self): pass
    posthog_client = _PostHogStub()  # type: ignore
