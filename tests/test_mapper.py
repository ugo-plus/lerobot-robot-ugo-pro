from lerobot_robot_ugo_pro.configs import FollowerParameters, UgoProConfig
from lerobot_robot_ugo_pro.follower import UgoFollowerMapper


def test_mapper_applies_gain_and_limits():
    cfg = UgoProConfig(
        joint_limits_deg={joint_id: (-10.0, 10.0) for joint_id in UgoProConfig().joint_ids},
        follower=FollowerParameters(mirror_mode=False, follower_gain=0.5),
    )
    mapper = UgoFollowerMapper(cfg)
    action = [20.0 for _ in cfg.joint_ids]
    targets = mapper.map_action(action)
    assert all(value == 10.0 for value in targets)


def test_mapper_mirror_and_role_masks():
    cfg = UgoProConfig(
        follower=FollowerParameters(mirror_mode=True, follower_gain=1.0, role="left")
    )
    mapper = UgoFollowerMapper(cfg)
    half = len(cfg.joint_ids) // 2
    action = list(range(len(cfg.joint_ids)))
    targets = mapper.map_action(action)
    # mirror swaps halves but right arm is masked to zero
    assert targets[:half] == action[half:]
    assert all(value == 0.0 for value in targets[half:])
