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

"""VR teleoperation of XLeRobot with LeRobot dataset recording.

Same control core as ``teleop_xlerobot_vr.py``, plus a background thread that
batches frames into episodes and (optionally) pushes the dataset to the Hub.

Setup: see ``teleop_xlerobot_vr.py``. Edit the recording constants below.
"""

import logging
import queue
import sys
import threading
import time
from pathlib import Path

# Dev convenience: make the package importable when run without installing it.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lerobot.datasets.utils import build_dataset_frame  # noqa: E402
from lerobot.robots.xlerobot import XLerobot, XLerobotConfig  # noqa: E402
from lerobot.utils.constants import ACTION, OBS_STR  # noqa: E402
from lerobot.utils.robot_utils import precise_sleep  # noqa: E402

from lerobot_vr_teleop import VRTeleop, VRTeleopConfig, XLeRobotVRController  # noqa: E402
from lerobot_vr_teleop.recording import arm_state_keys, make_xlerobot_dataset, start_saver  # noqa: E402
from lerobot_vr_teleop.serial_resilience import enable_bus_retries  # noqa: E402
from lerobot_vr_teleop.xlerobot_ports import detect_xlerobot_ports  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# --- Teleop scope ----------------------------------------------------------
ENABLE_LEFT = False
ENABLE_RIGHT = True
ENABLE_HEAD = False
ENABLE_BASE = True
KP = 1.0
FPS = 30

# Must match your saved calibration filename "<id>.json" (xlerobot.json) or the
# robot will drop into manual calibration on connect().
ROBOT_ID = "xlerobot"

# --- Recording -------------------------------------------------------------
DATASET_REPO = "username/XLeRobot_vr_demo"
DATASET_ROOT = "my_vr_dataset"
TASK = "Grab the cup"
EPISODE_LEN = 450
NR_OF_EPISODES = 110
PUSH_TO_HUB = True


def main():
    enable_bus_retries(min_retries=3)
    # USB enumeration is not stable; identify each bus by motor count.
    port1, port2 = detect_xlerobot_ports()
    logger.info("Detected XLeRobot buses: port1(left+head)=%s port2(right+base)=%s", port1, port2)
    robot = XLerobot(XLerobotConfig(id=ROBOT_ID, port1=port1, port2=port2))
    robot.connect()
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
    controller = XLeRobotVRController(
        obs,
        enable_left=ENABLE_LEFT,
        enable_right=ENABLE_RIGHT,
        enable_head=ENABLE_HEAD,
        enable_base=ENABLE_BASE,
        kp=KP,
    )
    robot.send_action(controller.reset_to_zero(obs))

    # The recorded names are the single source of truth for both control scope
    # and dataset feature shape -- they cannot drift apart.
    recorded_names = arm_state_keys(robot, ENABLE_LEFT)
    camera_keys = list(robot.cameras.keys())

    dataset = make_xlerobot_dataset(
        robot,
        repo_id=DATASET_REPO,
        root=f"{DATASET_ROOT}_{int(time.time())}",
        fps=FPS,
        enable_left=ENABLE_LEFT,
    )

    frame_queue: queue.Queue = queue.Queue()
    shutdown_event = threading.Event()
    saving_event = threading.Event()
    saver_thread = start_saver(
        dataset,
        frame_queue,
        shutdown_event,
        saving_event,
        episode_len=EPISODE_LEN,
        n_episodes=NR_OF_EPISODES,
        push_to_hub=PUSH_TO_HUB,
    )

    logger.info("Recording VR demonstrations. Press Ctrl+C to stop.")
    try:
        while not shutdown_event.is_set():
            if saving_event.is_set():
                time.sleep(0.1)
                continue

            t0 = time.perf_counter()
            structured = teleop.get_action()
            obs = robot.get_observation()
            action = controller.goals_to_action(structured, obs)
            robot.send_action(action)

            # Build the dataset frame from the single observation read above.
            action_values = {name: action[name] for name in recorded_names}
            obs_values = {name: obs[name] for name in recorded_names}
            obs_values.update({cam: obs[cam] for cam in camera_keys})

            action_frame = build_dataset_frame(dataset.features, action_values, prefix=ACTION)
            observation_frame = build_dataset_frame(dataset.features, obs_values, prefix=OBS_STR)
            frame_queue.put({**observation_frame, **action_frame, "task": TASK})

            precise_sleep(max(0.0, 1 / FPS - (time.perf_counter() - t0)))
    except KeyboardInterrupt:
        logger.info("Stopping recording.")
    finally:
        shutdown_event.set()
        if saver_thread.is_alive():
            logger.info("Flushing dataset saver thread...")
            saver_thread.join()
        teleop.disconnect()
        robot.disconnect()


if __name__ == "__main__":
    main()
