#!/usr/bin/env python3
# Copyright 2024 The HuggingFace Inc. team. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Interactive calibration for the XLeRobot.

`lerobot-calibrate` doesn't list `xlerobot` as a robot type (the vendored driver
isn't registered in lerobot's CLI choice registry), so this script drives the
calibration directly. It mirrors what `lerobot-calibrate` does:
``connect(calibrate=False)`` -> ``calibrate()`` -> ``disconnect()``.

Ports are auto-detected by default (head bus = 8 motors, base bus = 9 = port with
id 9), so you don't have to care which /dev/ttyACM* is which.

Usage:
    # auto-detect ports (recommended)
    PYTHONPATH=src python examples/xlerobot/calibrate_xlerobot.py --robot-id xlerobot

    # or pin ports explicitly
    PYTHONPATH=src python examples/xlerobot/calibrate_xlerobot.py --robot-id xlerobot \
        --port1 /dev/ttyACM1 --port2 /dev/ttyACM0

What you'll be asked to do (torque turns OFF, so SUPPORT the arms by hand):
  1. Move the left arm + head to the MIDDLE of their range -> ENTER
  2. Sweep every left-arm joint and both head motors end-to-end -> ENTER
  3. Move the right arm to the MIDDLE of its range -> ENTER
  4. Sweep every right-arm joint end-to-end -> ENTER
The base wheels need no movement (auto full-turn). Calibration saves to
~/.cache/huggingface/lerobot/calibration/robots/xlerobot/<robot-id>.json
"""

from __future__ import annotations

import argparse

DEFAULT_PORT1 = "/dev/ttyACM0"
DEFAULT_PORT2 = "/dev/ttyACM1"


def detect_ports(log=print) -> tuple[str, str]:
    """Return (port1=head bus [ids 1-8], port2=base bus [ids 1-9]).

    Only the base bus has id 9, so it is the discriminator. Raises SystemExit if
    both buses can't be identified.
    """
    import glob

    from lerobot.motors.feetech import FeetechMotorsBus

    populated: dict[str, list[int]] = {}
    for port in sorted(glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*")):
        try:
            bus = FeetechMotorsBus(port=port, motors={})
            bus.connect(handshake=False)
            bus.set_baudrate(1_000_000)
            ids = sorted(bus.broadcast_ping() or {})
            bus.disconnect(disable_torque=False)
        except Exception:  # noqa: BLE001
            ids = []
        if ids:
            populated[port] = ids

    base = next((p for p, ids in populated.items() if 9 in ids), None)
    head = next((p for p, ids in populated.items() if p != base and ids), None)
    if not head or not base:
        raise SystemExit(
            f"Could not auto-detect both buses (found: {populated or 'nothing'}).\n"
            "Expected one port with ids 1-8 (head) and one with 1-9 (base).\n"
            "Pass --port1/--port2 explicitly, or run check_motors.py."
        )
    log(f"Auto-detected: port1 (head bus) = {head}, port2 (base bus) = {base}")
    return head, base


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Interactive XLeRobot calibration.")
    parser.add_argument("--robot-id", default="xlerobot", help="calibration file name (default: %(default)s)")
    parser.add_argument("--port1", default=None, help="head bus (left arm + head); auto-detected if omitted")
    parser.add_argument("--port2", default=None, help="base bus (right arm + base); auto-detected if omitted")
    args = parser.parse_args(argv)

    # Imported here so the module registers the xlerobot config and import errors
    # surface with a clear message.
    from lerobot.robots.xlerobot import XLerobot, XLerobotConfig

    if args.port1 is None and args.port2 is None:
        port1, port2 = detect_ports()
    else:
        port1 = args.port1 or DEFAULT_PORT1
        port2 = args.port2 or DEFAULT_PORT2

    print(f"Calibrating XLeRobot id='{args.robot_id}'  port1(head)={port1}  port2(base)={port2}")
    print("Torque will be DISABLED during calibration - SUPPORT the arms so they don't drop.\n")

    config = XLerobotConfig(id=args.robot_id, port1=port1, port2=port2)
    robot = XLerobot(config)

    robot.connect(calibrate=False)
    try:
        robot.calibrate()
    finally:
        robot.disconnect()

    print(f"\nCalibration saved for id='{args.robot_id}'.")
    print("Verify with:  PYTHONPATH=src python examples/xlerobot/check_motors.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
