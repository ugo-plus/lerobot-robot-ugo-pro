"""Time helpers primarily to ease unit-testing."""

from __future__ import annotations

import time


def now_ms() -> float:
    """Return the current wall-clock time in milliseconds."""

    return time.time() * 1000.0


def monotonic_ms() -> float:
    """Return the monotonic clock in milliseconds."""

    return time.monotonic() * 1000.0
