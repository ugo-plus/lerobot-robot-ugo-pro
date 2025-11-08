# LeRobot + ugo Pro Integration

Brings an open source integration with [LeRobot](https://github.com/huggingface/lerobot) and [ugo Pro R&D model](https://ugo.plus/products/ugo-pro-rd/).

## Getting Started

```bash
pip install lerobot-robot-ugo-pro
```

Then either launch the LeRobot CLI:

```bash
lerobot-teleoperate \
    --robot.type=lerobot_robot_ugo_pro \
    --robot.id=ugo_pro_dual \
    --teleop.type=keyboard_ee
```

or interact with the robot directly in Python:

```python
from lerobot_robot_ugo_pro import UgoProConfig, UgoProFollower

robot = UgoProFollower(UgoProConfig())
robot.connect()

try:
    observation = robot.get_observation()
    robot.send_action([0.0] * len(observation["ids"]))
finally:
    robot.disconnect()
```

### Fail-safe Behavior

Per `docs/ugo_arm_monitoring_spec.md`, the follower monitors MCU telemetry age.  
If packets stop arriving beyond the configured timeout (default 0.2 s), the robot automatically issues a `mode:hold` command with the latest joint angles and tags it with `reason=telemetry_timeout` so the MCU freezes the posture safely.

## Development

Install the package in editable mode:
```bash
git clone https://github.com/ugo-plus/lerobot-robot-ugo-pro.git
cd lerobot-robot-ugo-pro
pip install -e .
pytest
```

Design notes, telemetry/command specs, and task planning live under `docs/`.
