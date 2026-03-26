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


def test_parser_v1_0_backward_compatibility() -> None:
    """MCU v1.0: vsd packet should be treated as follower data."""
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
    assert frame.source == "follower"
    assert buffer.latest() is frame
    assert buffer.latest_leader() is None
    assert not buffer.has_leader_data()


def test_parser_v1_1_leader_follower_packets() -> None:
    """MCU v1.1: vsd_l and vsd_f packets should be stored separately."""
    buffer = JointStateBuffer()
    parser = TelemetryParser(buffer=buffer)

    # Leader packet (operator input)
    leader_payload = (
        "vsd_l,interval:10[ms],read:5[ms],write:1[ms]\n"
        "id,11,12\n"
        "agl,100,200\n"
        "vel,1,2\n"
        "cur,3,4\n"
        "obj,100,200\n"
    ).encode()

    # Follower packet (actual robot state)
    follower_payload = (
        "vsd_f,interval:10[ms],read:5[ms],write:1[ms]\n"
        "id,11,12\n"
        "agl,90,180\n"
        "vel,1,2\n"
        "cur,3,4\n"
        "obj,100,200\n"
    ).encode()

    parser.feed(leader_payload)
    parser.feed(follower_payload)
    parser.flush()

    # Check leader frame
    leader_frame = buffer.latest_leader()
    assert leader_frame is not None
    assert leader_frame.source == "leader"
    assert leader_frame.angles_deg[11] == 10.0  # 100 * 0.1
    assert leader_frame.angles_deg[12] == 20.0  # 200 * 0.1
    assert buffer.has_leader_data()

    # Check follower frame
    follower_frame = buffer.latest()
    assert follower_frame is not None
    assert follower_frame.source == "follower"
    assert follower_frame.angles_deg[11] == 9.0  # 90 * 0.1
    assert follower_frame.angles_deg[12] == 18.0  # 180 * 0.1


def test_parser_v1_1_interleaved_packets() -> None:
    """MCU v1.1: Leader and follower packets can arrive in any order."""
    buffer = JointStateBuffer()
    parser = TelemetryParser(buffer=buffer)

    # Combined payload with both packet types
    payload = (
        "vsd_f,interval:10[ms]\n"
        "id,11,12\n"
        "agl,90,180\n"
        "vsd_l,interval:10[ms]\n"
        "id,11,12\n"
        "agl,100,200\n"
    ).encode()

    parser.feed(payload)
    parser.flush()

    # Both should be available
    follower_frame = buffer.latest()
    assert follower_frame is not None
    assert follower_frame.source == "follower"

    leader_frame = buffer.latest_leader()
    assert leader_frame is not None
    assert leader_frame.source == "leader"
