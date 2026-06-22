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

"""A robot-agnostic WebXR/VR teleoperator built on the XLeVR stack.

``VRTeleop`` owns the lifecycle of the XLeVR WebSocket + HTTPS servers (run in a
dedicated background asyncio thread) and exposes the latest controller goals via
:meth:`get_action`. The goals are returned in their raw VR coordinate space
(meters/degrees) -- mapping them to a particular robot's joints is the job of a
downstream processor such as
:class:`~lerobot_vr_teleop.xlerobot_vr_controller.XLeRobotVRController`.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any

from lerobot.utils.errors import DeviceNotConnectedError
from lerobot.teleoperators.teleoperator import Teleoperator

from .config_vr_teleop import VRTeleopConfig
from .vr_monitor import VRMonitor

logger = logging.getLogger(__name__)

# The per-controller sub-feature schema returned by get_action() for each
# enabled controller. Values are the python types of each field.
_GOAL_FEATURE = {
    "valid": bool,
    "target_position": list,  # [x, y, z] in meters, or None when invalid
    "wrist_roll_deg": float,
    "wrist_flex_deg": float,
    "gripper_closed": bool,
    "trigger": float,
    "thumbstick_x": float,
    "thumbstick_y": float,
    "button_a": bool,  # right controller: A button; left controller: X button
    "button_b": bool,  # right controller: B button; left controller: Y button
    "buttons": dict,  # full {a,b,squeeze,thumbstick,menu} state
}


class VRTeleop(Teleoperator):
    config_class = VRTeleopConfig
    name = "vr_teleop"

    def __init__(self, config: VRTeleopConfig):
        super().__init__(config)
        self.config = config
        self._monitor: VRMonitor | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._monitor_future = None
        self._connected = False

    @property
    def _enabled_controllers(self) -> list[str]:
        controllers = []
        if self.config.enable_left:
            controllers.append("left")
        if self.config.enable_right:
            controllers.append("right")
        if self.config.enable_headset:
            controllers.append("headset")
        return controllers

    @property
    def action_features(self) -> dict:
        return {controller: dict(_GOAL_FEATURE) for controller in self._enabled_controllers}

    @property
    def feedback_features(self) -> dict:
        return {}

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def is_calibrated(self) -> bool:
        return True

    def connect(self, calibrate: bool = True) -> None:
        if self._connected:
            raise DeviceNotConnectedError(f"{self} is already connected.")

        self._monitor = VRMonitor(
            https_port=self.config.https_port,
            websocket_port=self.config.websocket_port,
            host_ip=self.config.host_ip,
            vr_to_robot_scale=self.config.vr_to_robot_scale,
            print_only=self.config.print_only,
            start_https_ui=self.config.start_https_ui,
            xlevr_root=self.config.xlevr_root,
        )

        # Run the XLeVR servers in a dedicated asyncio loop on a background thread.
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, name="vr-teleop-loop", daemon=True)
        self._thread.start()
        self._monitor_future = asyncio.run_coroutine_threadsafe(
            self._monitor.start_monitoring(), self._loop
        )

        # Block until the servers report running (or fail / time out).
        deadline = time.time() + self.config.server_start_timeout_s
        while time.time() < deadline:
            if self._monitor.is_running:
                break
            if self._monitor_future.done():
                break  # start_monitoring returned early => initialization failed
            time.sleep(0.05)

        if not self._monitor.is_running:
            self.disconnect()
            raise DeviceNotConnectedError(
                f"{self} failed to start the VR server within "
                f"{self.config.server_start_timeout_s}s (check the XLeVR submodule and SSL certs)."
            )

        self._connected = True
        logger.info("%s connected.", self)

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_forever()
        finally:
            self._loop.close()

    def calibrate(self) -> None:
        pass

    def configure(self) -> None:
        pass

    @staticmethod
    def _flatten_goal(goal) -> dict[str, Any]:
        """Convert an XLeVR ``ControlGoal`` (or ``None``) into a plain dict."""
        if goal is None:
            return {
                "valid": False,
                "target_position": None,
                "wrist_roll_deg": None,
                "wrist_flex_deg": None,
                "gripper_closed": None,
                "trigger": 0.0,
                "thumbstick_x": 0.0,
                "thumbstick_y": 0.0,
                "button_a": False,
                "button_b": False,
                "buttons": {},
            }
        metadata = goal.metadata or {}
        thumbstick = metadata.get("thumbstick", {}) or {}
        buttons = metadata.get("buttons", {}) or {}
        target_position = goal.target_position
        if target_position is not None:
            target_position = [float(v) for v in target_position]
        return {
            "valid": target_position is not None,
            "target_position": target_position,
            "wrist_roll_deg": goal.wrist_roll_deg,
            "wrist_flex_deg": goal.wrist_flex_deg,
            "gripper_closed": goal.gripper_closed,
            "trigger": float(metadata.get("trigger", 0.0) or 0.0),
            "thumbstick_x": float(thumbstick.get("x", 0.0) or 0.0),
            "thumbstick_y": float(thumbstick.get("y", 0.0) or 0.0),
            "button_a": bool(buttons.get("a", False)),
            "button_b": bool(buttons.get("b", False)),
            "buttons": dict(buttons),
        }

    def get_action(self) -> dict[str, Any]:
        if not self._connected or self._monitor is None:
            raise DeviceNotConnectedError(f"{self} is not connected.")
        dual = self._monitor.get_latest_goal_nowait()
        return {
            controller: self._flatten_goal(dual.get(controller) if dual else None)
            for controller in self._enabled_controllers
        }

    def send_feedback(self, feedback: dict[str, Any]) -> None:
        # No haptic feedback channel yet; reserved for future use.
        pass

    def disconnect(self) -> None:
        # Signal the monitor's command loop to exit; start_monitoring's finally
        # block stops the WS + HTTPS servers cleanly (freeing ports 8442/8443).
        if self._monitor is not None:
            self._monitor.is_running = False
        if self._monitor_future is not None:
            try:
                self._monitor_future.result(timeout=self.config.disconnect_timeout_s)
            except Exception as e:
                logger.warning("VR monitor shutdown did not complete cleanly: %s", e)
        if self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=self.config.disconnect_timeout_s)

        self._monitor = None
        self._monitor_future = None
        self._loop = None
        self._thread = None
        self._connected = False
        logger.info("%s disconnected.", self)
