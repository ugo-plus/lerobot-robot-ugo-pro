"""Streaming parser for the MCU -> PC CSV telemetry feed."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from ..utils import utc_now_ms
from .frame import TelemetryFrame


_MANDATORY_SERIES = ("agl",)
_OPTIONAL_SERIES = ("vel", "cur", "onj_agl")


def _clean_value(raw: str) -> str:
    return raw.strip()


def _parse_ids(values: Sequence[str]) -> Tuple[int, ...]:
    ids: List[int] = []
    for value in values:
        value = _clean_value(value)
        if not value:
            continue
        try:
            ids.append(int(float(value)))
        except ValueError:
            continue
    return tuple(ids)


def _parse_metadata(values: Sequence[str]) -> Dict[str, str]:
    metadata: Dict[str, str] = {}
    for value in values:
        value = _clean_value(value)
        if not value:
            continue
        if ":" in value:
            key, raw_val = value.split(":", 1)
            metadata[key.strip()] = raw_val.strip()
    return metadata


def _parse_numeric_series(
    ids: Sequence[int],
    values: Sequence[str],
    *,
    transform,
    default,
) -> Tuple:
    data = []
    for idx in range(len(ids)):
        if idx < len(values):
            raw = _clean_value(values[idx])
            if raw:
                try:
                    data.append(transform(raw))
                    continue
                except ValueError:
                    pass
        data.append(default)
    return tuple(data)


@dataclass
class _FrameBuilder:
    ids: Tuple[int, ...] = ()
    raw_series: Dict[str, Tuple[str, ...]] = None  # type: ignore[assignment]
    metadata: Dict[str, str] = None  # type: ignore[assignment]
    last_vsd_ts_ms: int = 0

    def __post_init__(self) -> None:
        self.raw_series = {}
        self.metadata = {}

    def reset(self) -> None:
        self.ids = ()
        self.raw_series = {}
        self.metadata = {}
        self.last_vsd_ts_ms = 0

    def can_build(self) -> bool:
        return bool(self.ids) and "agl" in self.raw_series and self.last_vsd_ts_ms > 0

    def consume_line(self, line: str) -> Optional[TelemetryFrame]:
        line = line.strip()
        if not line:
            return None

        parts = [segment for segment in line.split(",")]
        head = parts[0].strip() if parts else ""
        values = tuple(part.strip() for part in parts[1:])

        if head == "vsd":
            frame = self.build_if_ready()
            self.metadata = _parse_metadata(values)
            self.last_vsd_ts_ms = utc_now_ms()
            self.raw_series = {}
            return frame

        if head == "id":
            ids = _parse_ids(values)
            if ids:
                self.ids = ids
            return None

        if head in _MANDATORY_SERIES or head in _OPTIONAL_SERIES:
            self.raw_series[head] = values
        return None

    def build_if_ready(self) -> Optional[TelemetryFrame]:
        if not self.ids:
            return None
        if "agl" not in self.raw_series:
            return None

        ids = self.ids
        angles = _parse_numeric_series(
            ids,
            self.raw_series.get("agl", ()),
            transform=lambda raw: float(raw) / 10.0,
            default=math.nan,
        )
        velocities = _parse_numeric_series(
            ids,
            self.raw_series.get("vel", ()),
            transform=lambda raw: int(float(raw)),
            default=0,
        )
        currents = _parse_numeric_series(
            ids,
            self.raw_series.get("cur", ()),
            transform=lambda raw: int(float(raw)),
            default=0,
        )
        targets = _parse_numeric_series(
            ids,
            self.raw_series.get("onj_agl", ()),
            transform=lambda raw: float(raw) / 10.0,
            default=math.nan,
        )

        frame = TelemetryFrame(
            ids=ids,
            angles_deg=angles,
            velocities_raw=velocities,
            currents_raw=currents,
            target_angles_deg=targets,
            metadata=dict(self.metadata),
            received_at_ms=self.last_vsd_ts_ms or utc_now_ms(),
        )

        self.reset()
        return frame


class TelemetryParser:
    """Stateful parser that handles arbitrary UDP packet boundaries."""

    def __init__(self) -> None:
        self._partial_line = ""
        self._builder = _FrameBuilder()

    def feed(self, payload: bytes | str) -> List[TelemetryFrame]:
        """Consume a UDP payload and return every completed frame."""
        if isinstance(payload, bytes):
            text = payload.decode("utf-8", errors="ignore")
        else:
            text = payload

        text = self._partial_line + text
        lines = text.splitlines()
        if text and not text.endswith("\n"):
            self._partial_line = lines.pop()
        else:
            self._partial_line = ""

        frames: List[TelemetryFrame] = []
        for line in lines:
            frame = self._builder.consume_line(line)
            if frame:
                frames.append(frame)

        if (not self._partial_line) and self._builder.can_build():
            frame = self._builder.build_if_ready()
            if frame:
                frames.append(frame)
        return frames

    def finalize(self) -> Optional[TelemetryFrame]:
        """Return the last buffered frame if no new vsd line will arrive."""
        pending_frame: Optional[TelemetryFrame] = None
        if self._partial_line:
            pending_frame = self._builder.consume_line(self._partial_line)
            self._partial_line = ""
        frame = pending_frame or self._builder.build_if_ready()
        self._builder.reset()
        return frame
