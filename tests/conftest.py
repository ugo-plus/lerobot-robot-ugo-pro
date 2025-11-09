from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REFS = ROOT / "refs" / "lerobot" / "src"
if REFS.exists():
    sys.path.insert(0, str(REFS))

from lerobot_robot_ugo_pro.configs import UgoProConfig  # noqa: E402


@pytest.fixture()
def ugo_config(tmp_path) -> UgoProConfig:
    return UgoProConfig(id="test_robot", calibration_dir=tmp_path)
