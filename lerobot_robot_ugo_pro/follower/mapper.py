"""Leader → follower mapping helpers."""

from __future__ import annotations

from typing import Iterable, List, Sequence, Tuple

from ..configs import UgoProConfig


class UgoFollowerMapper:
    """Maps teleoperator actions to follower joint targets."""

    def __init__(self, config: UgoProConfig) -> None:
        self.config = config
        self._joint_ids = config.joint_ids
        self._half = len(self._joint_ids) // 2

    def _apply_mirror(self, values: Sequence[float]) -> List[float]:
        if not self.config.follower.mirror_mode:
            return list(values)
        if self._half == 0 or self._half * 2 != len(values):
            return list(values)
        left = list(values[: self._half])
        right = list(values[self._half :])
        return right + left

    def _apply_role_mask(self, values: Sequence[float]) -> List[float]:
        role = self.config.follower.role
        if role == "dual":
            return list(values)
        mask: List[bool]
        if role == "left":
            mask = [True] * self._half + [False] * (len(values) - self._half)
        else:  # role == "right"
            mask = [False] * self._half + [True] * (len(values) - self._half)
        return [value if keep else 0.0 for value, keep in zip(values, mask)]

    def _clamp_to_limits(self, values: Sequence[float]) -> List[float]:
        clamped: List[float] = []
        for joint_id, value in zip(self._joint_ids, values):
            lower, upper = self.config.joint_limits_for(joint_id)
            clamped.append(min(max(value, lower), upper))
        return clamped

    def map_action(self, action: Sequence[float]) -> List[float]:
        if len(action) != len(self._joint_ids):
            raise ValueError(
                f"Expected {len(self._joint_ids)} action values, got {len(action)}"
            )
        scaled = [value * self.config.follower.follower_gain for value in action]
        mirrored = self._apply_mirror(scaled)
        masked = self._apply_role_mask(mirrored)
        return self._clamp_to_limits(masked)

    def map_dict(self, action: Iterable[Tuple[int, float]]) -> List[float]:
        """Alternative helper that accepts (joint_id, value) pairs."""
        action_map = {joint_id: value for joint_id, value in action}
        ordered = [action_map.get(joint_id, 0.0) for joint_id in self._joint_ids]
        return self.map_action(ordered)
