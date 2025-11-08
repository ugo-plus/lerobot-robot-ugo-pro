import asyncio
import socket

import pytest

from lerobot_robot_ugo_pro.transport import (
    CommandPayload,
    UgoCommandClient,
    UgoTelemetryClient,
    UgoUdpClientConfig,
)


def test_telemetry_client_receives_frame():
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.bind(("127.0.0.1", 0))
        _, port = probe.getsockname()
    except PermissionError:
        pytest.skip("UDP sockets are not permitted in this environment")
    finally:
        try:
            probe.close()
        except Exception:
            pass

    async def _run():
        config = UgoUdpClientConfig(
            remote_host="127.0.0.1",
            remote_port=9999,
            local_host="127.0.0.1",
            local_port=port,
        )
        client = UgoTelemetryClient(config)
        await client.connect()

        sock = client._ensure_socket()  # type: ignore[attr-defined]
        host, server_port = sock.getsockname()

        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        packet = "\n".join(
            [
                "vsd,interval:10[ms]",
                "id,1",
                "agl,10",
                "",
            ]
        )
        sender.sendto(packet.encode("utf-8"), (host, server_port))
        frame = await asyncio.wait_for(client.next_frame(), timeout=1.0)
        assert frame.ids == (1,)
        await client.disconnect()
        sender.close()

    asyncio.run(_run())


def test_command_payload_to_lines():
    payload = CommandPayload(
        ids=[1, 2],
        target_angles_deg=[1.0, -1.0],
        speeds_raw=[100],
        torques_raw=[200],
    )
    lines = payload.to_lines(
        UgoUdpClientConfig(command_interval_ms=5, write_latency_ms=1)
    )
    assert lines[0].startswith("cmd,")
    assert "tar,10,-10" in lines[2]
    assert "spd,100,100" in lines[3]
    assert "trq,200,200" in lines[4]


def test_build_hold_payload_uses_provided_targets():
    client = UgoCommandClient(UgoUdpClientConfig())
    payload = client.build_hold_payload(
        ids=[1, 2],
        target_angles_deg=[3.0, -3.0],
        metadata={"reason": "test"},
    )
    lines = payload.to_lines(UgoUdpClientConfig())
    assert "tar,30,-30" in lines[2]
    assert "reason:test" in lines[0]
