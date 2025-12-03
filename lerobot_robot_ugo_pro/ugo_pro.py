"""LeRobot Robot implementation for the ugo pro follower."""

from __future__ import annotations

import copy
import logging
from logging import Formatter, BASIC_FORMAT
import math
from collections import deque
from functools import cached_property
from typing import Any, Callable

from lerobot.cameras.utils import make_cameras_from_configs  # type: ignore
from lerobot.utils.errors import DeviceAlreadyConnectedError, DeviceNotConnectedError  # type: ignore
from lerobot.robots.robot import Robot  # type: ignore

from .config_ugo_pro import UgoProConfig
from .follower.mapper import UgoFollowerMapper
from .telemetry import JointStateBuffer, TelemetryFrame, TelemetryParser
from .transport import UgoCommandClient, UgoTelemetryClient
from .utils import now_ms

logger = logging.getLogger(__name__)
handler = logging.StreamHandler()
handler.setLevel(logging.INFO)
handler.setFormatter(Formatter(BASIC_FORMAT))
logger.addHandler(handler)

class UgoPro(Robot):
    """Follower that talks to the ugo Controller MCU via UDP."""

    config_class = UgoProConfig
    name = "ugo_pro"

    def __init__(
        self,
        config: UgoProConfig,
        *,
        telemetry_parser: TelemetryParser | None = None,
        telemetry_client_factory: Callable[[], UgoTelemetryClient] | None = None,
        command_client_factory: Callable[[], UgoCommandClient] | None = None,
    ):
        super().__init__(config)
        self.config = config
        logger.debug(
            "Initializing UgoPro (id=%s) with %d joints and %d cameras.",
            config.id,
            len(config.all_joint_ids),
            len(config.cameras),
        )
        self._joint_buffer = telemetry_parser.buffer if telemetry_parser else JointStateBuffer()
        self._telemetry_parser = telemetry_parser or TelemetryParser(buffer=self._joint_buffer)
        self._telemetry_client_factory = telemetry_client_factory
        self._command_client_factory = command_client_factory
        self._telemetry_client: UgoTelemetryClient | None = None
        self._command_client: UgoCommandClient | None = None
        self._mapper = UgoFollowerMapper(config)
        self._last_sent_targets = config.default_targets_deg()
        self._cmd_history: deque[dict[str, Any]] = deque(maxlen=config.command_history_size)
        self._last_observation: dict[str, Any] | None = {}
        self._is_connected = False
        self.cameras = make_cameras_from_configs(config.cameras)

    # ------------------------------------------------------------------ #
    @cached_property
    def observation_features(self) -> dict[str, Any]:
        features: dict[str, Any] = {}
        for joint_id in self.config.all_joint_ids:
            features[f"joint_{joint_id}.pos_deg"] = float
            if self.config.expose_velocity:
                features[f"joint_{joint_id}.vel_raw"] = float
            if self.config.expose_current:
                features[f"joint_{joint_id}.cur_raw"] = float
            if self.config.expose_commanded:
                features[f"joint_{joint_id}.target_deg"] = float
        features["packet_age_ms"] = float
        features["vsd_interval_ms"] = float
        features["vsd_read_ms"] = float
        features["vsd_write_ms"] = float
        features["status.health"] = str
        features["status.missing_fields"] = int
        features["cmd_history"] = list
        for name, cam_cfg in self.config.cameras.items():
            features[f"camera_{name}"] = (cam_cfg.height, cam_cfg.width, 3)
        return features

    @cached_property
    def action_features(self) -> dict[str, Any]:
        features: dict[str, Any] = {}
        for joint_id in self.config.all_joint_ids:
            features[f"joint_{joint_id}.target_deg"] = float
            # features[f"joint_{joint_id}.velocity_raw"] = float
            # features[f"joint_{joint_id}.torque_raw"] = float
        features["mode"] = str
        features["teleop.meta.timestamp"] = float
        return features

    # ------------------------------------------------------------------ #
    @property
    def is_connected(self) -> bool:
        return self._is_connected

    def connect(self, calibrate: bool = True) -> None:
        if self.is_connected:
            raise DeviceAlreadyConnectedError(f"{self} already connected")

        logger.debug(
            "Connecting UgoPro (id=%s) | calibrate=%s | telemetry=%s:%s | command=%s:%s",
            self.config.id,
            calibrate,
            self.config.telemetry_host,
            self.config.telemetry_port,
            self.config.mcu_host,
            self.config.command_port,
        )
        self._telemetry_client = self._build_telemetry_client()
        # self._telemetry_client.start(on_timeout=self._handle_timeout)
        self._command_client = self._build_command_client()
        self._command_client.connect()
        self._command_client.send_empty_packet()

        for cam in self.cameras.values():
            cam.connect()
            cam_name = getattr(cam, "name", repr(cam))
            logger.debug("Camera %s connected.", cam_name)

        if calibrate:
            self.calibrate()
        self.configure()
        self._is_connected = True
        self._wait_for_joint_map()
        logger.debug("UgoPro connected and ready.")

    def disconnect(self) -> None:
        if not self.is_connected:
            return
        logger.debug("Disconnecting UgoPro (id=%s).", self.config.id)
        if self._telemetry_client:
            self._telemetry_client.stop()
            self._telemetry_client = None
        if self._command_client:
            self._command_client.close()
            self._command_client = None
        for cam in self.cameras.values():
            try:
                cam.disconnect()
            except Exception:
                logger.debug("Failed to disconnect camera", exc_info=True)
        self._is_connected = False
        logger.debug("UgoPro disconnected.")

    # ------------------------------------------------------------------ #
    @property
    def is_calibrated(self) -> bool:
        return True

    def calibrate(self) -> None:
        logger.debug("UgoPro does not require explicit calibration at this stage.")

    def configure(self) -> None:
        ids = self._telemetry_parser.latest_ids or self.config.all_joint_ids
        logger.debug("Configuring command client with ids: %s", ids)
        if self._command_client:
            self._command_client.update_ids(ids)
        for joint_id in ids:
            self._last_sent_targets.setdefault(joint_id, 0.0)

    # ------------------------------------------------------------------ #
    def get_observation(self) -> dict[str, Any]:
        if not self.is_connected:
            raise DeviceNotConnectedError(f"{self} is not connected.")

        frame = self._joint_buffer.latest()
        logger.debug("Fetching observation; frame available=%s", frame is not None)
        if frame is None:
            frame = TelemetryFrame(
                timestamp=now_ms() / 1000.0,
                joint_ids=self.config.all_joint_ids,
                angles_deg={jid: math.nan for jid in self.config.all_joint_ids},
                velocities_raw={jid: math.nan for jid in self.config.all_joint_ids},
                currents_raw={jid: math.nan for jid in self.config.all_joint_ids},
                commanded_deg={jid: math.nan for jid in self.config.all_joint_ids},
                health="missing_all",
            )
            # for joint_id in self.config.joint_ids:
            #     frame[f"joint_{joint_id}.target_deg"] = 0.0
            #     frame[f"joint_{joint_id}.velocity_raw"] = 0.0
            #     frame[f"joint_{joint_id}.torque_raw"] = 0.0
            # raise DeviceNotConnectedError("No telemetry frame received yet.")

        return self._frame_to_observation(frame)

    def send_action(self, action: dict[str, Any]) -> dict[str, Any]:
        if not self.is_connected or not self._command_client:
            raise DeviceNotConnectedError(f"{self} is not connected.")

        frame = self._joint_buffer.latest()
        current_angles = frame.angles_deg if frame else self._last_sent_targets

        action = self._last_observation if self._last_observation is None else action

        logger.debug(
            "send_action invoked: mode=%s | fields=%d | current_angles=%s",
            action.get("mode"),
            len(action),
            "present" if frame else "cached",
        )
        mapped = self._mapper.map(
            copy.deepcopy(action),
            current_angles=current_angles,
            previous_targets=self._last_sent_targets,
        )

        clipped_targets = self._clip_targets(mapped.targets_deg)
        timestamp_ms = self._extract_timestamp(action)
        payload = self._command_client.send_joint_targets(
            clipped_targets,
            velocity_raw=mapped.velocity_raw,
            torque_raw=mapped.torque_raw,
            mode=mapped.mode,
            timestamp_ms=timestamp_ms,
        )
        self._last_sent_targets = clipped_targets
        self._record_command(payload, mapped.mode)

        return {"mode": mapped.mode, "joint_targets_deg": clipped_targets}

    # ------------------------------------------------------------------ #
    def _frame_to_observation(self, frame: TelemetryFrame) -> dict[str, Any]:
        obs: dict[str, Any] = {}
        for joint_id in self.config.all_joint_ids:
            obs[f"joint_{joint_id}.pos_deg"] = frame.angles_deg.get(joint_id, math.nan)
            # if self.config.expose_velocity:
            #     obs[f"joint_{joint_id}.vel_raw"] = frame.velocities_raw.get(joint_id, math.nan)
            # if self.config.expose_current:
            #     obs[f"joint_{joint_id}.cur_raw"] = frame.currents_raw.get(joint_id, math.nan)
            if self.config.expose_commanded:
                obs[f"joint_{joint_id}.target_deg"] = frame.commanded_deg.get(joint_id, math.nan)

        obs["packet_age_ms"] = frame.packet_age_ms
        obs["vsd_interval_ms"] = frame.vsd_interval_ms or math.nan
        obs["vsd_read_ms"] = frame.vsd_read_ms or math.nan
        obs["vsd_write_ms"] = frame.vsd_write_ms or math.nan
        obs["status.health"] = frame.health
        obs["status.missing_fields"] = len(frame.missing_fields)
        obs["cmd_history"] = list(self._cmd_history)

        for name, cam in self.cameras.items():
            obs[f"camera_{name}"] = cam.async_read()

        # logger.debug("obs : %s", obs)
        self._last_observation = obs
        return obs

    def _clip_targets(self, targets: dict[int, float]) -> dict[int, float]:
        clipped: dict[int, float] = {}
        for joint_id, value in targets.items():
            lo, hi = self.config.joint_limit_for(joint_id)
            clipped_value = float(min(max(value, lo), hi))
            if clipped_value != value:
                logger.debug(
                    "Target for joint %d clipped from %.2f to %.2f (limits %.2f..%.2f).",
                    joint_id,
                    value,
                    clipped_value,
                    lo,
                    hi,
                )
            clipped[joint_id] = clipped_value
        return clipped

    def _wait_for_joint_map(self) -> None:
        ids = self._telemetry_parser.latest_ids
        if ids:
            return
        logger.debug("Waiting for telemetry id ordering (timeout %.1fs).", self.config.timeout_sec)
        deadline = now_ms() + self.config.timeout_sec * 1000.0
        while now_ms() < deadline:
            ids = self._telemetry_parser.latest_ids
            if ids:
                if self._command_client:
                    self._command_client.update_ids(ids)
                logger.debug("Telemetry id ordering received: %s", ids)
                return

        logger.warning("Timed out waiting for telemetry id ordering; falling back to config order.")
        if self._command_client:
            self._command_client.update_ids(self.config.all_joint_ids)

    def _handle_timeout(self, timeout_sec: float) -> None:
        if not self._command_client:
            return
        logger.debug("Telemetry timeout detected (%.2fs). Sending hold command.", timeout_sec)
        try:
            self._command_client.send_joint_targets(
                self._last_sent_targets,
                mode="hold",
                velocity_raw=None,
                torque_raw=None,
                timestamp_ms=None,
            )
        except Exception:
            logger.debug("Failed to send hold command during telemetry timeout.", exc_info=True)

    def _record_command(self, payload: str, mode: str) -> None:
        self._cmd_history.append({"ts_ms": now_ms(), "mode": mode, "payload": payload})

    def _build_telemetry_client(self) -> UgoTelemetryClient:
        if self._telemetry_client_factory:
            return self._telemetry_client_factory()
        logger.debug(
            "Creating telemetry client host=%s port=%s interface=%s timeout=%.2fs",
            self.config.telemetry_host,
            self.config.telemetry_port,
            self.config.network_interface or self.config.telemetry_host,
            self.config.timeout_sec,
        )
        return UgoTelemetryClient(
            host=self.config.telemetry_host,
            port=self.config.telemetry_port,
            parser=self._telemetry_parser,
            timeout_sec=self.config.timeout_sec,
            interface=self.config.network_interface or self.config.telemetry_host,
        )

    def _build_command_client(self) -> UgoCommandClient:
        if self._command_client_factory:
            return self._command_client_factory()
        logger.debug(
            "Creating command client remote=%s:%s local=%s:%s rate=%.1fHz",
            self.config.mcu_host,
            self.config.command_port,
            self.config.command_bind_host,
            self.config.command_bind_port,
            self.config.command_rate_hz,
        )
        return UgoCommandClient(
            remote_host=self.config.mcu_host,
            remote_port=self.config.command_port,
            local_host=self.config.command_bind_host,
            local_port=self.config.command_bind_port,
            rate_hz=self.config.command_rate_hz,
            default_ids=self.config.all_joint_ids,
            default_velocity_raw=self.config.velocity_limit_raw,
            default_torque_raw=self.config.torque_limit_raw,
        )

    @staticmethod
    def _extract_timestamp(action: dict[str, Any]) -> float | None:
        return action.get("teleop.meta.timestamp") or action.get("timestamp_ms")
