"""Dummy teleoperator for the ugo_pro bilateral controller."""

from __future__ import annotations

import time
from copy import deepcopy
from typing import Any

from lerobot.teleoperators.teleoperator import Teleoperator
from lerobot.teleoperators.utils import TeleopEvents
from lerobot.utils.errors import DeviceAlreadyConnectedError, DeviceNotConnectedError

from .config_ugo_bilcon import UgoBilconConfig


class UgoBilcon(Teleoperator):
    """Placeholder teleoperator so LeRobot can run alongside the bilateral controller."""

    config_class = UgoBilconConfig
    name = "ugo_bilcon"

    def __init__(self, config: UgoBilconConfig):
        # Skip calibration persistence by forcing an in-memory identifier.
        config.id = config.id or "ugo_bilcon"
        super().__init__(config)
        self.config = config
        self._is_connected = False
        self._default_action = self._make_default_action()

    def _make_default_action(self) -> dict[str, Any]:
        action: dict[str, Any] = {}
        for joint_id in self.config.joint_ids:
            action[f"joint_{joint_id}.target_deg"] = 0.0
            action[f"joint_{joint_id}.velocity_raw"] = 0.0
            action[f"joint_{joint_id}.torque_raw"] = 0.0
        action["mode"] = self.config.mode
        action["teleop.meta.timestamp"] = time.time() * 1_000
        return action

    @property
    def action_features(self) -> dict[str, Any]:
        """Mirror the follower action contract so downstream processors align."""
        features: dict[str, Any] = {}
        for joint_id in self.config.joint_ids:
            features[f"joint_{joint_id}.target_deg"] = float
            features[f"joint_{joint_id}.velocity_raw"] = float
            features[f"joint_{joint_id}.torque_raw"] = float
        features["mode"] = str
        features["teleop.meta.timestamp"] = float
        return features

    @property
    def feedback_features(self) -> dict[str, type]:
        return {}

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    def connect(self, calibrate: bool = True) -> None:  # noqa: ARG002
        if self.is_connected:
            raise DeviceAlreadyConnectedError(f"{self} already connected")
        self._is_connected = True

    def disconnect(self) -> None:
        if not self.is_connected:
            raise DeviceNotConnectedError(f"{self} is not connected.")
        self._is_connected = False

    @property
    def is_calibrated(self) -> bool:
        return True

    def calibrate(self) -> None:
        # Calibration is handled on the hardware controller, so we skip persistence.
        pass

    def configure(self) -> None:
        pass

    def get_action(self) -> dict[str, Any]:
        if not self.is_connected:
            raise DeviceNotConnectedError(f"{self} is not connected.")
        action = deepcopy(self._default_action)
        action["teleop.meta.timestamp"] = time.time() * 1_000
        return action

    def send_feedback(self, feedback: dict[str, Any]) -> None:  # noqa: ARG002
        if not self.is_connected:
            raise DeviceNotConnectedError(f"{self} is not connected.")

    def get_teleop_events(self) -> dict[TeleopEvents, bool]:
        """Expose neutral events so RL processors remain satisfied."""
        return {
            TeleopEvents.IS_INTERVENTION: False,
            TeleopEvents.TERMINATE_EPISODE: False,
            TeleopEvents.SUCCESS: False,
            TeleopEvents.RERECORD_EPISODE: False,
        }
