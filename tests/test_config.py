import pytest

from lerobot_robot_ugo_pro.configs import UgoProConfig


def test_joint_ids_concat():
    cfg = UgoProConfig()
    assert cfg.joint_ids[: len(cfg.left_joint_ids)] == cfg.left_joint_ids
    assert cfg.joint_ids[len(cfg.left_joint_ids) :] == cfg.right_joint_ids


def test_missing_joint_limits_raise():
    with pytest.raises(ValueError):
        UgoProConfig(
            joint_limits_deg={
                joint_id: (-180.0, 180.0)
                for joint_id in list(range(1, 8))  # right arm only
            }
        )
