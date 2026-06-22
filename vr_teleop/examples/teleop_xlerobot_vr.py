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

"""Real-time VR teleoperation of the XLeRobot dual-arm mobile manipulator.

Setup:
    1. Initialize the XLeVR submodule:  git submodule update --init --recursive
    2. (optional) pip install -e vr_teleop   # otherwise the bootstrap below is used
    3. Run this script, then open the printed https URL in the headset browser and
       accept the self-signed certificate.

Press Ctrl+C to stop.
"""

import logging
import sys
import time
from pathlib import Path

# Dev convenience: make the package importable when run without installing it.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lerobot.robots.xlerobot import XLerobot, XLerobotConfig  # noqa: E402
from lerobot.utils.robot_utils import precise_sleep  # noqa: E402

from lerobot_vr_teleop import VRTeleop, VRTeleopConfig, XLeRobotVRController  # noqa: E402
from lerobot_vr_teleop.serial_resilience import enable_bus_retries  # noqa: E402
from lerobot_vr_teleop.xlerobot_ports import detect_xlerobot_ports  # noqa: E402
from lerobot_vr_teleop.xlerobot_vr_controller import ARM_JOINTS  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# --- Teleop scope ----------------------------------------------------------
# First-bring-up SAFE defaults: right arm only. Enable the others progressively
# once the right arm tracks the controller correctly.
ENABLE_LEFT = True
ENABLE_RIGHT = True
# Head is OFF: head_motor_1/2 are not range-calibrated on this robot (~1-tick
# range), so normalized position commands are erratic. Recalibrate before enabling.
ENABLE_HEAD = False
ENABLE_BASE = False
KP = 0.8
FPS = 30

# IMPORTANT: the robot loads calibration from "<id>.json". Your saved calibration
# is "xlerobot.json", so the id MUST be "xlerobot" or connect() will re-calibrate.
ROBOT_ID = "xlerobot"

# Clamp the per-step position delta (normalized units) so a single bad VR frame
# cannot command a large arm jump. Raise or set to None once you trust the mapping.
MAX_RELATIVE_TARGET = 5.0

# Toggle button: press A (right) / X (left) to START teleop, press again to STOP
# (arms fold to the park pose). The script keeps polling either way — only the
# physical following turns on/off. If the live "Buttons pressed:" log shows your
# A/X under a different name (e.g. 'b'), change this to that name.
TOGGLE_BUTTON = "a"


def connect_with_retry(robot, attempts: int = 3) -> None:
    """Connect, retrying past transient Feetech 'Incorrect status packet' glitches.

    A single corrupted serial packet (common right when torque switches on) can
    abort connect(). Reads are reliable, so a clean disconnect + retry succeeds.
    Note: each attempt re-shows the 'Press ENTER to restore calibration' prompt.
    """
    for i in range(1, attempts + 1):
        try:
            robot.connect()
            return
        except Exception as e:
            logger.warning("Robot connect attempt %d/%d failed: %s", i, attempts, e)
            try:
                robot.disconnect()
            except Exception:
                pass
            time.sleep(1.0)
    raise RuntimeError(f"Robot failed to connect after {attempts} attempts.")


def enabled_arm_pos_keys() -> list[str]:
    """The `<arm>_arm_<joint>.pos` keys for the currently enabled arms."""
    keys = []
    if ENABLE_LEFT:
        keys += [f"left_arm_{j}.pos" for j in ARM_JOINTS]
    if ENABLE_RIGHT:
        keys += [f"right_arm_{j}.pos" for j in ARM_JOINTS]
    return keys


def fold_arms(robot, folded: dict, max_seconds: float = 4.0, tol: float = 1.5) -> None:
    """Ease the arms back to the captured `folded` pose, then return.

    Repeatedly commanding the folded target lets the robot's max_relative_target
    clamp move it there smoothly (a few units per step) instead of in one jump.
    """
    logger.info("Folding arms back to the start pose...")
    deadline = time.time() + max_seconds
    while time.time() < deadline:
        obs = robot.get_observation()
        if all(abs(obs[k] - folded[k]) < tol for k in folded):
            break
        robot.send_action(dict(folded))
        precise_sleep(1 / FPS)
    logger.info("Fold complete.")


def main():
    # Tolerate occasional corrupted serial packets so a single glitch doesn't abort
    # the ~40-write connect()/configure() burst.
    enable_bus_retries(min_retries=3)
    # USB enumeration is not stable; identify each bus by motor count.
    port1, port2 = detect_xlerobot_ports()
    logger.info("Detected XLeRobot buses: port1(left+head)=%s port2(right+base)=%s", port1, port2)
    robot = XLerobot(
        XLerobotConfig(id=ROBOT_ID, port1=port1, port2=port2, max_relative_target=MAX_RELATIVE_TARGET)
    )
    connect_with_retry(robot)
    logger.info("Robot connected (calibrated=%s)", robot.is_calibrated)

    teleop = VRTeleop(
        VRTeleopConfig(
            enable_left=ENABLE_LEFT,
            enable_right=ENABLE_RIGHT,
            enable_headset=ENABLE_HEAD,
        )
    )
    teleop.connect()

    obs = robot.get_observation()

    # Capture the current physical pose as the "folded" / park pose to return to on cancel.
    folded = {k: obs[k] for k in enabled_arm_pos_keys()}

    controller = XLeRobotVRController(
        obs,
        enable_left=ENABLE_LEFT,
        enable_right=ENABLE_RIGHT,
        enable_head=ENABLE_HEAD,
        enable_base=ENABLE_BASE,
        kp=KP,
    )

    # Start IDLE: hold the captured park pose. The robot does NOT follow the
    # controllers until the operator presses the toggle button.
    logger.info(
        "Polling started. Press %s (A=right / X=left) to START teleop; press again to STOP "
        "(arms fold to park). Ctrl+C exits.",
        TOGGLE_BUTTON.upper(),
    )
    active = False
    prev_toggle = False
    last_buttons: list[str] = []
    try:
        while True:
            t0 = time.perf_counter()
            structured = teleop.get_action()

            # Show which button fields are live (helps confirm the A/X mapping on your headset).
            pressed_names = sorted(
                f"{c}:{n}"
                for c in ("left", "right")
                for n, v in (structured.get(c, {}).get("buttons", {}) or {}).items()
                if v
            )
            if pressed_names != last_buttons:
                if pressed_names:
                    logger.info("Buttons pressed: %s", pressed_names)
                last_buttons = pressed_names

            # Rising-edge toggle: A (right) / X (left) flips teleop on/off.
            toggle = bool(
                (structured.get("right", {}).get("buttons", {}) or {}).get(TOGGLE_BUTTON)
                or (structured.get("left", {}).get("buttons", {}) or {}).get(TOGGLE_BUTTON)
            )
            if toggle and not prev_toggle:
                active = not active
                if active:
                    obs = robot.get_observation()
                    robot.send_action(controller.reset_to_zero(obs))  # re-seed baselines; ease to home
                    logger.info("▶ Teleop STARTED — arms following controllers.")
                else:
                    fold_arms(robot, folded)
                    logger.info("⏸ Teleop STOPPED — arms folded. Press %s to start again.", TOGGLE_BUTTON.upper())
            prev_toggle = toggle

            if active:
                obs = robot.get_observation()
                action = controller.goals_to_action(structured, obs)
                robot.send_action(action)
            else:
                robot.send_action(dict(folded))  # hold the park pose while idle

            precise_sleep(max(0.0, 1 / FPS - (time.perf_counter() - t0)))
    except KeyboardInterrupt:
        logger.info("Stopping VR teleoperation.")
    finally:
        try:
            fold_arms(robot, folded)
        except Exception as e:
            logger.warning("Fold failed: %s", e)
        teleop.disconnect()
        robot.disconnect()


if __name__ == "__main__":
    main()
