from __future__ import annotations

import pytest

from lerobot_robot_ugo_pro.config_ugo_pro import DEFAULT_LEFT_IDS, DEFAULT_RIGHT_IDS, UgoProConfig


def test_config_orders_ids_by_role(ugo_config: UgoProConfig) -> None:
    assert ugo_config.ordered_joint_ids("left-only") == DEFAULT_LEFT_IDS
    assert ugo_config.ordered_joint_ids("right-only") == DEFAULT_RIGHT_IDS
    assert ugo_config.ordered_joint_ids("dual") == DEFAULT_RIGHT_IDS + DEFAULT_LEFT_IDS


def test_config_validates_ports() -> None:
    with pytest.raises(ValueError):
        UgoProConfig(telemetry_port=70000)  # type: ignore[arg-type]


def test_config_detects_duplicate_ids() -> None:
    with pytest.raises(ValueError):
        UgoProConfig(left_arm_ids=(1,), right_arm_ids=(1,))
