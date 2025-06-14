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

# TODO(aliberts, Steven, Pepijn): use gRPC calls instead of zmq?

import base64
import json
import logging
from functools import cached_property
from typing import Any, Dict, Optional, Tuple

import cv2
import numpy as np
import torch
import zmq

from lerobot.common.constants import OBS_IMAGES, OBS_STATE
from lerobot.common.errors import DeviceAlreadyConnectedError, DeviceNotConnectedError

from ..robot import Robot
from .config_lekiwi import LeKiwiClientConfig


class LeKiwiClient(Robot):
    config_class = LeKiwiClientConfig
    name = "lekiwi_client"

    def __init__(self, config: LeKiwiClientConfig):
        super().__init__(config)
        self.config = config
        self.id = config.id
        self.robot_type = config.type

        self.remote_ip = config.remote_ip
        self.port_zmq_cmd = config.port_zmq_cmd
        self.port_zmq_observations = config.port_zmq_observations

        self.teleop_keys = config.teleop_keys

        self.polling_timeout_ms = config.polling_timeout_ms
        self.connect_timeout_s = config.connect_timeout_s

        self.zmq_context = None
        self.zmq_cmd_socket = None
        self.zmq_observation_socket = None

        self.last_frames = {}

        self.last_remote_state = {}

        # Define three speed levels and a current index
        self.speed_levels = [
            {"xy": 0.1, "theta": 30},  # slow
            {"xy": 0.2, "theta": 60},  # medium
            {"xy": 0.3, "theta": 90},  # fast
        ]
        self.speed_index = 0  # Start at slow

        self._is_connected = False
        self.logs = {}

        # Local camera setup
        self.local_camera = None
        if config.use_local_camera:
            self.local_camera = cv2.VideoCapture(config.local_camera_port)
            self.local_camera.set(cv2.CAP_PROP_FPS, config.local_camera_fps)
            self.local_camera.set(cv2.CAP_PROP_FRAME_WIDTH, config.local_camera_width)
            self.local_camera.set(cv2.CAP_PROP_FRAME_HEIGHT, config.local_camera_height)

    @cached_property
    def _state_ft(self) -> dict[str, type]:
        return dict.fromkeys(
            (
                "arm_shoulder_pan.pos",
                "arm_shoulder_lift.pos",
                "arm_elbow_flex.pos",
                "arm_wrist_flex.pos",
                "arm_wrist_roll.pos",
                "arm_gripper.pos",
                "x.vel",
                "y.vel",
                "theta.vel",
            ),
            float,
        )

    @cached_property
    def _state_order(self) -> tuple[str, ...]:
        return tuple(self._state_ft.keys())

    @cached_property
    def _cameras_ft(self) -> dict[str, tuple]:
        cameras = {
            "front": (640, 480, 3),
            "wrist": (640, 480, 3),
        }
        if self.config.use_local_camera:
            cameras["local"] = (self.config.local_camera_width, self.config.local_camera_height, 3)
        return cameras

    @cached_property
    def observation_features(self) -> dict[str, type | tuple]:
        features = {**self._state_ft, **self._cameras_ft}
        return features

    @cached_property
    def action_features(self) -> dict[str, type]:
        return self._state_ft

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    @property
    def is_calibrated(self) -> bool:
        pass

    def connect(self) -> None:
        """Establishes ZMQ sockets with the remote mobile robot"""

        if self._is_connected:
            raise DeviceAlreadyConnectedError(
                "LeKiwi Daemon is already connected. Do not run `robot.connect()` twice."
            )

        self.zmq_context = zmq.Context()
        self.zmq_cmd_socket = self.zmq_context.socket(zmq.PUSH)
        zmq_cmd_locator = f"tcp://{self.remote_ip}:{self.port_zmq_cmd}"
        self.zmq_cmd_socket.connect(zmq_cmd_locator)
        self.zmq_cmd_socket.setsockopt(zmq.CONFLATE, 1)

        self.zmq_observation_socket = self.zmq_context.socket(zmq.PULL)
        zmq_observations_locator = f"tcp://{self.remote_ip}:{self.port_zmq_observations}"
        self.zmq_observation_socket.connect(zmq_observations_locator)
        self.zmq_observation_socket.setsockopt(zmq.CONFLATE, 1)

        poller = zmq.Poller()
        poller.register(self.zmq_observation_socket, zmq.POLLIN)
        socks = dict(poller.poll(self.connect_timeout_s * 1000))
        if self.zmq_observation_socket not in socks or socks[self.zmq_observation_socket] != zmq.POLLIN:
            raise DeviceNotConnectedError("Timeout waiting for LeKiwi Host to connect expired.")

        self._is_connected = True

    def calibrate(self) -> None:
        pass

    def _poll_and_get_latest_message(self) -> Optional[str]:
        """Polls the ZMQ socket for a limited time and returns the latest message string."""
        poller = zmq.Poller()
        poller.register(self.zmq_observation_socket, zmq.POLLIN)

        try:
            socks = dict(poller.poll(self.polling_timeout_ms))
        except zmq.ZMQError as e:
            logging.error(f"ZMQ polling error: {e}")
            return None

        if self.zmq_observation_socket not in socks:
            logging.info("No new data available within timeout.")
            return None

        last_msg = None
        while True:
            try:
                msg = self.zmq_observation_socket.recv_string(zmq.NOBLOCK)
                last_msg = msg
            except zmq.Again:
                break

        if last_msg is None:
            logging.warning("Poller indicated data, but failed to retrieve message.")

        return last_msg

    def _parse_observation_json(self, obs_string: str) -> Optional[Dict[str, Any]]:
        """Parses the JSON observation string."""
        try:
            return json.loads(obs_string)
        except json.JSONDecodeError as e:
            logging.error(f"Error decoding JSON observation: {e}")
            return None

    def _decode_image_from_b64(self, image_b64: str) -> Optional[np.ndarray]:
        """Decodes a base64 encoded image string to an OpenCV image.
        
        Returns:
            np.ndarray: Image in (640, 480, 3) format for dataset compatibility
        """
        if not image_b64:
            return None
        try:
            jpg_data = base64.b64decode(image_b64)
            np_arr = np.frombuffer(jpg_data, dtype=np.uint8)
            frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if frame is None:
                logging.warning("cv2.imdecode returned None for an image.")
                return None
            
            # OpenCV reads in BGR, convert to RGB
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            
            # Transpose from (H, W, C) to (W, H, C) format
            frame = frame.transpose(1, 0, 2)
            
            return frame
        except (TypeError, ValueError) as e:
            logging.error(f"Error decoding base64 image data: {e}")
            return None

    def _remote_state_from_obs(
        self, observation: Dict[str, Any]
    ) -> Tuple[Dict[str, np.ndarray], Dict[str, Any]]:
        """Extracts frames and state from the parsed observation, maintaining LeKiwi's format."""
        # The host sends motor states at top level
        state_dict = {}
        for key in [
            # Arm motor positions
            "arm_shoulder_pan.pos",
            "arm_shoulder_lift.pos",
            "arm_elbow_flex.pos",
            "arm_wrist_flex.pos",
            "arm_wrist_roll.pos",
            "arm_gripper.pos",
            # Base velocities
            "x.vel",
            "y.vel",
            "theta.vel",
        ]:
            state_dict[key] = observation.get(key, 0.0)  # Use 0.0 as default if key not found

        # Decode images
        image_observation = {k: v for k, v in observation.items() if k.startswith(OBS_IMAGES)}
        current_frames: Dict[str, np.ndarray] = {}
        for full_cam_name, image_b64 in image_observation.items():
            frame = self._decode_image_from_b64(image_b64)
            if frame is not None:
                # Extract camera name (e.g. 'front' from 'images.front')
                cam_name = full_cam_name.removeprefix(f"{OBS_IMAGES}.")
                current_frames[cam_name] = frame

        # Return both the frames and state dict with motor states at top level for dataset compatibility
        return current_frames, state_dict

    def _get_data(self) -> Tuple[Dict[str, np.ndarray], Dict[str, Any], Dict[str, Any]]:
        """
        Polls the video socket for the latest observation data and reads local camera if enabled.

        Attempts to retrieve and decode the latest message within a short timeout.
        If successful, updates and returns the new frames, speed, and arm state.
        If no new data arrives or decoding fails, returns the last known values.
        """

        # 1. Get the latest message string from the socket
        latest_message_str = self._poll_and_get_latest_message()

        # 2. If no message, return cached data
        if latest_message_str is None:
            return self.last_frames, self.last_remote_state

        # 3. Parse the JSON message
        observation = self._parse_observation_json(latest_message_str)

        # 4. If JSON parsing failed, return cached data
        if observation is None:
            return self.last_frames, self.last_remote_state

        # 5. Process the valid observation data
        try:
            new_frames, new_state = self._remote_state_from_obs(observation)

            # 6. Add local camera frame if enabled
            if self.config.use_local_camera and self.local_camera is not None:
                ret, frame = self.local_camera.read()
                if ret:
                    # Convert BGR to RGB
                    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    # Transpose from (H, W, C) to (W, H, C) format
                    frame = frame.transpose(1, 0, 2)
                    new_frames['local'] = frame

        except Exception as e:
            logging.error(f"Error processing observation data, serving last observation: {e}")
            return self.last_frames, self.last_remote_state

        self.last_frames = new_frames
        self.last_remote_state = new_state

        return new_frames, new_state

    def get_observation(self) -> dict[str, Any]:
        """
        Capture observations from the remote robot: current follower arm positions,
        present wheel speeds (converted to body-frame velocities: x, y, theta),
        and camera frames. Receives over ZMQ, matches LeKiwi's API format.
        """
        if not self.is_connected:
            raise DeviceNotConnectedError("LeKiwiClient is not connected. You need to run `robot.connect()`.")

        frames, state_dict = self._get_data()

        # Format observation to match LeKiwi's API and dataset requirements
        observation = {}

        # Add motor states at the root for dataset compatibility
        observation.update(state_dict)

        # Also add motor states under observation.state for API compatibility
        observation[OBS_STATE] = state_dict

        # Add camera frames with observation.images prefix
        for key, value in frames.items():
            observation[key] = value

        return observation

    def _from_keyboard_to_base_action(self, pressed_keys: np.ndarray):
        # Speed control
        if self.teleop_keys["speed_up"] in pressed_keys:
            self.speed_index = min(self.speed_index + 1, 2)
        if self.teleop_keys["speed_down"] in pressed_keys:
            self.speed_index = max(self.speed_index - 1, 0)
        speed_setting = self.speed_levels[self.speed_index]
        xy_speed = speed_setting["xy"]  # e.g. 0.1, 0.25, or 0.4
        theta_speed = speed_setting["theta"]  # e.g. 30, 60, or 90

        x_cmd = 0.0  # m/s forward/backward
        y_cmd = 0.0  # m/s lateral
        theta_cmd = 0.0  # deg/s rotation

        if self.teleop_keys["forward"] in pressed_keys:
            x_cmd += xy_speed
        if self.teleop_keys["backward"] in pressed_keys:
            x_cmd -= xy_speed
        if self.teleop_keys["left"] in pressed_keys:
            y_cmd += xy_speed
        if self.teleop_keys["right"] in pressed_keys:
            y_cmd -= xy_speed
        if self.teleop_keys["rotate_left"] in pressed_keys:
            theta_cmd += theta_speed
        if self.teleop_keys["rotate_right"] in pressed_keys:
            theta_cmd -= theta_speed
        return {
            "x.vel": x_cmd,
            "y.vel": y_cmd,
            "theta.vel": theta_cmd,
        }

    def configure(self):
        pass

    def send_action(self, action: dict[str, Any]) -> dict[str, Any]:
        """Command lekiwi to move to a target joint configuration. Translates to motor space + sends over ZMQ

        Args:
            action (np.ndarray): array containing the goal positions for the motors.

        Raises:
            RobotDeviceNotConnectedError: if robot is not connected.

        Returns:
            np.ndarray: the action sent to the motors, potentially clipped.
        """
        if not self._is_connected:
            raise DeviceNotConnectedError(
                "ManipulatorRobot is not connected. You need to run `robot.connect()`."
            )

        # Send action to host
        self.zmq_cmd_socket.send_string(json.dumps(action))
        
        # Wait for response with actual action sent (which might be clipped)
        try:
            response_msg = self.zmq_observation_socket.recv_string()
            response = json.loads(response_msg)
            if "action_sent" in response:
                return response["action_sent"]
        except zmq.Again:
            logging.warning("No response from host about action sent")
        
        # If no response received, return original action
        return action

    def disconnect(self) -> None:
        """Cleans ZMQ comms and releases camera"""
        if self.zmq_cmd_socket is not None:
            self.zmq_cmd_socket.close()
            self.zmq_cmd_socket = None

        if self.zmq_observation_socket is not None:
            self.zmq_observation_socket.close()
            self.zmq_observation_socket = None

        if self.zmq_context is not None:
            self.zmq_context.term()
            self.zmq_context = None

        if self.local_camera is not None:
            self.local_camera.release()
            self.local_camera = None

        self._is_connected = False
