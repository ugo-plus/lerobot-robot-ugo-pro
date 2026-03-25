"""Tests for MCU v1.0/v1.1 packet parsing compatibility.

This test file can be run directly without the full lerobot dependency.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def setup_mock_lerobot() -> None:
    """Set up mock lerobot modules to allow imports without full dependency."""
    lerobot = types.ModuleType("lerobot")
    lerobot_cameras = types.ModuleType("lerobot.cameras")
    lerobot_cameras_configs = types.ModuleType("lerobot.cameras.configs")
    lerobot_cameras_utils = types.ModuleType("lerobot.cameras.utils")
    lerobot_utils = types.ModuleType("lerobot.utils")
    lerobot_utils_errors = types.ModuleType("lerobot.utils.errors")
    lerobot_robots = types.ModuleType("lerobot.robots")
    lerobot_robots_config = types.ModuleType("lerobot.robots.config")
    lerobot_robots_robot = types.ModuleType("lerobot.robots.robot")
    lerobot_teleoperators = types.ModuleType("lerobot.teleoperators")
    lerobot_teleoperators_config = types.ModuleType("lerobot.teleoperators.config")
    lerobot_teleoperators_teleoperator = types.ModuleType(
        "lerobot.teleoperators.teleoperator"
    )
    lerobot_teleoperators_utils = types.ModuleType("lerobot.teleoperators.utils")

    class CameraConfig:
        pass

    class RobotConfig:
        @classmethod
        def register_subclass(cls, name):
            def decorator(subcls):
                return subcls

            return decorator

    class Robot:
        def __init__(self, config):
            pass

    class TeleoperatorConfig:
        @classmethod
        def register_subclass(cls, name):
            def decorator(subcls):
                return subcls

            return decorator

    class Teleoperator:
        def __init__(self, config):
            pass

    class DeviceAlreadyConnectedError(Exception):
        pass

    class DeviceNotConnectedError(Exception):
        pass

    class TeleopEvents:
        pass

    def make_cameras_from_configs(configs):
        return {}

    lerobot_cameras_configs.CameraConfig = CameraConfig
    lerobot_cameras_utils.make_cameras_from_configs = make_cameras_from_configs
    lerobot_utils_errors.DeviceAlreadyConnectedError = DeviceAlreadyConnectedError
    lerobot_utils_errors.DeviceNotConnectedError = DeviceNotConnectedError
    lerobot_robots_config.RobotConfig = RobotConfig
    lerobot_robots_robot.Robot = Robot
    lerobot_teleoperators_config.TeleoperatorConfig = TeleoperatorConfig
    lerobot_teleoperators_teleoperator.Teleoperator = Teleoperator
    lerobot_teleoperators_utils.TeleopEvents = TeleopEvents

    lerobot.cameras = lerobot_cameras
    lerobot.utils = lerobot_utils
    lerobot.robots = lerobot_robots
    lerobot.teleoperators = lerobot_teleoperators
    lerobot_cameras.configs = lerobot_cameras_configs
    lerobot_cameras.utils = lerobot_cameras_utils
    lerobot_utils.errors = lerobot_utils_errors
    lerobot_robots.config = lerobot_robots_config
    lerobot_robots.robot = lerobot_robots_robot
    lerobot_teleoperators.config = lerobot_teleoperators_config
    lerobot_teleoperators.teleoperator = lerobot_teleoperators_teleoperator
    lerobot_teleoperators.utils = lerobot_teleoperators_utils

    sys.modules["lerobot"] = lerobot
    sys.modules["lerobot.cameras"] = lerobot_cameras
    sys.modules["lerobot.cameras.configs"] = lerobot_cameras_configs
    sys.modules["lerobot.cameras.utils"] = lerobot_cameras_utils
    sys.modules["lerobot.utils"] = lerobot_utils
    sys.modules["lerobot.utils.errors"] = lerobot_utils_errors
    sys.modules["lerobot.robots"] = lerobot_robots
    sys.modules["lerobot.robots.config"] = lerobot_robots_config
    sys.modules["lerobot.robots.robot"] = lerobot_robots_robot
    sys.modules["lerobot.teleoperators"] = lerobot_teleoperators
    sys.modules["lerobot.teleoperators.config"] = lerobot_teleoperators_config
    sys.modules["lerobot.teleoperators.teleoperator"] = (
        lerobot_teleoperators_teleoperator
    )
    sys.modules["lerobot.teleoperators.utils"] = lerobot_teleoperators_utils


# Set up mocks before importing the module
setup_mock_lerobot()

from lerobot_robot_ugo_pro.telemetry import JointStateBuffer, TelemetryParser


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
    assert buffer.latest() is not None
    assert buffer.latest().source == "follower"
    assert buffer.latest_leader() is not None
    assert buffer.latest_leader().source == "leader"


def test_has_leader_data() -> None:
    """Test has_leader_data() method."""
    buffer = JointStateBuffer()
    assert not buffer.has_leader_data()

    parser = TelemetryParser(buffer=buffer)
    leader_payload = (
        "vsd_l,interval:10[ms]\n" "id,11,12\n" "agl,100,200\n"
    ).encode()
    parser.feed(leader_payload)
    parser.flush()

    assert buffer.has_leader_data()


if __name__ == "__main__":
    test_parser_v1_0_backward_compatibility()
    print("Test 1 (v1.0 backward compatibility): PASSED")

    test_parser_v1_1_leader_follower_packets()
    print("Test 2 (v1.1 leader/follower packets): PASSED")

    test_parser_v1_1_interleaved_packets()
    print("Test 3 (v1.1 interleaved packets): PASSED")

    test_has_leader_data()
    print("Test 4 (has_leader_data): PASSED")

    print("\nAll tests passed!")
