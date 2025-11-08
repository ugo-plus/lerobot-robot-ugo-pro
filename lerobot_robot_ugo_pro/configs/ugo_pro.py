"""Pydantic configuration objects describing the Ugo Pro follower setup."""

from __future__ import annotations

from typing import Dict, Iterable, List, Literal, Sequence, Tuple

from pydantic import BaseModel, Field, field_validator

from ..transport import UgoUdpClientConfig

try:  # pragma: no cover - exercised only when lerobot is available
    from lerobot.common.robot_config import RobotConfig  # type: ignore
except ImportError:  # pragma: no cover
    class RobotConfig(BaseModel):  # type: ignore
        """Fallback RobotConfig used when lerobot is not installed."""

        @classmethod
        def register_subclass(cls, *_args, **_kwargs):
            def decorator(sub_cls):
                return sub_cls

            return decorator


class FollowerParameters(BaseModel):
    """Tunable leader → follower mapping parameters."""

    mirror_mode: bool = True
    follower_gain: float = 1.0
    role: Literal["left", "right", "dual"] = "dual"


def _default_joint_limits(ids: Iterable[int]) -> Dict[int, Tuple[float, float]]:
    return {joint_id: (-180.0, 180.0) for joint_id in ids}


@RobotConfig.register_subclass("lerobot_robot_ugo_pro")  # type: ignore[misc]
class UgoProConfig(RobotConfig):
    """Primary configuration object exported to the LeRobot registry."""

    name: str = "ugo_pro"
    telemetry_udp: UgoUdpClientConfig = Field(
        default_factory=lambda: UgoUdpClientConfig(local_host="0.0.0.0", local_port=8886)
    )
    command_udp: UgoUdpClientConfig = Field(
        default_factory=lambda: UgoUdpClientConfig(local_host="0.0.0.0", local_port=0)
    )
    left_joint_ids: Tuple[int, ...] = tuple(range(11, 18))
    right_joint_ids: Tuple[int, ...] = tuple(range(1, 8))
    joint_limits_deg: Dict[int, Tuple[float, float]] = Field(
        default_factory=lambda: _default_joint_limits(list(range(1, 8)) + list(range(11, 18)))
    )
    follower: FollowerParameters = Field(default_factory=FollowerParameters)

    @property
    def joint_ids(self) -> Tuple[int, ...]:
        return self.left_joint_ids + self.right_joint_ids

    @field_validator("left_joint_ids", "right_joint_ids")
    @classmethod
    def _ensure_sorted(cls, value: Sequence[int]) -> Tuple[int, ...]:
        return tuple(sorted(value))

    @field_validator("joint_limits_deg")
    @classmethod
    def _ensure_limits_cover_all(
        cls,
        value: Dict[int, Tuple[float, float]],
        info,
    ) -> Dict[int, Tuple[float, float]]:
        joint_ids: List[int] = list(info.data.get("left_joint_ids", ())) + list(
            info.data.get("right_joint_ids", ())
        )
        missing = [joint_id for joint_id in joint_ids if joint_id not in value]
        if missing:
            raise ValueError(f"Joint limits missing ids: {missing}")
        return value

    def joint_limits_for(self, joint_id: int) -> Tuple[float, float]:
        try:
            return self.joint_limits_deg[joint_id]
        except KeyError as exc:  # pragma: no cover - configuration error
            raise KeyError(f"No joint limits configured for id {joint_id}") from exc
