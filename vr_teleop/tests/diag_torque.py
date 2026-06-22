#!/usr/bin/env python3
"""Gentle torque-enable diagnostic: energize each arm motor one at a time while
holding its current position (no movement), with retries. Distinguishes a power
brown-out (random motors fail) from a single bad motor/cable (same motor fails)."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import logging  # noqa: E402

logging.disable(logging.WARNING)

from lerobot.robots.xlerobot import XLerobot, XLerobotConfig  # noqa: E402
from lerobot_vr_teleop.serial_resilience import enable_bus_retries  # noqa: E402
from lerobot_vr_teleop.xlerobot_ports import detect_xlerobot_ports  # noqa: E402


def main():
    enable_bus_retries(min_retries=3)
    p1, p2 = detect_xlerobot_ports()
    robot = XLerobot(XLerobotConfig(id="xlerobot", port1=p1, port2=p2))
    robot.bus1.connect()
    robot.bus2.connect()
    robot.bus1.disable_torque()
    robot.bus2.disable_torque()
    time.sleep(0.2)

    plan = [
        ("bus1/left+head", robot.bus1, robot.left_arm_motors + robot.head_motors),
        ("bus2/right", robot.bus2, robot.right_arm_motors),
    ]
    results = []
    for label, bus, motors in plan:
        print(f"\n--- {label} ({p1 if bus is robot.bus1 else p2}) ---")
        for name in motors:
            try:
                pos = bus.sync_read("Present_Position", [name])
                bus.write("Goal_Position", name, pos[name])  # hold current -> no motion
                bus.enable_torque([name], num_retry=3)
                print(f"  {name:26s} ENERGIZED ok")
                results.append((name, True))
            except Exception as e:
                print(f"  {name:26s} FAILED: {e}")
                results.append((name, False))

    ok = sum(1 for _, good in results if good)
    print(f"\n{ok}/{len(results)} motors energized one-at-a-time.")
    if ok == len(results):
        print("=> All motors energize with retries on. The link has occasional packet glitches")
        print("   that retries absorb. Re-seat USB + daisy-chain connectors for a healthy link.")
    else:
        failed = [n for n, good in results if not good]
        print(f"=> Still failing on {failed} even with retries -> physical link to those is bad.")

    robot.bus1.disconnect()
    robot.bus2.disconnect()


if __name__ == "__main__":
    main()
