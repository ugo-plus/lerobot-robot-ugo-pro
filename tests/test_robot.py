from __future__ import annotations

import time

from typing import Callable, cast

from lerobot_robot_ugo_pro import UgoPro, UgoProConfig
from lerobot_robot_ugo_pro.telemetry import JointStateBuffer, TelemetryFrame, TelemetryParser
from lerobot_robot_ugo_pro.transport import UgoCommandClient, UgoTelemetryClient


class DummyTelemetryClient:
    def start(self, on_timeout=None):
        self.on_timeout = on_timeout

    def stop(self):
        pass


class DummyCommandClient:
    def __init__(self):
        self.sent: list[dict] = []
        self.ids: tuple[int, ...] = ()

    def connect(self):
        pass

    def close(self):
        pass

    def update_ids(self, ids):
        self.ids = tuple(ids)

    def send_joint_targets(self, joint_targets_deg, **kwargs):
        self.sent.append({"targets": dict(joint_targets_deg), "kwargs": kwargs})
        return "cmd"

    def send_empty_packet(self) -> None:
        self.sent.append({})

def _make_robot(config: UgoProConfig) -> tuple[UgoPro, JointStateBuffer, DummyCommandClient]:
    buffer = JointStateBuffer()
    parser = TelemetryParser(buffer=buffer)
    parser.latest_ids = config.all_joint_ids
    command_client = DummyCommandClient()
    telemetry_factory: Callable[[], UgoTelemetryClient] = cast(
        Callable[[], UgoTelemetryClient],
        lambda: cast(UgoTelemetryClient, DummyTelemetryClient()),
    )
    command_factory: Callable[[], UgoCommandClient] = cast(
        Callable[[], UgoCommandClient],
        lambda: cast(UgoCommandClient, command_client),
    )
    robot = UgoPro(
        config,
        telemetry_parser=parser,
        telemetry_client_factory=telemetry_factory,
        command_client_factory=command_factory,
    )
    robot.connect()
    return robot, buffer, command_client


def _inject_frame(config: UgoProConfig, buffer: JointStateBuffer) -> TelemetryFrame:
    joint_ids = config.all_joint_ids
    frame = TelemetryFrame(
        timestamp=time.time(),
        joint_ids=joint_ids,
        angles_deg={jid: float(jid) for jid in joint_ids},
        velocities_raw={jid: 1.0 for jid in joint_ids},
        currents_raw={jid: 2.0 for jid in joint_ids},
        commanded_deg={jid: float(jid) for jid in joint_ids},
        vsd_interval_ms=10.0,
        vsd_read_ms=5.0,
        vsd_write_ms=1.0,
    )
    buffer.update(frame)
    return frame


def test_robot_builds_observations(ugo_config: UgoProConfig) -> None:
    robot, buffer, _ = _make_robot(ugo_config)
    try:
        _inject_frame(ugo_config, buffer)
        obs = robot.get_observation()
        assert obs["joint_11.pos_deg"] == 11.0
        assert obs["vsd_interval_ms"] == 10.0
    finally:
        robot.disconnect()


def test_robot_send_action_calls_command_client(ugo_config: UgoProConfig) -> None:
    robot, buffer, command_client = _make_robot(ugo_config)
    try:
        _inject_frame(ugo_config, buffer)
        action = {"joint_11.target_deg": 15.0, "mode": "abs"}
        result = robot.send_action(action)
        print(result)
        assert command_client.sent
        assert command_client.sent[-1]["targets"][11] == 15.0
        assert result["mode"] == "abs"
    finally:
        robot.disconnect()
