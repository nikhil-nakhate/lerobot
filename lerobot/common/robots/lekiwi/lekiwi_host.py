#!/usr/bin/env python

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

import base64
import json
import logging
import time

import cv2
import zmq

from lerobot.common.constants import OBS_IMAGES, OBS_STATE

from .config_lekiwi import LeKiwiConfig, LeKiwiHostConfig
from .lekiwi import LeKiwi


class LeKiwiHost:
    def __init__(self, config: LeKiwiHostConfig):
        self.zmq_context = zmq.Context()
        self.zmq_cmd_socket = self.zmq_context.socket(zmq.PULL)
        self.zmq_cmd_socket.setsockopt(zmq.CONFLATE, 1)
        self.zmq_cmd_socket.bind(f"tcp://*:{config.port_zmq_cmd}")

        self.zmq_observation_socket = self.zmq_context.socket(zmq.PUSH)
        self.zmq_observation_socket.setsockopt(zmq.CONFLATE, 1)
        self.zmq_observation_socket.bind(f"tcp://*:{config.port_zmq_observations}")

        self.connection_time_s = config.connection_time_s
        self.watchdog_timeout_ms = config.watchdog_timeout_ms
        self.max_loop_freq_hz = config.max_loop_freq_hz

    def disconnect(self):
        self.zmq_observation_socket.close()
        self.zmq_cmd_socket.close()
        self.zmq_context.term()


def main():
    from lerobot.common.utils.utils import init_logging
    init_logging()
    logging.info("Configuring LeKiwi")
    robot_config = LeKiwiConfig()
    robot_config.calibration_fpath = robot_config.calibration_dir / f"rosey_master.json"
    robot = LeKiwi(robot_config)

    logging.info("Connecting LeKiwi")
    robot.connect()

    logging.info("Starting HostAgent")
    host_config = LeKiwiHostConfig()
    host = LeKiwiHost(host_config)

    last_cmd_time = time.time()
    watchdog_active = False
    logging.info("Waiting for commands...")
    try:
        # Business logic
        start = time.perf_counter()
        duration = 0
        while duration < host.connection_time_s:
            loop_start_time = time.time()
            try:
                msg = host.zmq_cmd_socket.recv_string(zmq.NOBLOCK)
                data = dict(json.loads(msg))
                action_sent = robot.send_action(data)  # This might be clipped by max_relative_target
                last_cmd_time = time.time()
                watchdog_active = False
                
                # Send back the actual action sent (which might be clipped) and current observation
                formatted_action = {key: float(val) for key, val in action_sent.items()}
                response = {
                    "action_sent": formatted_action,
                    **formatted_observation
                }
                host.zmq_observation_socket.send_string(json.dumps(response), flags=zmq.NOBLOCK)
            except zmq.Again:
                if not watchdog_active:
                    logging.warning("No command available")
            except Exception as e:
                logging.error("Message fetching failed: %s", e)

            now = time.time()
            if (now - last_cmd_time > host.watchdog_timeout_ms / 1000) and not watchdog_active:
                logging.warning(
                    f"Command not received for more than {host.watchdog_timeout_ms} milliseconds. Stopping the base."
                )
                watchdog_active = True
                robot.stop_base()

            # Get observation from robot and format it for sending
            last_observation = robot.get_observation()
            formatted_observation = {}

            # Format state dict - convert all values to float for JSON serialization
            if OBS_STATE in last_observation:
                formatted_observation[OBS_STATE] = {key: float(val) for key, val in last_observation[OBS_STATE].items()}

            # Format camera frames - encode as base64 JPEG
            for key, val in last_observation.items():
                if key.startswith(OBS_IMAGES):
                    ret, buffer = cv2.imencode(".jpg", val, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
                    if ret:
                        formatted_observation[key] = base64.b64encode(buffer).decode("utf-8")
                    else:
                        formatted_observation[key] = ""

            # Send the formatted observation to the remote agent
            try:
                host.zmq_observation_socket.send_string(json.dumps(formatted_observation), flags=zmq.NOBLOCK)
            except zmq.Again:
                logging.info("Dropping observation, no client connected")

            # Ensure a short sleep to avoid overloading the CPU.
            elapsed = time.time() - loop_start_time

            time.sleep(max(1 / host.max_loop_freq_hz - elapsed, 0))
            duration = time.perf_counter() - start
        print("Cycle time reached.")

    except KeyboardInterrupt:
        print("Keyboard interrupt received. Exiting...")
    finally:
        print("Shutting down Lekiwi Host.")
        robot.disconnect()
        host.disconnect()

    logging.info("Finished LeKiwi cleanly")


if __name__ == "__main__":
    main()
