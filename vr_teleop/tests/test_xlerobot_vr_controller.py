"""Deterministic, no-hardware tests for the VR -> XLerobot action mapping."""

import math

import pytest

from lerobot.model.SO101Robot import SO101Kinematics
from lerobot_vr_teleop.xlerobot_vr_controller import (
    ARM_JOINTS,
    VRMappingConfig,
    XLeRobotVRController,
)

STATE_KEYS = (
    [f"left_arm_{j}.pos" for j in ARM_JOINTS]
    + [f"right_arm_{j}.pos" for j in ARM_JOINTS]
    + ["head_motor_1.pos", "head_motor_2.pos"]
)


def make_obs(value: float = 0.0) -> dict:
    return dict.fromkeys(STATE_KEYS, value)


def goal(
    *,
    valid=True,
    pos=(0.0, 0.0, 0.0),
    wrist_flex=0.0,
    wrist_roll=0.0,
    trigger=0.0,
    tx=0.0,
    ty=0.0,
):
    return {
        "valid": valid,
        "target_position": list(pos) if pos is not None else None,
        "wrist_flex_deg": wrist_flex,
        "wrist_roll_deg": wrist_roll,
        "gripper_closed": None,
        "trigger": trigger,
        "thumbstick_x": tx,
        "thumbstick_y": ty,
    }


def empty():
    return goal(valid=False, pos=None)


def test_reset_to_zero_commands_zero_pose():
    obs = make_obs(0.0)
    ctrl = XLeRobotVRController(obs, kp=1.0)
    action = ctrl.reset_to_zero(obs)
    for key in [f"right_arm_{j}.pos" for j in ARM_JOINTS]:
        assert action[key] == pytest.approx(0.0)
    assert action["x.vel"] == 0.0
    assert action["y.vel"] == 0.0
    assert action["theta.vel"] == 0.0


def test_first_valid_frame_seeds_baseline_without_jump():
    obs = make_obs(0.0)
    ctrl = XLeRobotVRController(obs, enable_left=False, enable_head=False, enable_base=False, kp=1.0)
    arm = ctrl.arms["right"]

    structured = {"right": goal(pos=(0.3, 0.2, 0.1), trigger=1.0)}
    action = ctrl.goals_to_action(structured, obs)

    # First frame only seeds the baseline; targets stay at the zero pose.
    assert arm.prev_vr_pos == [0.3, 0.2, 0.1]
    for j in ARM_JOINTS:
        assert arm.target_positions[j] == pytest.approx(0.0)
    for key in [f"right_arm_{j}.pos" for j in ARM_JOINTS]:
        assert action[key] == pytest.approx(0.0)


def test_wrist_flex_coupling_holds_after_motion():
    obs = make_obs(0.0)
    ctrl = XLeRobotVRController(obs, enable_left=False, enable_head=False, enable_base=False, kp=1.0)
    arm = ctrl.arms["right"]

    ctrl.goals_to_action({"right": goal(pos=(0.0, 0.0, 0.0))}, obs)  # seed
    ctrl.goals_to_action({"right": goal(pos=(0.0, 0.01, -0.01), wrist_flex=5.0)}, obs)  # move

    tp = arm.target_positions
    assert tp["wrist_flex"] == pytest.approx(-tp["shoulder_lift"] - tp["elbow_flex"] + arm.pitch)


def test_gripper_threshold():
    obs = make_obs(0.0)
    ctrl = XLeRobotVRController(obs, enable_left=False, enable_head=False, enable_base=False, kp=1.0)
    arm = ctrl.arms["right"]
    m = ctrl.mapping

    ctrl.goals_to_action({"right": goal(pos=(0.0, 0.0, 0.0))}, obs)  # seed

    ctrl.goals_to_action({"right": goal(pos=(0.0, 0.0, 0.0), trigger=0.6)}, obs)
    assert arm.target_positions["gripper"] == pytest.approx(m.gripper_closed)

    ctrl.goals_to_action({"right": goal(pos=(0.0, 0.0, 0.0), trigger=0.4)}, obs)
    assert arm.target_positions["gripper"] == pytest.approx(m.gripper_open)


def test_base_thumbstick_signs():
    obs = make_obs(0.0)
    ctrl = XLeRobotVRController(
        obs, enable_left=False, enable_right=False, enable_head=False, enable_base=True
    )
    m = ctrl.mapping

    # Stick up (-y) -> forward (+x.vel); stick right (+x) -> rotate right (-theta).
    action = ctrl.goals_to_action({"right": goal(tx=0.8, ty=-0.8)}, obs)
    assert action["x.vel"] == pytest.approx(m.base_xy_speed)
    assert action["theta.vel"] == pytest.approx(-m.base_theta_speed)

    # Stick down (+y) -> backward (-x.vel); stick left (-x) -> rotate left (+theta).
    action = ctrl.goals_to_action({"right": goal(tx=-0.8, ty=0.8)}, obs)
    assert action["x.vel"] == pytest.approx(-m.base_xy_speed)
    assert action["theta.vel"] == pytest.approx(m.base_theta_speed)

    # Inside the deadzone -> no motion.
    action = ctrl.goals_to_action({"right": goal(tx=0.05, ty=0.05)}, obs)
    assert action["x.vel"] == 0.0
    assert action["theta.vel"] == 0.0


def test_head_thumbstick_steps():
    obs = make_obs(0.0)
    ctrl = XLeRobotVRController(
        obs, enable_left=False, enable_right=False, enable_head=True, enable_base=False, kp=1.0
    )
    m = ctrl.mapping

    ctrl.goals_to_action({"left": goal(tx=0.5, ty=-0.5)}, obs)
    assert ctrl.head.target_positions["head_motor_1"] == pytest.approx(m.head_degree_step)
    assert ctrl.head.target_positions["head_motor_2"] == pytest.approx(-m.head_degree_step)


def test_disabled_left_arm_absent_from_action():
    obs = make_obs(0.0)
    ctrl = XLeRobotVRController(obs, enable_left=False, enable_head=False, enable_base=False, kp=1.0)
    action = ctrl.goals_to_action({"right": goal(pos=(0.0, 0.0, 0.0))}, obs)
    assert not any(k.startswith("left_arm_") for k in action)
    assert all(k.startswith("right_arm_") for k in action)


@pytest.mark.parametrize("x,y", [(0.20, 0.10), (0.15, 0.15), (0.1629, 0.1131)])
def test_ik_deterministic_and_finite(x, y):
    # SO101Kinematics.inverse_kinematics is the IK the controller relies on. It must
    # be deterministic and return finite shoulder_lift/elbow_flex angles. (Note: the
    # library's forward_kinematics is NOT a strict inverse of inverse_kinematics, so
    # we do not assert an EE round-trip here.)
    kin = SO101Kinematics()
    j2a, j3a = kin.inverse_kinematics(x, y)
    j2b, j3b = kin.inverse_kinematics(x, y)
    assert (j2a, j3a) == (j2b, j3b)
    assert all(math.isfinite(v) for v in (j2a, j3a))


def test_ik_continuous_under_small_perturbation():
    # The control loop integrates EE position in small steps, so IK must vary
    # continuously: a tiny change in (x, y) must not cause a large joint jump.
    kin = SO101Kinematics()
    j2, j3 = kin.inverse_kinematics(0.16, 0.11)
    j2p, j3p = kin.inverse_kinematics(0.16 + 1e-3, 0.11 + 1e-3)
    assert abs(j2p - j2) < 5.0
    assert abs(j3p - j3) < 5.0
