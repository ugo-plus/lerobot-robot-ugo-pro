"""Configuration model for the ugo pro follower."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field

from lerobot.cameras.configs import CameraConfig  # type: ignore
from lerobot.robots.config import RobotConfig  # type: ignore

DEFAULT_LEFT_IDS: tuple[int, ...] = (21, 22, 23, 24, 25, 26, 27, 28)
DEFAULT_RIGHT_IDS: tuple[int, ...] = (11, 12, 13, 14, 15, 16, 17, 18)
VALID_FOLLOWER_ROLES = {"dual", "left-only", "right-only"}


def _default_joint_limits() -> dict[int, tuple[float, float]]:
    limits: dict[int, tuple[float, float]] = {}
    for joint_id in DEFAULT_LEFT_IDS + DEFAULT_RIGHT_IDS:
        limits[joint_id] = (-180.0, 180.0)
    return limits


@RobotConfig.register_subclass("ugo_pro")
@dataclass(kw_only=True)
class UgoProConfig(RobotConfig):
    """Dataclass capturing runtime knobs for the ugo pro follower."""

    telemetry_host: str = "0.0.0.0"
    telemetry_port: int = 8886
    mcu_host: str = "192.168.4.40"
    command_port: int = 8888
    command_bind_host: str = "0.0.0.0"
    command_bind_port: int = 0
    network_interface: str | None = None
    timeout_sec: float = 0.3
    command_rate_hz: float = 100.0
    left_arm_ids: tuple[int, ...] = DEFAULT_LEFT_IDS
    right_arm_ids: tuple[int, ...] = DEFAULT_RIGHT_IDS
    joint_limits_deg: dict[int, tuple[float, float]] = field(default_factory=_default_joint_limits)
    velocity_limit_raw: int | None = 512
    torque_limit_raw: int | None = 1023
    follower_gain: float = 1.0
    follower_role: str = "dual"
    mirror_mode: bool = False
    action_map: dict[str, int] = field(default_factory=dict)
    command_history_size: int = 32
    expose_velocity: bool = True
    expose_current: bool = True
    expose_commanded: bool = True
    cameras: dict[str, CameraConfig] = field(default_factory=dict)

    def __post_init__(self) -> None:
        super().__post_init__()
        self._validate_network()
        self._validate_ids()
        self._validate_joint_limits()
        self._validate_action_map()

    @property
    def all_joint_ids(self) -> tuple[int, ...]:
        return self.left_arm_ids + self.right_arm_ids

    def ordered_joint_ids(self, role: str | None = None) -> tuple[int, ...]:
        """Return the joint ordering for the configured follower role."""

        role = (role or self.follower_role).lower()
        if role not in VALID_FOLLOWER_ROLES:
            raise ValueError(f"Unsupported follower role '{role}'")
        if role == "dual":
            return self.all_joint_ids
        if role == "left-only":
            return self.left_arm_ids
        return self.right_arm_ids

    def joint_limit_for(self, joint_id: int) -> tuple[float, float]:
        return self.joint_limits_deg[joint_id]

    def default_targets_deg(self) -> dict[int, float]:
        return {joint_id: 0.0 for joint_id in self.all_joint_ids}

    # --------------------------------------------------------------------- #
    # Internal validation helpers
    # --------------------------------------------------------------------- #
    def _validate_network(self) -> None:
        for attr in ("telemetry_host", "mcu_host", "command_bind_host"):
            self._ensure_valid_ip(getattr(self, attr), attr)
        for attr in ("telemetry_port", "command_port"):
            self._ensure_port(getattr(self, attr), attr)
        if self.command_bind_port:
            self._ensure_port(self.command_bind_port, "command_bind_port")
        if self.timeout_sec <= 0:
            raise ValueError("timeout_sec must be greater than zero")
        if self.command_rate_hz <= 0:
            raise ValueError("command_rate_hz must be greater than zero")
        if not (0.0 <= self.follower_gain <= 1.0):
            raise ValueError("follower_gain must be within [0.0, 1.0]")
        if self.follower_role not in VALID_FOLLOWER_ROLES:
            raise ValueError(f"Unsupported follower_role '{self.follower_role}'")

    def _validate_ids(self) -> None:
        if not self.left_arm_ids or not self.right_arm_ids:
            raise ValueError("left_arm_ids and right_arm_ids cannot be empty")
        duplicates = set(self.left_arm_ids).intersection(self.right_arm_ids)
        if duplicates:
            raise ValueError(f"Joint IDs must be unique across arms: {sorted(duplicates)}")

    def _validate_joint_limits(self) -> None:
        for joint_id in self.all_joint_ids:
            if joint_id not in self.joint_limits_deg:
                raise ValueError(f"joint_limits_deg missing entry for joint {joint_id}")
            limit = self.joint_limits_deg[joint_id]
            if len(limit) != 2:
                raise ValueError(f"joint_limits_deg for joint {joint_id} must be a pair")
            lo, hi = limit
            if lo >= hi:
                raise ValueError(f"Invalid joint limit for joint {joint_id}: min {lo} >= max {hi}")

    def _validate_action_map(self) -> None:
        for key, joint_id in self.action_map.items():
            if not isinstance(key, str):
                raise ValueError("action_map keys must be strings")
            if joint_id not in self.all_joint_ids:
                raise ValueError(f"action_map targets unknown joint id {joint_id}")

    @staticmethod
    def _ensure_valid_ip(address: str, field_name: str) -> None:
        try:
            ipaddress.ip_address(address)
        except ValueError as exc:
            raise ValueError(f"{field_name} must be a valid IPv4/IPv6 address") from exc

    @staticmethod
    def _ensure_port(port: int, field_name: str) -> None:
        if not (0 < port < 65536):
            raise ValueError(f"{field_name} must be within 1-65535")
