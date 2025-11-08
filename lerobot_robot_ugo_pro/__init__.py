"""
lerobot_robot_ugo_pro
~~~~~~~~~~~~~~~~~~~~~

Follower robot implementation for controlling the dual-arm Ugo Pro platform
through LeRobot's Bring-Your-Own-Hardware (BYOH) interface.
"""

from .configs.ugo_pro import UgoProConfig
from .robots.ugo_pro_follower import UgoProFollower

__all__ = ["UgoProConfig", "UgoProFollower"]
