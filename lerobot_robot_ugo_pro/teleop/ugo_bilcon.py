"""Dummy teleoperator for the ugo_pro bilateral controller."""

from __future__ import annotations

import logging
import time
from copy import deepcopy
from typing import Any, Callable

from lerobot.teleoperators.teleoperator import Teleoperator  # type: ignore
from lerobot.teleoperators.utils import TeleopEvents  # type: ignore
from lerobot.utils.errors import DeviceAlreadyConnectedError, DeviceNotConnectedError  # type: ignore

from .config_ugo_bilcon import UgoBilconConfig
from ..telemetry import JointStateBuffer, TelemetryFrame, TelemetryParser
from ..transport import UgoTelemetryClient

logger = logging.getLogger(__name__)


class UgoBilcon(Teleoperator):
    """Placeholder teleoperator so LeRobot can run alongside the bilateral controller."""

    config_class = UgoBilconConfig
    name = "ugo_bilcon"

    def __init__(
        self,
        config: UgoBilconConfig,
        *,
        telemetry_parser: TelemetryParser | None = None,
        telemetry_client_factory: Callable[[], UgoTelemetryClient] | None = None,
    ):
        # Skip calibration persistence by forcing an in-memory identifier.
        config.id = config.id or "ugo_bilcon"
        super().__init__(config)
        self.config = config
        self._is_connected = False
        self._default_action = self._make_default_action()
        self._joint_buffer = telemetry_parser.buffer if telemetry_parser else JointStateBuffer()
        self._telemetry_parser = telemetry_parser or TelemetryParser(buffer=self._joint_buffer)
        self._telemetry_client_factory = telemetry_client_factory
        self._telemetry_client: UgoTelemetryClient | None = None

    def _make_default_action(self) -> dict[str, Any]:
        action: dict[str, Any] = {}
        for joint_id in self.config.joint_ids:
            action[f"joint_{joint_id}.target_deg"] = 0.0
            # action[f"joint_{joint_id}.velocity_raw"] = 0.0
            # action[f"joint_{joint_id}.torque_raw"] = 0.0
        return action

    @property
    def action_features(self) -> dict[str, Any]:
        """Mirror the follower action contract so downstream processors align."""
        features: dict[str, Any] = {}
        for joint_id in self.config.joint_ids:
            features[f"joint_{joint_id}.target_deg"] = float
            # features[f"joint_{joint_id}.velocity_raw"] = float
            # features[f"joint_{joint_id}.torque_raw"] = float
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
        self._telemetry_client = self._build_telemetry_client()
        self._telemetry_client.start()
        self._is_connected = True
        self._wait_for_frame()

    def disconnect(self) -> None:
        if not self.is_connected:
            raise DeviceNotConnectedError(f"{self} is not connected.")
        if self._telemetry_client:
            self._telemetry_client.stop()
            self._telemetry_client = None
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

        frame = self._joint_buffer.latest()
        if frame is None:
            self._wait_for_frame()
            frame = self._joint_buffer.latest()

        if frame is None:
            action = deepcopy(self._default_action)
        else:
            action = self._frame_to_action(frame)

        # action["mode"] = self.config.mode
        action["teleop.meta.timestamp"] = (frame.timestamp * 1_000) if frame else time.time() * 1_000
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

    # ------------------------------------------------------------------ #
    def _frame_to_action(self, frame: TelemetryFrame) -> dict[str, Any]:
        action: dict[str, Any] = {}
        for joint_id in self.config.joint_ids:
            action[f"joint_{joint_id}.target_deg"] = float(frame.angles_deg.get(joint_id, 0.0))
            # action[f"joint_{joint_id}.velocity_raw"] = float(frame.velocities_raw.get(joint_id, 0.0))
            # action[f"joint_{joint_id}.torque_raw"] = float(frame.currents_raw.get(joint_id, 0.0))
        return action

    def _wait_for_frame(self) -> None:
        if not self._telemetry_client:
            return

        deadline = time.time() + max(self.config.timeout_sec, 0.1)
        while time.time() < deadline:
            if self._joint_buffer.latest():
                return
            time.sleep(0.01)
        logger.warning("Timed out waiting for telemetry frame in ugo_bilcon teleop.")

    def _build_telemetry_client(self) -> UgoTelemetryClient:
        if self._telemetry_client_factory:
            return self._telemetry_client_factory()
        return UgoTelemetryClient(
            host=self.config.telemetry_host,
            port=self.config.telemetry_port,
            parser=self._telemetry_parser,
            timeout_sec=self.config.timeout_sec,
            interface=self.config.network_interface or self.config.telemetry_host,
        )
