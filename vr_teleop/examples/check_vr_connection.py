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

"""Robot-free VR connection checker.

Starts ONLY the VR server (no robot, no calibration prompt) and prints a live
status line showing whether the headset and each controller are streaming data.
Use this to confirm the Quest link works before running the real teleop.

Run, then in the Quest browser open https://<this-ip>:8443 (accept the cert),
Enter VR, and move a controller. The matching line should flip to STREAMING.
Ctrl+C to quit.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lerobot_vr_teleop import VRTeleop, VRTeleopConfig  # noqa: E402
from lerobot_vr_teleop.vr_monitor import get_local_ip  # noqa: E402


def fmt(goal: dict) -> str:
    if not goal["valid"]:
        return "—   not streaming"
    p = goal["target_position"]
    return f"STREAMING  pos=[{p[0]:+.2f} {p[1]:+.2f} {p[2]:+.2f}] trig={goal['trigger']:.2f} stick=({goal['thumbstick_x']:+.2f},{goal['thumbstick_y']:+.2f})"


def main():
    teleop = VRTeleop(VRTeleopConfig())
    teleop.connect()
    ip = get_local_ip()
    print("\n" + "=" * 70)
    print("VR server is UP. On the Quest browser:")
    print(f"  1) open  https://{ip}:8442   accept the warning (error page is fine)")
    print(f"  2) open  https://{ip}:8443   accept the warning -> Enter VR")
    print("  3) move a controller / squeeze trigger and watch below")
    print("=" * 70 + "\n")
    try:
        while True:
            g = teleop.get_action()
            line = (
                f"LEFT  {fmt(g['left']):70s} | RIGHT {fmt(g['right'])}"
                if "left" in g
                else f"RIGHT {fmt(g['right'])}"
            )
            print("\r" + line[:200].ljust(200), end="", flush=True)
            time.sleep(0.2)
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        teleop.disconnect()


if __name__ == "__main__":
    main()
