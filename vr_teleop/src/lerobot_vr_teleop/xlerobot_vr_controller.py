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

"""Maps robot-agnostic VR goals to an :class:`~lerobot.robots.xlerobot.XLerobot`
action dict.

This consolidates the prototype's ``SimpleTeleopArm`` / ``SimpleHeadControl`` /
``get_vr_base_action`` logic into a single, robot-handle-free processor:

* It never calls ``robot.get_observation()`` or touches motor buses -- the caller
  passes the current observation in, and the processor returns an action dict.
* All the empirical scaling constants are centralized in :class:`VRMappingConfig`
  (with the prototype's exact values as defaults) instead of being scattered as
  magic numbers across two example scripts.
* Head and base each read a *distinct* controller's thumbstick by default (the
  prototype read the right thumbstick for both, so head and base moved together).

The arm end-effector control uses :class:`~lerobot.model.SO101Robot.SO101Kinematics`
2-link IK plus the wrist-coupling convention
``wrist_flex = -shoulder_lift - elbow_flex + pitch``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from lerobot.model.SO101Robot import SO101Kinematics

logger = logging.getLogger(__name__)

ARM_JOINTS = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]
HEAD_MOTORS = ["head_motor_1", "head_motor_2"]


def _clamp(value: float, limit: float) -> float:
    return max(-limit, min(limit, value))


@dataclass
class VRMappingConfig:
    """Empirical VR-to-robot mapping constants (defaults match the prototype)."""

    # Per-axis raw VR position gain (applied to frame-to-frame deltas, meters).
    vr_x_gain: float = 220.0  # shoulder/pan axis
    vr_y_gain: float = 70.0
    vr_z_gain: float = 70.0
    pos_scale: float = 0.01  # position sensitivity
    delta_limit: float = 0.01  # max EE delta per update (meters)

    # Wrist angle handling (degrees).
    angle_scale: float = 4.0
    angle_limit: float = 8.0  # max angle delta per update (degrees)
    pitch_limit: float = 90.0
    roll_limit: float = 90.0

    # shoulder_pan from VR x delta.
    pan_x_scale: float = 200.0
    pan_limit: float = 180.0
    pan_deadzone: float = 0.001

    # IK smoothing (0-1, lower = smoother).
    ik_alpha: float = 0.1

    # End-effector home position (meters) used as the IK reference at reset.
    home_x: float = 0.1629
    home_y: float = 0.1131

    # Gripper.
    gripper_open: float = 0.0
    gripper_closed: float = 45.0
    trigger_threshold: float = 0.5

    # Head thumbstick control (degrees per update).
    head_degree_step: float = 2.0
    head_deadzone: float = 0.1

    # Base thumbstick control.
    base_xy_speed: float = 0.1  # m/s (matches XLerobot "slow" speed level)
    base_theta_speed: float = 30.0  # deg/s
    base_deadzone: float = 0.2


class _ArmMapper:
    """Per-arm VR -> joint-target state machine with IK + wrist coupling."""

    def __init__(self, prefix: str, initial_obs: dict, kinematics: SO101Kinematics, mapping: VRMappingConfig, kp: float):
        self.prefix = prefix
        self.kinematics = kinematics
        self.mapping = mapping
        self.kp = kp
        self.reset(initial_obs)

    def reset(self, initial_obs: dict | None = None) -> None:
        m = self.mapping
        self.current_x = m.home_x
        self.current_y = m.home_y
        self.pitch = 0.0
        self.prev_vr_pos = None
        self.prev_wrist_flex = None
        self.prev_wrist_roll = None
        self.target_positions = dict.fromkeys(ARM_JOINTS, 0.0)

    def update(self, goal: dict) -> None:
        """Integrate one VR goal frame into ``self.target_positions``."""
        m = self.mapping
        if not goal.get("valid"):
            return
        pos = goal["target_position"]
        wrist_flex = goal.get("wrist_flex_deg")
        wrist_roll = goal.get("wrist_roll_deg")

        # Seed all baselines together on the first valid frame (single skip),
        # avoiding the prototype's three staggered early-returns.
        if self.prev_vr_pos is None:
            self.prev_vr_pos = pos
            self.prev_wrist_flex = wrist_flex
            self.prev_wrist_roll = wrist_roll
            return

        vr_x = (pos[0] - self.prev_vr_pos[0]) * m.vr_x_gain
        vr_y = (pos[1] - self.prev_vr_pos[1]) * m.vr_y_gain
        vr_z = (pos[2] - self.prev_vr_pos[2]) * m.vr_z_gain
        self.prev_vr_pos = pos

        delta_x = _clamp(vr_x * m.pos_scale, m.delta_limit)
        delta_y = _clamp(vr_y * m.pos_scale, m.delta_limit)
        delta_z = _clamp(vr_z * m.pos_scale, m.delta_limit)

        # VR Z maps to robot X (inverted); VR Y maps to robot Y.
        self.current_x += -delta_z
        self.current_y += delta_y

        # Wrist flex -> end-effector pitch (relative).
        if wrist_flex is not None and self.prev_wrist_flex is not None:
            delta_pitch = _clamp((wrist_flex - self.prev_wrist_flex) * m.angle_scale, m.angle_limit)
            self.pitch = _clamp(self.pitch + delta_pitch, m.pitch_limit)
            self.prev_wrist_flex = wrist_flex
        elif wrist_flex is not None:
            self.prev_wrist_flex = wrist_flex

        # Wrist roll (relative).
        if wrist_roll is not None and self.prev_wrist_roll is not None:
            delta_roll = _clamp((wrist_roll - self.prev_wrist_roll) * m.angle_scale, m.angle_limit)
            self.target_positions["wrist_roll"] = _clamp(
                self.target_positions["wrist_roll"] + delta_roll, m.roll_limit
            )
            self.prev_wrist_roll = wrist_roll
        elif wrist_roll is not None:
            self.prev_wrist_roll = wrist_roll

        # shoulder_pan from VR x delta.
        if abs(delta_x) > m.pan_deadzone:
            delta_pan = _clamp(delta_x * m.pan_x_scale, m.angle_limit)
            self.target_positions["shoulder_pan"] = _clamp(
                self.target_positions["shoulder_pan"] + delta_pan, m.pan_limit
            )

        # IK for shoulder_lift / elbow_flex, smoothed.
        try:
            joint2, joint3 = self.kinematics.inverse_kinematics(self.current_x, self.current_y)
            alpha = m.ik_alpha
            self.target_positions["shoulder_lift"] = (1 - alpha) * self.target_positions["shoulder_lift"] + alpha * joint2
            self.target_positions["elbow_flex"] = (1 - alpha) * self.target_positions["elbow_flex"] + alpha * joint3
        except Exception as e:
            logger.warning("[%s] VR IK failed: %s", self.prefix, e)

        # Wrist-flex coupling keeps the gripper orientation steady through the pitch.
        self.target_positions["wrist_flex"] = (
            -self.target_positions["shoulder_lift"] - self.target_positions["elbow_flex"] + self.pitch
        )

        # Gripper from trigger.
        if goal.get("trigger", 0.0) > m.trigger_threshold:
            self.target_positions["gripper"] = m.gripper_closed
        else:
            self.target_positions["gripper"] = m.gripper_open

    def p_control(self, current_obs: dict) -> dict:
        """Return ``{<prefix>_arm_<joint>.pos: cmd}`` via proportional control."""
        action = {}
        for joint in ARM_JOINTS:
            key = f"{self.prefix}_arm_{joint}.pos"
            current = current_obs[key]
            action[key] = current + self.kp * (self.target_positions[joint] - current)
        return action


class _HeadMapper:
    """Head pan/tilt from a thumbstick, with proportional control."""

    def __init__(self, initial_obs: dict, mapping: VRMappingConfig, kp: float):
        self.mapping = mapping
        self.kp = kp
        self.reset(initial_obs)

    def reset(self, initial_obs: dict | None = None) -> None:
        obs = initial_obs or {}
        self.target_positions = {m: obs.get(f"{m}.pos", 0.0) for m in HEAD_MOTORS}

    def update(self, goal: dict) -> None:
        m = self.mapping
        thumb_x = goal.get("thumbstick_x", 0.0)
        thumb_y = goal.get("thumbstick_y", 0.0)
        if abs(thumb_x) > m.head_deadzone:
            self.target_positions["head_motor_1"] += m.head_degree_step if thumb_x > 0 else -m.head_degree_step
        if abs(thumb_y) > m.head_deadzone:
            self.target_positions["head_motor_2"] += m.head_degree_step if thumb_y > 0 else -m.head_degree_step

    def p_control(self, current_obs: dict) -> dict:
        action = {}
        for motor in HEAD_MOTORS:
            key = f"{motor}.pos"
            current = current_obs.get(key, 0.0)
            action[key] = current + self.kp * (self.target_positions[motor] - current)
        return action


class _BaseMapper:
    """Holonomic base velocity from a thumbstick (direct velocity, no P-control)."""

    def __init__(self, mapping: VRMappingConfig):
        self.mapping = mapping

    def update(self, goal: dict) -> dict:
        m = self.mapping
        thumb_x = goal.get("thumbstick_x", 0.0)
        thumb_y = goal.get("thumbstick_y", 0.0)
        x_vel = 0.0
        y_vel = 0.0
        theta_vel = 0.0
        # Thumbstick up (-y) = forward, down (+y) = backward.
        if thumb_y < -m.base_deadzone:
            x_vel += m.base_xy_speed
        elif thumb_y > m.base_deadzone:
            x_vel -= m.base_xy_speed
        # Thumbstick right (+x) = rotate right (negative theta), left = rotate left.
        if thumb_x > m.base_deadzone:
            theta_vel -= m.base_theta_speed
        elif thumb_x < -m.base_deadzone:
            theta_vel += m.base_theta_speed
        return {"x.vel": x_vel, "y.vel": y_vel, "theta.vel": theta_vel}


class XLeRobotVRController:
    """Converts structured VR goals into an XLerobot action dict.

    Args:
        initial_obs: An XLerobot observation dict used to seed joint targets.
        enable_left / enable_right: Enable each arm.
        enable_head / enable_base: Enable head and base control.
        kp: Proportional gain for arm/head tracking.
        mapping: Tunable :class:`VRMappingConfig`.
        head_source / base_source: Which controller's thumbstick drives head and
            base (default: head from ``"left"``, base from ``"right"`` so they do
            not fight over the same stick).
    """

    def __init__(
        self,
        initial_obs: dict,
        *,
        enable_left: bool = True,
        enable_right: bool = True,
        enable_head: bool = True,
        enable_base: bool = True,
        kp: float = 1.0,
        mapping: VRMappingConfig | None = None,
        head_source: str = "left",
        base_source: str = "right",
    ):
        self.mapping = mapping or VRMappingConfig()
        self.enable_left = enable_left
        self.enable_right = enable_right
        self.enable_head = enable_head
        self.enable_base = enable_base
        self.head_source = head_source
        self.base_source = base_source

        self.arms: dict[str, _ArmMapper] = {}
        if enable_left:
            self.arms["left"] = _ArmMapper("left", initial_obs, SO101Kinematics(), self.mapping, kp)
        if enable_right:
            self.arms["right"] = _ArmMapper("right", initial_obs, SO101Kinematics(), self.mapping, kp)
        self.head = _HeadMapper(initial_obs, self.mapping, kp) if enable_head else None
        self.base = _BaseMapper(self.mapping) if enable_base else None

    @staticmethod
    def _empty_goal() -> dict:
        return {
            "valid": False,
            "target_position": None,
            "wrist_roll_deg": None,
            "wrist_flex_deg": None,
            "gripper_closed": None,
            "trigger": 0.0,
            "thumbstick_x": 0.0,
            "thumbstick_y": 0.0,
        }

    def goals_to_action(self, structured: dict, current_obs: dict) -> dict:
        """Update internal targets from ``structured`` goals and return an action."""
        action: dict[str, float] = {}
        for prefix, mapper in self.arms.items():
            mapper.update(structured.get(prefix) or self._empty_goal())
            action.update(mapper.p_control(current_obs))
        if self.head is not None:
            self.head.update(structured.get(self.head_source) or self._empty_goal())
            action.update(self.head.p_control(current_obs))
        if self.base is not None:
            action.update(self.base.update(structured.get(self.base_source) or self._empty_goal()))
        return action

    def reset_to_zero(self, current_obs: dict) -> dict:
        """Reset all internal state and return an action toward the zero pose."""
        action: dict[str, float] = {}
        for mapper in self.arms.values():
            mapper.reset(current_obs)
            action.update(mapper.p_control(current_obs))
        if self.head is not None:
            self.head.reset(current_obs)
            action.update(self.head.p_control(current_obs))
        if self.base is not None:
            action.update({"x.vel": 0.0, "y.vel": 0.0, "theta.vel": 0.0})
        return action
