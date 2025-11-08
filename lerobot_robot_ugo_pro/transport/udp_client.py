"""Async UDP clients for telemetry reception and command transmission."""

from __future__ import annotations

import asyncio
import socket
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Iterable, List, Optional, Sequence, Union

from ..telemetry import TelemetryFrame, TelemetryParser
from ..telemetry.frame import JointStateBuffer
from ..utils import utc_now_ms


class UgoUdpClientError(RuntimeError):
    """Base error for UDP transport issues."""


@dataclass
class UgoUdpClientConfig:
    """Connection parameters shared by telemetry and command clients."""

    remote_host: str = "192.168.4.40"
    remote_port: int = 8888
    local_host: str = "0.0.0.0"
    local_port: int = 8886
    buffer_size: int = 65535
    timeout_sec: float = 0.2
    command_interval_ms: int = 10
    write_latency_ms: int = 1


class _BaseUdpClient:
    def __init__(self, config: UgoUdpClientConfig):
        self.config = config
        self._socket: Optional[socket.socket] = None

    def _ensure_socket(self) -> socket.socket:
        if not self._socket:
            raise UgoUdpClientError("UDP socket is not connected")
        return self._socket

    async def disconnect(self) -> None:
        sock, self._socket = self._socket, None
        if sock:
            sock.close()


class UgoTelemetryClient(_BaseUdpClient):
    """Async UDP receiver that parses telemetry frames as they arrive."""

    def __init__(
        self,
        config: UgoUdpClientConfig,
        parser: Optional[TelemetryParser] = None,
    ) -> None:
        super().__init__(config)
        self.parser = parser or TelemetryParser()

    async def connect(self) -> None:
        if self._socket:
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.config.local_host, self.config.local_port))
        sock.setblocking(False)
        self._socket = sock

    async def next_frame(self, timeout_sec: Optional[float] = None) -> TelemetryFrame:
        """Block until the next telemetry frame is received."""
        sock = self._ensure_socket()
        loop = asyncio.get_running_loop()
        timeout = timeout_sec if timeout_sec is not None else self.config.timeout_sec
        deadline = loop.time() + timeout
        frames: List[TelemetryFrame] = []
        while not frames:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise asyncio.TimeoutError("Telemetry timeout exceeded")
            data, _ = await asyncio.wait_for(
                loop.sock_recvfrom(sock, self.config.buffer_size),
                timeout=remaining,
            )
            frames = self.parser.feed(data)
        return frames[-1]

    async def pump_forever(
        self,
        buffer: JointStateBuffer,
        *,
        timeout_sec: Optional[float] = None,
        on_timeout: Optional[Callable[[], Awaitable[None]]] = None,
    ) -> None:
        """Continuously receive telemetry and store the latest frame into a buffer."""
        while True:
            try:
                frame = await self.next_frame(timeout_sec=timeout_sec)
            except asyncio.TimeoutError:
                if on_timeout:
                    await on_timeout()
                continue
            buffer.update(frame)


Numeric = Union[int, float]


def _pad_series(ids: Sequence[int], values: Sequence[Numeric], default: Numeric) -> List[Numeric]:
    padded: List[Numeric] = []
    for idx in range(len(ids)):
        if idx < len(values):
            padded.append(values[idx])
        else:
            padded.append(default)
    return padded


def _format_csv_row(header: str, values: Iterable[Union[int, float, str]]) -> str:
    return ",".join([header, *[str(v) for v in values]])


@dataclass
class CommandPayload:
    ids: Sequence[int]
    target_angles_deg: Sequence[float]
    speeds_raw: Optional[Sequence[int]] = None
    torques_raw: Optional[Sequence[int]] = None
    mode: str = "abs"
    sync_fields: Optional[Sequence[Union[int, float, str]]] = None
    metadata: Optional[dict[str, Union[int, float, str]]] = None

    def to_lines(
        self,
        config: UgoUdpClientConfig,
    ) -> List[str]:
        ids = list(self.ids)
        if not ids:
            raise ValueError("CommandPayload requires at least one joint id")
        if len(self.target_angles_deg) != len(ids):
            raise ValueError("target_angles_deg must match ids length")

        cmd_fields = {
            "interval": f"{config.command_interval_ms}[ms]",
            "write": f"{config.write_latency_ms}[ms]",
            "mode": self.mode,
        }
        if self.metadata:
            cmd_fields.update(self.metadata)
        cmd_row = "cmd," + ",".join(f"{key}:{value}" for key, value in cmd_fields.items())
        lines = [cmd_row]
        lines.append(_format_csv_row("id", ids))

        targets = [
            str(int(round(angle_deg * 10.0)))
            for angle_deg in self.target_angles_deg
        ]
        lines.append(_format_csv_row("tar", targets))

        if self.speeds_raw:
            speeds = _pad_series(ids, self.speeds_raw, self.speeds_raw[-1])
            lines.append(_format_csv_row("spd", speeds))
        if self.torques_raw:
            torques = _pad_series(ids, self.torques_raw, self.torques_raw[-1])
            lines.append(_format_csv_row("trq", torques))

        sync_fields = list(self.sync_fields or (utc_now_ms(), 0))
        lines.append(_format_csv_row("sync", sync_fields))
        return lines


class UgoCommandClient(_BaseUdpClient):
    """Async UDP sender that pushes CSV command packets at a fixed cadence."""

    def __init__(self, config: UgoUdpClientConfig) -> None:
        super().__init__(config)

    async def connect(self) -> None:
        if self._socket:
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.config.local_host, self.config.local_port))
        sock.connect((self.config.remote_host, self.config.remote_port))
        sock.setblocking(False)
        self._socket = sock

    async def send_payload(self, payload: CommandPayload) -> None:
        sock = self._ensure_socket()
        lines = payload.to_lines(self.config)
        packet = ("\n".join(lines) + "\n").encode("utf-8")
        loop = asyncio.get_running_loop()
        await loop.sock_sendall(sock, packet)

    def build_hold_payload(
        self,
        ids: Sequence[int],
        *,
        target_angles_deg: Optional[Sequence[float]] = None,
        metadata: Optional[dict[str, Union[int, float, str]]] = None,
    ) -> CommandPayload:
        if target_angles_deg is None:
            target_angles_deg = [0.0 for _ in ids]
        if len(target_angles_deg) != len(ids):
            raise ValueError("target_angles_deg must match ids length for hold payload")
        return CommandPayload(
            ids=ids,
            target_angles_deg=target_angles_deg,
            mode="hold",
            metadata=metadata,
        )

    async def send_hold(
        self,
        ids: Sequence[int],
        *,
        target_angles_deg: Optional[Sequence[float]] = None,
        metadata: Optional[dict[str, Union[int, float, str]]] = None,
    ) -> None:
        """Send a hold command to freeze the MCU when telemetry is stale."""
        payload = self.build_hold_payload(
            ids,
            target_angles_deg=target_angles_deg,
            metadata=metadata,
        )
        await self.send_payload(payload)
