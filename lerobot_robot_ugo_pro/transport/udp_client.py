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
    """Lightweight UDP listener that pushes packets into a :class:`TelemetryParser`.

    Multiple instances that target the same (interface, port) share one underlying
    socket/thread to avoid binding conflicts. Each instance registers its parser
    (and optional timeout callback) with the shared receiver.
    """

    # key: (interface, port) -> _SharedReceiver
    _shared_receivers: dict[tuple[str, int], "_SharedReceiver"] = {}
    _registry_lock = threading.Lock()

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
        self._receiver: _SharedReceiver | None = None
        self._subscription_id: int | None = None

    def start(self, on_timeout: Callable[[float], None] | None = None) -> None:
        if self._subscription_id is not None:
            return

        with self._registry_lock:
            receiver = self._shared_receivers.get((self.interface, self.port))
            if receiver is None:
                receiver = _SharedReceiver(
                    interface=self.interface, port=self.port, timeout_sec=self.timeout_sec
                )
                self._shared_receivers[(self.interface, self.port)] = receiver
                logger.info("Telemetry listener bound on %s:%s", self.interface, self.port)
            else:
                logger.info(
                    "Reusing telemetry listener on %s:%s for an additional subscriber.",
                    self.interface,
                    self.port,
                )

        self._receiver = receiver
        self._subscription_id = receiver.subscribe(self.parser, on_timeout)

    def stop(self) -> None:
        if self._receiver and self._subscription_id is not None:
            should_cleanup = self._receiver.unsubscribe(self._subscription_id)
            self._subscription_id = None
            if should_cleanup:
                with self._registry_lock:
                    self._shared_receivers.pop((self.interface, self.port), None)
        self._receiver = None


class _SharedReceiver:
    """Owns a socket and fans out received packets to subscribers."""

    def __init__(self, *, interface: str, port: int, timeout_sec: float):
        self.interface = interface
        self.port = port
        self.timeout_sec = timeout_sec
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._last_rx = time.monotonic()
        self._subscribers: dict[int, tuple[TelemetryParser, Callable[[float], None] | None]] = {}
        self._sub_lock = threading.Lock()
        self._next_id = 0
        self._start_thread()

    def _start_thread(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except (AttributeError, OSError):
            # SO_REUSEPORT not available everywhere; ignore.
            pass
        sock.bind((self.interface, self.port))
        sock.settimeout(0.05)
        self._sock = sock
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def subscribe(self, parser: TelemetryParser, on_timeout: Callable[[float], None] | None) -> int:
        with self._sub_lock:
            sub_id = self._next_id
            self._next_id += 1
            self._subscribers[sub_id] = (parser, on_timeout)
        return sub_id

    def unsubscribe(self, sub_id: int) -> bool:
        with self._sub_lock:
            self._subscribers.pop(sub_id, None)
            has_subscribers = bool(self._subscribers)
        if not has_subscribers:
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
            return True
        return False

    # ------------------------------------------------------------------ #
    def _run(self) -> None:
        assert self._sock is not None
        while not self._stop.is_set():
            try:
                data, _ = self._sock.recvfrom(65535)
            except socket.timeout:
                if time.monotonic() - self._last_rx > self.timeout_sec:
                    for _, callback in list(self._subscribers.values()):
                        if callback:
                            callback(self.timeout_sec)
                continue
            except OSError:
                break

            self._last_rx = time.monotonic()
            subscribers_snapshot = list(self._subscribers.values())
            for parser, _ in subscribers_snapshot:
                frames = parser.feed(data)
                logger.debug("Received UDP telemetry packet (%d bytes)", len(data))
                if not frames:
                    parser.flush()


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

        # ordered_velocities = self._ordered_values(ids, velocities)
        # ordered_torques = self._ordered_values(ids, torques)

        # interval_ms = 0
        # if self.rate_limiter.period > 0:
        #     interval_ms = int(round(self.rate_limiter.period * 1000.0))

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
