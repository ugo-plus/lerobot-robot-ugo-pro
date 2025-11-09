"""Structured representation of a telemetry packet."""

from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Mapping


@dataclass(slots=True)
class TelemetryFrame:
    """Container for the parsed telemetry information coming from the MCU."""

    timestamp: float
    joint_ids: tuple[int, ...]
    angles_deg: dict[int, float]
    velocities_raw: dict[int, float]
    currents_raw: dict[int, float]
    commanded_deg: dict[int, float]
    vsd_interval_ms: float | None = None
    vsd_read_ms: float | None = None
    vsd_write_ms: float | None = None
    missing_fields: tuple[str, ...] = field(default_factory=tuple)
    raw_lines: tuple[str, ...] = field(default_factory=tuple)
    health: str = "unknown"

    @property
    def packet_age_ms(self) -> float:
        """Return how old the frame is compared to the current wall-clock."""

        return max(0.0, (time.time() - self.timestamp) * 1000.0)

    def as_dict(self) -> Mapping[str, float]:
        """Expose a flattened view, mainly for debugging."""

        obs: dict[str, float] = {}
        for joint_id, value in self.angles_deg.items():
            obs[f"joint_{joint_id}.pos_deg"] = value
        return obs
