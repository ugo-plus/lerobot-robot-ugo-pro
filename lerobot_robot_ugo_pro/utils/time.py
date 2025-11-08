"""Small helpers around time handling to keep UDP packets in sync."""

from __future__ import annotations

from datetime import datetime, timezone


def utc_now_ms() -> int:
    """Return the current UTC timestamp in milliseconds."""
    return int(datetime.now(tz=timezone.utc).timestamp() * 1000)
