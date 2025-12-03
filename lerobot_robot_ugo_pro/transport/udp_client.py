"""UDP transport utilities."""

from __future__ import annotations

import logging
from logging import Formatter, BASIC_FORMAT
import math
import socket
import threading
import time
from typing import Callable, Mapping, Sequence

from ..telemetry.parser import TelemetryParser

logger = logging.getLogger(__name__)
handler = logging.StreamHandler()
handler.setLevel(logging.INFO)
handler.setFormatter(Formatter(BASIC_FORMAT))
logger.addHandler(handler)


class RateLimiter:
    """Simple time based rate limiter."""

    def __init__(self, *, rate_hz: float):
        self._period = 0.0 if rate_hz <= 0 else 1.0 / rate_hz
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self) -> None:
        if self._period <= 0:
            return
        with self._lock:
            now = time.monotonic()
            remaining = self._period - (now - self._last)
            if remaining > 0:
                time.sleep(remaining)
                now = time.monotonic()
            self._last = now

    @property
    def period(self) -> float:
        return self._period


class UgoTelemetryClient:
    """Lightweight UDP listener that pushes packets into a :class:`TelemetryParser`."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        parser: TelemetryParser,
        timeout_sec: float = 0.3,
        interface: str | None = None,
    ):
        self.host = host
        self.port = port
        self.parser = parser
        self.timeout_sec = timeout_sec
        self.interface = interface or host
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._last_rx = time.monotonic()
        self._on_timeout: Callable[[float], None] | None = None

    def start(self, on_timeout: Callable[[float], None] | None = None) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._on_timeout = on_timeout
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.interface, self.port))
        sock.settimeout(0.05)
        self._sock = sock
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("Telemetry listener bound on %s:%s", self.interface, self.port)

    def stop(self) -> None:
        self._stop.set()
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None

    # ------------------------------------------------------------------ #
    def _run(self) -> None:
        assert self._sock is not None
        while not self._stop.is_set():
            try:
                data, _ = self._sock.recvfrom(65535)
            except socket.timeout:
                if time.monotonic() - self._last_rx > self.timeout_sec:
                    if self._on_timeout:
                        self._on_timeout(self.timeout_sec)
                continue
            except OSError:
                break
            self._last_rx = time.monotonic()
            frames = self.parser.feed(data)
            logger.debug("Received UDP telemetry packet (%d bytes)", len(data))
            if not frames:
                self.parser.flush()


class UgoCommandClient:
    """Encapsulates UDP command formatting and transmission."""

    def __init__(
        self,
        *,
        remote_host: str,
        remote_port: int,
        local_host: str = "0.0.0.0",
        local_port: int = 0,
        rate_hz: float = 100.0,
        default_ids: Sequence[int] | None = None,
        default_velocity_raw: int | None = None,
        default_torque_raw: int | None = None,
    ):
        self.remote_host = remote_host
        self.remote_port = remote_port
        self.local_host = local_host
        self.local_port = local_port
        self.rate_limiter = RateLimiter(rate_hz=rate_hz)
        self._ids: tuple[int, ...] = tuple(default_ids or ())
        self._last_targets_deg: dict[int, float] = {joint_id: 0.0 for joint_id in self._ids}
        self._sock: socket.socket | None = None
        self._default_velocity_raw = default_velocity_raw
        self._default_torque_raw = default_torque_raw
        self._sync_counter = 0
        self.last_payload: str | None = None

    def connect(self) -> None:
        if self._sock:
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if self.local_port:
            sock.bind((self.local_host, self.local_port))
        self._sock = sock

    def close(self) -> None:
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def update_ids(self, ids: Sequence[int]) -> None:
        self._ids = tuple(ids)
        for joint_id in self._ids:
            self._last_targets_deg.setdefault(joint_id, 0.0)

    def send_joint_targets(
        self,
        joint_targets_deg: Mapping[int, float],
        *,
        velocity_raw: Mapping[int, float] | None = None,
        torque_raw: Mapping[int, float] | None = None,
        mode: str = "abs",
        timestamp_ms: float | None = None,
    ) -> str:
        if not self._sock:
            self.connect()
        assert self._sock is not None

        payload = self.build_payload(
            joint_targets_deg,
            velocity_raw=velocity_raw,
            torque_raw=torque_raw,
            mode=mode,
            timestamp_ms=timestamp_ms,
        )
        self.rate_limiter.wait()
        # debug payload
        logger.debug("Sending UDP command payload:\n\t%s", payload)
        self._sock.sendto(payload.encode("utf-8"), (self.remote_host, self.remote_port))
        self.last_payload = payload
        return payload

    def send_empty_packet(self) -> None:
        """Send an empty UDP packet to the configured remote."""
        if not self._sock:
            self.connect()
        assert self._sock is not None

        self.rate_limiter.wait()
        self._sock.sendto(b"", (self.remote_host, self.remote_port))

    def build_payload(
        self,
        joint_targets_deg: Mapping[int, float],
        *,
        velocity_raw: Mapping[int, float] | None,
        torque_raw: Mapping[int, float] | None,
        mode: str,
        timestamp_ms: float | None,
    ) -> str:
        ids = self._ids or tuple(sorted(joint_targets_deg.keys()))
        if not ids:
            raise ValueError("No joint ids available for command payload.")

        ordered_targets = self._ordered_values(
            ids,
            joint_targets_deg,
            formatter=lambda v: str(int(round(float(v) * 10.0))),
            fallback=self._last_targets_deg,
        )
        velocities = velocity_raw or {}
        torques = torque_raw or {}
        if not velocities and self._default_velocity_raw is not None:
            velocities = {joint_id: self._default_velocity_raw for joint_id in ids}
        if not torques and self._default_torque_raw is not None:
            torques = {joint_id: self._default_torque_raw for joint_id in ids}

        ordered_velocities = self._ordered_values(ids, velocities)
        ordered_torques = self._ordered_values(ids, torques)

        interval_ms = 0
        if self.rate_limiter.period > 0:
            interval_ms = int(round(self.rate_limiter.period * 1000.0))

        lines = [
            # f"cmd,interval:{interval_ms}[ms],write:1[ms],mode:{mode}",
            # "id," + ",".join(str(joint_id) for joint_id in ids),
            # "tar," + ",".join(ordered_targets),
            ",".join(ordered_targets),
        ]

        # if any(entry for entry in ordered_velocities):
        #     lines.append("spd," + ",".join(ordered_velocities))
        # if any(entry for entry in ordered_torques):
        #     lines.append("trq," + ",".join(ordered_torques))

        # if timestamp_ms is not None:
        #     self._sync_counter += 1
        #     lines.append(f"sync,{int(timestamp_ms)},{self._sync_counter}")

        for joint_id, value in zip(ids, ordered_targets):
            if value:
                self._last_targets_deg[joint_id] = float(int(value) / 10.0)

        return "\n".join(lines)

    def _ordered_values(
        self,
        ids: Sequence[int],
        values: Mapping[int, float],
        *,
        formatter: Callable[[float], str] | None = None,
        fallback: Mapping[int, float] | None = None,
    ) -> list[str]:
        formatter = formatter or (lambda value: str(int(round(float(value)))))
        row: list[str] = []
        for joint_id in ids:
            value = values.get(joint_id)
            if value is None and fallback is not None:
                value = fallback.get(joint_id)
            if value is None or (isinstance(value, float) and math.isnan(value)):
                row.append("")
            else:
                row.append(formatter(float(value)))
        return row
