"""Leader-to-follower action mapping helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ..configs.ugo_pro import UgoProConfig


VALID_MODES = {"abs", "rel", "hold"}


@dataclass(slots=True)
class MappedAction:
    """Normalized action passed to the command client."""

    targets_deg: dict[int, float]
    velocity_raw: dict[int, float]
    torque_raw: dict[int, float]
    mode: str


class UgoFollowerMapper:
    """Map arbitrary teleoperator inputs to ordered joint targets."""

    def __init__(self, config: UgoProConfig):
        self.config = config

    def map(
        self,
        action: Mapping[str, Any],
        *,
        current_angles: Mapping[int, float] | None,
        previous_targets: Mapping[int, float] | None,
    ) -> MappedAction:
        """Convert a generic action dict into ordered joint targets."""

        mode = str(action.get("mode", "abs")).lower()
        if mode not in VALID_MODES:
            mode = "abs"

        requested = self._extract_targets(action)
        requested.update(self._extract_action_map_targets(action))
        requested = self._apply_mirror(requested)
        targets = self._complete_targets(requested, current_angles or {}, previous_targets or {})
        targets = self._apply_follower_gain(targets, current_angles or {})

        velocity_raw = self._extract_numeric_series(action, ".velocity_raw")
        torque_raw = self._extract_numeric_series(action, ".torque_raw")

        return MappedAction(targets_deg=targets, velocity_raw=velocity_raw, torque_raw=torque_raw, mode=mode)

    # ------------------------------------------------------------------ #
    # Extraction helpers
    # ------------------------------------------------------------------ #
    def _extract_targets(self, action: Mapping[str, Any]) -> dict[int, float]:
        result: dict[int, float] = {}
        prefix = "joint_"
        suffix = ".target_deg"
        for key, value in action.items():
            if not isinstance(key, str) or not key.startswith(prefix) or not key.endswith(suffix):
                continue
            joint_str = key[len(prefix) : -len(suffix)]
            try:
                joint_id = int(joint_str)
            except ValueError:
                continue
            try:
                result[joint_id] = float(value)
            except (TypeError, ValueError):
                continue
        return result

    def _extract_action_map_targets(self, action: Mapping[str, Any]) -> dict[int, float]:
        mapped: dict[int, float] = {}
        for key, joint_id in self.config.action_map.items():
            if key not in action:
                continue
            try:
                mapped[joint_id] = float(action[key])
            except (TypeError, ValueError):
                continue
        return mapped

    def _extract_numeric_series(self, action: Mapping[str, Any], suffix: str) -> dict[int, float]:
        result: dict[int, float] = {}
        for joint_id in self.config.all_joint_ids:
            key = f"joint_{joint_id}{suffix}"
            if key not in action:
                continue
            try:
                result[joint_id] = float(action[key])
            except (TypeError, ValueError):
                continue
        return result

    # ------------------------------------------------------------------ #
    # Transformations
    # ------------------------------------------------------------------ #
    def _apply_mirror(self, targets: dict[int, float]) -> dict[int, float]:
        if not self.config.mirror_mode:
            return targets

        mirrored = targets.copy()
        for left_id, right_id in zip(self.config.left_arm_ids, self.config.right_arm_ids):
            left_val = targets.get(left_id)
            right_val = targets.get(right_id)
            if right_val is not None:
                mirrored[left_id] = -right_val
            if left_val is not None:
                mirrored[right_id] = -left_val
        return mirrored

    def _complete_targets(
        self,
        requested: dict[int, float],
        current: Mapping[int, float],
        previous: Mapping[int, float],
    ) -> dict[int, float]:
        completed: dict[int, float] = {}
        for joint_id in self.config.all_joint_ids:
            if self._role_allows_joint(joint_id) and joint_id in requested:
                completed[joint_id] = requested[joint_id]
            elif joint_id in previous:
                completed[joint_id] = previous[joint_id]
            elif joint_id in current:
                completed[joint_id] = float(current[joint_id])
            else:
                completed[joint_id] = 0.0
        return completed

    def _apply_follower_gain(self, targets: dict[int, float], current: Mapping[int, float]) -> dict[int, float]:
        gain = self.config.follower_gain
        if gain >= 1.0 or not current:
            return targets
        blended: dict[int, float] = {}
        for joint_id, target in targets.items():
            present = float(current.get(joint_id, target))
            if gain <= 0.0:
                blended[joint_id] = present
            else:
                blended[joint_id] = present + gain * (target - present)
        return blended

    def _role_allows_joint(self, joint_id: int) -> bool:
        if self.config.follower_role == "dual":
            return True
        if self.config.follower_role == "left-only":
            return joint_id in self.config.left_arm_ids
        if self.config.follower_role == "right-only":
            return joint_id in self.config.right_arm_ids
        return True
