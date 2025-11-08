# LeRobot + ugo Pro Integration

Brings an open source integration with [LeRobot](https://github.com/huggingface/lerobot) and [ugo Pro R&D model](https://ugo.plus/products/ugo-pro-rd/).

## Getting Started

```bash
pip install lerobot-robot-ugo-pro

lerobot-teleoperate \
    --robot.type=lerobot_robot_ugo_pro \
    --robot.id=black \
    --teleop.type=keyboard_ee \
    --fps=60
```

## Development

Install the package in editable mode:
```bash
git clone https://github.com/ugo-plus/lerobot-robot-ugo-pro.git
cd lerobot-robot-ugo-pro
pip install -e .
```