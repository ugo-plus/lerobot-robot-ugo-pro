import asyncio

from lerobot_robot_ugo_pro.configs import UgoProConfig
from lerobot_robot_ugo_pro.robots import UgoProFollower
from lerobot_robot_ugo_pro.telemetry.frame import TelemetryFrame


def _make_frame() -> TelemetryFrame:
    ids = (11, 12)
    return TelemetryFrame(
        ids=ids,
        angles_deg=(1.0, 2.0),
        velocities_raw=(0, 0),
        currents_raw=(0, 0),
        target_angles_deg=(1.0, 2.0),
        metadata={},
        received_at_ms=0,
    )


def test_handle_timeout_sends_hold_with_latest_angles(monkeypatch):
    robot = UgoProFollower(UgoProConfig())
    robot._connected = True  # type: ignore[attr-defined]
    robot._buffer.update(_make_frame())  # type: ignore[attr-defined]

    captured = {}

    async def fake_send_hold(ids, *, target_angles_deg=None, metadata=None):
        captured["ids"] = tuple(ids)
        captured["targets"] = tuple(target_angles_deg)
        captured["metadata"] = metadata

    robot._command_client.send_hold = fake_send_hold  # type: ignore[attr-defined]
    asyncio.run(robot._handle_telemetry_timeout())  # type: ignore[attr-defined]

    assert captured["ids"] == robot.config.joint_ids
    assert captured["targets"][: len(_make_frame().angles_deg)] == _make_frame().angles_deg
    assert captured["metadata"]["reason"] == "telemetry_timeout"


def test_handle_timeout_without_frame_uses_zero_targets():
    robot = UgoProFollower(UgoProConfig())
    robot._connected = True  # type: ignore[attr-defined]

    captured = {}

    async def fake_send_hold(ids, *, target_angles_deg=None, metadata=None):
        captured["targets"] = tuple(target_angles_deg)

    robot._command_client.send_hold = fake_send_hold  # type: ignore[attr-defined]
    asyncio.run(robot._handle_telemetry_timeout())  # type: ignore[attr-defined]

    assert all(value == 0.0 for value in captured["targets"])
