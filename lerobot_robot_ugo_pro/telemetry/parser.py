"""Streaming parser for the MCU CSV telemetry format."""

from __future__ import annotations

import math
import threading
import time
from typing import Sequence

from .frame import TelemetryFrame


class JointStateBuffer:
    """Thread-safe holder for the latest telemetry frame."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._frame: TelemetryFrame | None = None

    def update(self, frame: TelemetryFrame) -> None:
        with self._lock:
            self._frame = frame

    def latest(self) -> TelemetryFrame | None:
        with self._lock:
            return self._frame


class TelemetryParser:
    """Parse bytes coming from the UDP socket into :class:`TelemetryFrame` instances."""

    def __init__(self, *, buffer: JointStateBuffer | None = None):
        self.buffer = buffer or JointStateBuffer()
        self.partial_buf = ""
        self.latest_ids: tuple[int, ...] = ()
        self._current_lines: dict[str, list[str]] = {}
        self._raw_lines: list[str] = []

    def feed(self, payload: bytes) -> list[TelemetryFrame]:
        """Feed new bytes and return zero or more completed frames."""

        text = payload.decode("utf-8", errors="ignore")
        text = self.partial_buf + text
        lines = text.splitlines()
        if text and not text.endswith("\n"):
            self.partial_buf = lines.pop() if lines else text
        else:
            self.partial_buf = ""

        frames: list[TelemetryFrame] = []
        for line in lines:
            frame = self._process_line(line.strip())
            if frame:
                frames.append(frame)
        return frames

    def flush(self) -> TelemetryFrame | None:
        """Force completion of the current frame if possible."""

        return self._finalize_frame()

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    def _process_line(self, line: str) -> TelemetryFrame | None:
        if not line:
            return None
        parts = [part.strip() for part in line.split(",")]
        key = parts[0]

        if key == "vsd":
            frame = self._finalize_frame()
            self._current_lines = {"vsd": parts[1:]}
            self._raw_lines = [line]
            return frame

        if not self._current_lines:
            # Ignore until we encounter the next vsd header.
            return None

        self._current_lines[key] = parts[1:]
        self._raw_lines.append(line)
        return None


    def _finalize_frame(self) -> TelemetryFrame | None:
        if not self._current_lines:
            return None

        lines = self._current_lines
        self._current_lines = {}
        raw_lines = tuple(self._raw_lines)
        self._raw_lines = []

        ids = self._parse_ids(lines.get("id", []))
        if not ids:
            return None
        self.latest_ids = ids

        missing_fields: list[str] = []
        angles = self._parse_numeric_series(ids, lines.get("agl"), scale=0.1)
        if not angles:
            missing_fields.append("agl")

        velocities = self._parse_numeric_series(ids, lines.get("vel"))
        if not velocities:
            missing_fields.append("vel")

        currents = self._parse_numeric_series(ids, lines.get("cur"))
        if not currents:
            missing_fields.append("cur")
        commanded = self._parse_numeric_series(ids, lines.get("obj"), scale=0.1)
        if not commanded:
            missing_fields.append("obj")

        vsd_interval, vsd_read, vsd_write = self._parse_vsd(lines.get("vsd", []))

        health = "ok"
        if not angles:
            health = "missing_agl"
        elif missing_fields and health == "ok":
            health = "partial"

        frame = TelemetryFrame(
            timestamp=time.time(),
            joint_ids=ids,
            angles_deg=angles,
            velocities_raw=velocities,
            currents_raw=currents,
            commanded_deg=commanded,
            vsd_interval_ms=vsd_interval,
            vsd_read_ms=vsd_read,
            vsd_write_ms=vsd_write,
            missing_fields=tuple(missing_fields),
            raw_lines=raw_lines,
            health=health,
        )
        self.buffer.update(frame)
        return frame

    @staticmethod
    def _parse_ids(values: Sequence[str] | None) -> tuple[int, ...]:
        if not values:
            return ()
        ids: list[int] = []
        for value in values:
            try:
                ids.append(int(value))
            except ValueError:
                continue
        return tuple(ids)

    @staticmethod
    def _parse_numeric_series(
        joint_ids: Sequence[int], values: Sequence[str] | None, *, scale: float = 1.0
    ) -> dict[int, float]:
        if not values:
            return {}
        series: dict[int, float] = {}
        for joint_id, raw in zip(joint_ids, values):
            if raw == "":
                series[joint_id] = math.nan
                continue
            try:
                series[joint_id] = float(raw) * scale
            except ValueError:
                series[joint_id] = math.nan
        return series

    @staticmethod
    def _parse_vsd(values: Sequence[str]) -> tuple[float | None, float | None, float | None]:
        interval = read = write = None
        for value in values:
            name, _, remainder = value.partition(":")
            try:
                number_str, _, _ = remainder.partition("[")
                numeric = float(number_str)
            except ValueError:
                continue
            if name == "interval":
                interval = numeric
            elif name == "read":
                read = numeric
            elif name == "write":
                write = numeric
        return interval, read, write
