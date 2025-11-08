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

## Development

Install the package in editable mode:
```bash
git clone https://github.com/ugo-plus/lerobot-robot-ugo-pro.git
cd lerobot-robot-ugo-pro
pip install -e .
pytest
```

Design notes, telemetry/command specs, and task planning live under `docs/`.
