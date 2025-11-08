"""LeRobot Robot implementation for the Ugo Pro follower."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from threading import Thread
from typing import Optional, Sequence

from ..configs import UgoProConfig
from ..follower import UgoFollowerMapper
from ..telemetry.frame import JointStateBuffer, TelemetryFrame
from ..transport import CommandPayload, UgoCommandClient, UgoTelemetryClient
from ..utils import utc_now_ms

try:  # pragma: no cover - exercised only with lerobot installed
    from lerobot.common.robot import Robot as _Robot  # type: ignore
except ImportError:  # pragma: no cover
    class _Robot:  # type: ignore
        """Fallback Robot base class used in local tests."""

Robot = _Robot

try:  # pragma: no cover
    from lerobot.common.exceptions import DeviceNotConnectedError as _DeviceNotConnectedError  # type: ignore
except ImportError:  # pragma: no cover
    class _DeviceNotConnectedError(RuntimeError):
        """Raised when the robot is not connected."""

DeviceNotConnectedError = _DeviceNotConnectedError


class UgoProFollower(Robot):
    """Connects LeRobot to the UDP telemetry/command pipes of the Ugo Pro."""

    def __init__(self, config: Optional[UgoProConfig] = None) -> None:
        super().__init__()  # type: ignore[misc]
        self.config = config or UgoProConfig()
        self._telemetry_client = UgoTelemetryClient(self.config.telemetry_udp)
        self._command_client = UgoCommandClient(self.config.command_udp)
        self._buffer = JointStateBuffer()
        self._mapper = UgoFollowerMapper(self.config)

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_thread: Optional[Thread] = None
        self._telemetry_task: Optional[asyncio.Task] = None
        self._connected = False

    # --------------------------------------------------------------------- utils
    def _ensure_loop(self) -> None:
        if self._loop:
            return

        self._loop = asyncio.new_event_loop()

        def _runner() -> None:
            assert self._loop is not None
            asyncio.set_event_loop(self._loop)
            self._loop.run_forever()

        self._loop_thread = Thread(target=_runner, daemon=True)
        self._loop_thread.start()

    def _run_coro(self, coro):
        if not self._loop:
            raise DeviceNotConnectedError("Robot loop is not running")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result()

    # ------------------------------------------------------------------ lifecycle
    def connect(self) -> None:
        if self._connected:
            return
        self._ensure_loop()
        self._run_coro(self._async_connect())
        self._connected = True

    async def _async_connect(self) -> None:
        await self._telemetry_client.connect()
        await self._command_client.connect()
        self._telemetry_task = asyncio.create_task(
            self._telemetry_client.pump_forever(
                self._buffer,
                timeout_sec=self.config.telemetry_udp.timeout_sec,
                on_timeout=self._handle_telemetry_timeout,
            )
        )

    def disconnect(self) -> None:
        if not self._connected:
            return
        self._run_coro(self._async_disconnect())
        self._connected = False
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._loop_thread:
            self._loop_thread.join(timeout=1.0)
        self._loop = None
        self._loop_thread = None

    async def _async_disconnect(self) -> None:
        if self._telemetry_task:
            self._telemetry_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._telemetry_task
        await self._telemetry_client.disconnect()
        await self._command_client.disconnect()

    def is_connected(self) -> bool:
        return self._connected

    # ---------------------------------------------------------------- observations
    def _latest_frame(self) -> TelemetryFrame:
        frame = self._buffer.snapshot()
        if not frame:
            raise DeviceNotConnectedError("Telemetry frame is not yet available")
        return frame

    def get_observation(self) -> dict:
        frame = self._latest_frame()
        age_ms = max(0, utc_now_ms() - frame.received_at_ms)
        observation = {
            "ids": list(frame.ids),
            "angles_deg": list(frame.angles_deg),
            "velocities_raw": list(frame.velocities_raw),
            "currents_raw": list(frame.currents_raw),
            "target_angles_deg": list(frame.target_angles_deg),
            "metadata": dict(frame.metadata),
            "timestamp_ms": frame.received_at_ms,
            "packet_age_ms": age_ms,
        }
        return observation

    # ------------------------------------------------------------------ actions
    def send_action(self, action: Sequence[float]) -> None:
        if not self._connected:
            raise DeviceNotConnectedError("Robot is not connected")
        targets = self._mapper.map_action(action)
        payload = CommandPayload(
            ids=self.config.joint_ids,
            target_angles_deg=targets,
        )
        self._run_coro(self._command_client.send_payload(payload))

    async def _handle_telemetry_timeout(self) -> None:
        """Send a mode:hold command when telemetry silence exceeds the timeout."""
        if not self._connected:
            return
        frame = self._buffer.snapshot()
        if frame:
            joint_map = frame.to_joint_dict()
            targets = [
                joint_map.get(joint_id, {}).get("angle_deg", 0.0)
                for joint_id in self.config.joint_ids
            ]
        else:
            targets = [0.0 for _ in self.config.joint_ids]
        await self._command_client.send_hold(
            self.config.joint_ids,
            target_angles_deg=targets,
            metadata={"reason": "telemetry_timeout"},
        )

    # ------------------------------------------------------------- no-op helpers
    def configure(self) -> None:
        """Configuration is handled entirely through the provided config."""

    def calibrate(self) -> None:
        """The Ugo Pro MCU performs calibration on boot; nothing to do here."""
