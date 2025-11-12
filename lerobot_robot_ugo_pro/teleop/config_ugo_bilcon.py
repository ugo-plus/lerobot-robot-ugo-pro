"""Configuration for the ugo_bilcon dummy teleoperator."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Tuple

from lerobot.teleoperators.config import TeleoperatorConfig # type: ignore

from ..config_ugo_pro import DEFAULT_LEFT_IDS, DEFAULT_RIGHT_IDS


def _default_joint_ids() -> Tuple[int, ...]:
    return DEFAULT_LEFT_IDS + DEFAULT_RIGHT_IDS


@TeleoperatorConfig.register_subclass("ugo_bilcon")
@dataclass(kw_only=True)
class UgoBilconConfig(TeleoperatorConfig):
    """Minimal configuration for the ugo_bilcon teleoperator."""

    joint_ids: tuple[int, ...] = field(default_factory=_default_joint_ids)
    mode: str = "bilateral"
