from __future__ import annotations

import time

from typing import cast

from lerobot_robot_ugo_pro.telemetry import JointStateBuffer, TelemetryFrame, TelemetryParser
from lerobot_robot_ugo_pro.teleop.config_ugo_bilcon import UgoBilconConfig
from lerobot_robot_ugo_pro.teleop.ugo_bilcon import UgoBilcon
from lerobot_robot_ugo_pro.transport import UgoTelemetryClient


class DummyTelemetryClient:
    def start(self) -> None:  # pragma: no cover - trivial stub
        pass

    def stop(self) -> None:  # pragma: no cover - trivial stub
        pass


def test_ugo_bilcon_get_action_returns_telemetry(tmp_path) -> None:
    buffer = JointStateBuffer()
    parser = TelemetryParser(buffer=buffer)
    frame = TelemetryFrame(
        timestamp=time.time(),
        joint_ids=(11, 12),
        angles_deg={11: 10.0, 12: -5.0},
        velocities_raw={11: 1.0, 12: 2.0},
        currents_raw={11: -3.0, 12: 4.0},
        commanded_deg={11: 8.0, 12: -4.0},
    )
    buffer.update(frame)

    config = UgoBilconConfig(id="bilcon", calibration_dir=tmp_path, joint_ids=(11, 12))
    teleop = UgoBilcon(
        config,
        telemetry_parser=parser,
        telemetry_client_factory=lambda: cast(UgoTelemetryClient, DummyTelemetryClient()),
    )

    teleop.connect()
    action = teleop.get_action()

    assert action["joint_11.target_deg"] == 10.0
    # assert action["joint_11.velocity_raw"] == 1.0
    # assert action["joint_11.torque_raw"] == -3.0
    # assert action["mode"] == config.mode
    assert "teleop.meta.timestamp" in action

    teleop.disconnect()
