from __future__ import annotations

from lerobot_robot_ugo_pro.configs import UgoProConfig
from lerobot_robot_ugo_pro.follower import UgoFollowerMapper


def test_mapper_uses_action_map_for_targets() -> None:
    config = UgoProConfig(action_map={"leader.elbow": 11})
    mapper = UgoFollowerMapper(config)
    result = mapper.map(
        {"leader.elbow": 42.0},
        current_angles={},
        previous_targets=config.default_targets_deg(),
    )
    assert result.targets_deg[11] == 42.0


def test_mapper_applies_mirror_mode() -> None:
    config = UgoProConfig(mirror_mode=True)
    mapper = UgoFollowerMapper(config)
    action = {"joint_1.target_deg": 15.0}
    result = mapper.map(action, current_angles={}, previous_targets=config.default_targets_deg())
    assert result.targets_deg[11] == -15.0  # mirrored and sign flipped
    assert result.targets_deg[1] == 15.0


def test_mapper_blends_with_current_angles() -> None:
    config = UgoProConfig(follower_gain=0.5)
    mapper = UgoFollowerMapper(config)
    current = {11: 10.0}
    action = {"joint_11.target_deg": 20.0}
    result = mapper.map(action, current_angles=current, previous_targets={})
    assert result.targets_deg[11] == 15.0
