import math

import pytest

from lerobot_robot_ugo_pro.telemetry import TelemetryParser


SAMPLE_PACKET = "\n".join(
    [
        "vsd,interval:10[ms],read:5[ms],write:1[ms]",
        "id,11,12,13",
        "agl,10,20,30",
        "vel,1,2,3",
        "cur,4,5,6",
        "onj_agl,10,20,30",
        "",
    ]
)


def test_parser_generates_frame_from_packet():
    parser = TelemetryParser()
    frames = parser.feed(SAMPLE_PACKET)
    assert len(frames) == 1
    frame = frames[0]
    assert frame.ids == (11, 12, 13)
    assert frame.angles_deg == (1.0, 2.0, 3.0)
    assert frame.velocities_raw == (1, 2, 3)
    assert frame.currents_raw == (4, 5, 6)
    assert frame.target_angles_deg == (1.0, 2.0, 3.0)
    assert frame.metadata["interval"] == "10[ms]"


def test_parser_handles_partial_packets():
    parser = TelemetryParser()
    head = "vsd,interval:10[ms]\n"
    body = "id,1\nagl,10\n"
    frames = parser.feed(head)
    assert not frames
    frames = parser.feed(body)
    assert len(frames) == 1
    assert frames[0].angles_deg == (1.0,)


def test_finalize_flushes_partial_packet():
    parser = TelemetryParser()
    parser.feed("vsd,interval:10[ms]\n")
    parser.feed("id,1\nagl,10")  # no newline at the end → partial line buffered
    frames = parser.feed("")
    assert not frames
    frame = parser.finalize()
    assert frame is not None
    assert frame.ids == (1,)


def test_missing_optional_series_are_padded():
    parser = TelemetryParser()
    packet = "vsd,interval:10[ms]\nid,1,2\nagl,10,20\n"
    frames = parser.feed(packet)
    frame = frames[0]
    assert frame.currents_raw == (0, 0)
    assert frame.velocities_raw == (0, 0)
    assert math.isnan(frame.target_angles_deg[0])
