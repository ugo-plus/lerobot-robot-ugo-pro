"""Telemetry frame containers and buffering utilities."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from typing import Dict, Optional, Tuple


@dataclass(slots=True, frozen=True)
class TelemetryFrame:
    """Structured view of one MCU → PC telemetry burst."""

    ids: Tuple[int, ...]
    angles_deg: Tuple[float, ...]
    velocities_raw: Tuple[int, ...]
    currents_raw: Tuple[int, ...]
    target_angles_deg: Tuple[float, ...]
    metadata: Dict[str, str] = field(default_factory=dict)
    received_at_ms: int = 0

    def __post_init__(self) -> None:
        expected_len = len(self.ids)
        for field_name, series in (
            ("angles_deg", self.angles_deg),
            ("velocities_raw", self.velocities_raw),
            ("currents_raw", self.currents_raw),
            ("target_angles_deg", self.target_angles_deg),
        ):
            if len(series) != expected_len:
                raise ValueError(
                    f"{field_name} length ({len(series)}) must match ids length ({expected_len})"
                )

    def id_index(self, servo_id: int) -> int:
        """Return the index of a servo id within the frame."""
        return self.ids.index(servo_id)

    def angle_for(self, servo_id: int) -> float:
        return self.angles_deg[self.id_index(servo_id)]

    def velocity_for(self, servo_id: int) -> int:
        return self.velocities_raw[self.id_index(servo_id)]

    def current_for(self, servo_id: int) -> int:
        return self.currents_raw[self.id_index(servo_id)]

    def target_angle_for(self, servo_id: int) -> float:
        return self.target_angles_deg[self.id_index(servo_id)]

    def to_joint_dict(self) -> Dict[int, Dict[str, float]]:
        """Export the frame as an id->measurement dictionary."""
        return {
            servo_id: {
                "angle_deg": angle,
                "velocity_raw": velocity,
                "current_raw": current,
                "target_angle_deg": target,
            }
            for servo_id, angle, velocity, current, target in zip(
                self.ids,
                self.angles_deg,
                self.velocities_raw,
                self.currents_raw,
                self.target_angles_deg,
            )
        }


class JointStateBuffer:
    """Thread-safe container for the latest telemetry frame."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._frame: Optional[TelemetryFrame] = None

    def update(self, frame: TelemetryFrame) -> None:
        with self._lock:
            self._frame = frame

    def snapshot(self) -> Optional[TelemetryFrame]:
        with self._lock:
            return self._frame

    def clear(self) -> None:
        with self._lock:
            self._frame = None
