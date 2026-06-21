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

"""Read-only reachability check for every XLeRobot motor.

Pings each expected Feetech motor on both buses. This NEVER enables torque, moves
a joint, or writes calibration - it only opens the serial port and pings.

    bus1 (port1): left arm (ids 1-6) + head (ids 7-8)
    bus2 (port2): right arm (ids 1-6) + base wheels (ids 7-9)

Usage:
    PYTHONPATH=src python examples/xlerobot/check_motors.py
    PYTHONPATH=src python examples/xlerobot/check_motors.py --port1 /dev/ttyACM0 --port2 /dev/ttyACM1

Exit code 0 if all expected motors respond, else 1.
"""

from __future__ import annotations

import argparse

from lerobot.motors import Motor, MotorNormMode
from lerobot.motors.feetech import FeetechMotorsBus

DEFAULT_PORT1 = "/dev/ttyACM0"
DEFAULT_PORT2 = "/dev/ttyACM1"

# Exact id map from src/lerobot/robots/xlerobot/xlerobot.py
BUS1_MOTORS = {
    "left_arm_shoulder_pan": 1,
    "left_arm_shoulder_lift": 2,
    "left_arm_elbow_flex": 3,
    "left_arm_wrist_flex": 4,
    "left_arm_wrist_roll": 5,
    "left_arm_gripper": 6,
    "head_motor_1": 7,
    "head_motor_2": 8,
}
BUS2_MOTORS = {
    "right_arm_shoulder_pan": 1,
    "right_arm_shoulder_lift": 2,
    "right_arm_elbow_flex": 3,
    "right_arm_wrist_flex": 4,
    "right_arm_wrist_roll": 5,
    "right_arm_gripper": 6,
    "base_left_wheel": 7,
    "base_back_wheel": 8,
    "base_right_wheel": 9,
}


def _make_bus(port: str, id_map: dict[str, int]) -> FeetechMotorsBus:
    motors = {name: Motor(mid, "sts3215", MotorNormMode.RANGE_M100_100) for name, mid in id_map.items()}
    return FeetechMotorsBus(port=port, motors=motors)


def check_bus(label: str, port: str, id_map: dict[str, int]) -> bool:
    print(f"\n=== {label}  (port={port}) ===")
    bus = _make_bus(port, id_map)
    try:
        # handshake=False: just open the port; we ping motors ourselves.
        bus.connect(handshake=False)
    except Exception as exc:  # noqa: BLE001
        print(f"  COULD NOT OPEN PORT: {exc}")
        return False

    all_ok = True
    try:
        # Broadcast ping: which ids respond at all (at the default baud-rate)?
        try:
            found = bus.broadcast_ping() or {}
        except Exception as exc:  # noqa: BLE001
            found = {}
            print(f"  (broadcast_ping failed: {exc})")
        responding_ids = sorted(found)
        print(f"  ids responding on bus: {responding_ids if responding_ids else 'NONE'}")

        # Per-motor ping against the expected map.
        for name, mid in id_map.items():
            model = bus.ping(name, num_retry=2)
            ok = model is not None
            all_ok = all_ok and ok
            status = "OK" if ok else "** UNREACHABLE **"
            model_str = f"model={model}" if ok else ""
            print(f"  id {mid:>2}  {name:<24} {status} {model_str}")

        # Flag any unexpected ids present on the bus.
        unexpected = sorted(set(responding_ids) - set(id_map.values()))
        if unexpected:
            print(f"  WARNING: unexpected ids present (not in XLeRobot map): {unexpected}")
    finally:
        # disable_torque=False keeps this strictly read-only (no register writes).
        bus.disconnect(disable_torque=False)

    return all_ok


def detect_ports(log=print) -> tuple[str, str]:
    """Auto-detect which serial port carries which bus, regardless of ttyACM* labels.

    The head bus has 8 motors (ids 1-8); the base bus has 9 (ids 1-9, only it has
    id 9). So id 9 uniquely identifies the base bus.

    Returns:
        (port1, port2) where port1 is the head bus (left arm + head) and port2 is
        the base bus (right arm + base).

    Raises:
        SystemExit: if both buses can't be identified.
    """
    import glob

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
            "Expected one port with ids 1-8 (head) and one with ids 1-9 (base).\n"
            "Pass --port1/--port2 explicitly, or check power/cabling."
        )
    log(f"Auto-detected: port1 (head bus) = {head}, port2 (base bus) = {base}")
    return head, base


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only XLeRobot motor reachability check.")
    parser.add_argument("--port1", default=None, help="bus1 (left arm + head); auto-detected if omitted")
    parser.add_argument("--port2", default=None, help="bus2 (right arm + base); auto-detected if omitted")
    args = parser.parse_args(argv)

    print("XLeRobot motor reachability check (read-only: no torque, no motion)")

    # Auto-detect when the user did not pin both ports (handles ttyACM* renumbering).
    if args.port1 is None and args.port2 is None:
        try:
            args.port1, args.port2 = detect_ports()
        except SystemExit as exc:
            print(str(exc))
            print(f"Falling back to defaults: port1={DEFAULT_PORT1}, port2={DEFAULT_PORT2}")
            args.port1, args.port2 = DEFAULT_PORT1, DEFAULT_PORT2
    else:
        args.port1 = args.port1 or DEFAULT_PORT1
        args.port2 = args.port2 or DEFAULT_PORT2

    ok1 = check_bus("bus1: left arm + head", args.port1, BUS1_MOTORS)
    ok2 = check_bus("bus2: right arm + base", args.port2, BUS2_MOTORS)

    total = len(BUS1_MOTORS) + len(BUS2_MOTORS)
    print("\n" + "=" * 60)
    if ok1 and ok2:
        print(f"ALL {total} MOTORS REACHABLE.")
        return 0
    print("SOME MOTORS UNREACHABLE - see ** UNREACHABLE ** rows above.")
    print("Common causes: power off, daisy-chain unplugged, wrong port, or an")
    print("id/baud-rate mismatch (try `lerobot-find-port` / re-run motor setup).")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
