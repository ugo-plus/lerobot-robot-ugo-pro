from __future__ import annotations

from lerobot_robot_ugo_pro.transport import UgoCommandClient


def test_command_client_builds_payload_with_defaults() -> None:
    client = UgoCommandClient(
        remote_host="127.0.0.1",
        remote_port=9999,
        default_ids=(11, 12),
        default_velocity_raw=100,
        default_torque_raw=200,
    )

    payload = client.build_payload(
        {11: 1.0, 12: -1.0},
        velocity_raw=None,
        torque_raw=None,
        mode="abs",
        timestamp_ms=1234,
    )
    lines = payload.splitlines()
    assert lines[1] == "id,11,12"
    assert lines[2] == "tar,10,-10"
    assert "spd,100,100" in payload
    assert "trq,200,200" in payload
    assert "sync,1234,1" in payload


def test_command_client_uses_previous_targets_when_missing() -> None:
    client = UgoCommandClient(remote_host="127.0.0.1", remote_port=9999, default_ids=(11, 12))
    client.build_payload(
        {11: 2.0, 12: 3.0},
        velocity_raw=None,
        torque_raw=None,
        mode="abs",
        timestamp_ms=None,
    )
    payload = client.build_payload(
        {11: 5.0},
        velocity_raw=None,
        torque_raw=None,
        mode="abs",
        timestamp_ms=None,
    )
    assert "tar,50,30" in payload
