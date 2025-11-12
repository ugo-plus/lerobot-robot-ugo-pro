from __future__ import annotations

from lerobot_robot_ugo_pro.telemetry import JointStateBuffer, TelemetryParser


def test_parser_decodes_single_packet() -> None:
    buffer = JointStateBuffer()
    parser = TelemetryParser(buffer=buffer)
    payload = (
        "vsd,interval:10[ms],read:5[ms],write:1[ms]\n"
        "id,11,12\n"
        "agl,123,456\n"
        "vel,1,2\n"
        "cur,3,4\n"
        "obj,120,450\n"
    ).encode()

    parser.feed(payload)
    frame = parser.flush()
    assert frame is not None

    assert frame.angles_deg[11] == 12.3
    assert frame.velocities_raw[12] == 2
    assert frame.currents_raw[11] == 3
    assert frame.commanded_deg[12] == 45.0
    assert frame.vsd_interval_ms == 10
    assert buffer.latest() is frame


def test_parser_handles_partial_packets() -> None:
    parser = TelemetryParser(buffer=JointStateBuffer())
    part1 = "vsd,interval:10[ms]\nid,1,2\nagl,10,\n".encode()
    part2 = "vel,,2\nobj,10,20\n".encode()

    parser.feed(part1)
    parser.feed(part2)
    frame = parser.flush()
    assert frame is not None
    assert frame.angles_deg[1] == 1.0
    assert frame.angles_deg[2] != frame.angles_deg[2]  # NaN for missing value
    assert frame.health in {"partial", "missing_agl"}
