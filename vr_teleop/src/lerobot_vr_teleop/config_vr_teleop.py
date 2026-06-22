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

from dataclasses import dataclass

from lerobot.teleoperators.config import TeleoperatorConfig


@TeleoperatorConfig.register_subclass("vr_teleop")
@dataclass
class VRTeleopConfig(TeleoperatorConfig):
    """Configuration for the WebXR-based :class:`VRTeleop` teleoperator.

    The teleoperator is robot-agnostic: it serves the XLeVR WebXR front-end to a
    headset browser and exposes the latest controller goals. Mapping those goals
    to a specific robot's action space is done downstream (see
    :class:`~lerobot_vr_teleop.xlerobot_vr_controller.XLeRobotVRController`).
    """

    # Network / server
    https_port: int = 8443
    websocket_port: int = 8442
    host_ip: str = "0.0.0.0"
    # Scale applied to raw VR positions by XLeVR before they reach us.
    vr_to_robot_scale: float = 1.0

    # Which controllers are surfaced in get_action().
    enable_left: bool = True
    enable_right: bool = True
    enable_headset: bool = True

    # Server behavior
    print_only: bool = False  # XLeVR print-only smoke mode (no goals queued)
    start_https_ui: bool = True  # serve the web-ui the headset browser loads
    server_start_timeout_s: float = 10.0
    disconnect_timeout_s: float = 5.0

    # Optional override for the XLeVR checkout; defaults to the in-repo submodule.
    xlevr_root: str | None = None
