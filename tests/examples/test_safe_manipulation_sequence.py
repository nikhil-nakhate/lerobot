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

"""Hardware-free tests for the XLeRobot safe manipulation sequence.

The script lives in ``examples/`` which is not an importable package, so it is
loaded by file path. None of these tests touch real hardware.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

_MODULE_PATH = Path(__file__).resolve().parents[2] / "examples" / "xlerobot" / "safe_manipulation_sequence.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("safe_manipulation_sequence", _MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    # Register before exec so dataclasses can resolve the module via sys.modules
    # (required because of `from __future__ import annotations`).
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sms = _load_module()


# --------------------------------------------------------------------------- #
# US-001 - safety validation
# --------------------------------------------------------------------------- #
def test_default_constants_pass_validation():
    # Should not raise with the shipped Conservative profile.
    sms.validate_safety_constants()


def test_default_invariants_hold():
    assert sms.BASE_DISTANCE_M <= sms.BASE_DISTANCE_CEIL_M
    assert 0 < sms.BASE_SPEED_MS <= sms.BASE_SPEED_CEIL_MS
    assert sms.ARM_LIFT_DELTA <= sms.ARM_LIFT_DELTA_CEIL
    assert sms.MAX_RELATIVE_TARGET >= 1


@pytest.mark.parametrize(
    "kwargs",
    [
        {"base_distance_m": 0.5},  # too far
        {"base_speed_ms": 0.5},  # too fast
        {"arm_lift_delta": 100.0},  # too big a lift
        {"max_relative_target": 0},  # clamp disabled
        {"base_distance_m": 0.0},  # zero / non-positive
    ],
)
def test_out_of_range_constants_rejected(kwargs):
    with pytest.raises(ValueError):
        sms.validate_safety_constants(**kwargs)


# --------------------------------------------------------------------------- #
# US-002 / US-003 - pure planner
# --------------------------------------------------------------------------- #
def test_arm_sequence_starts_and_ends_at_home():
    plan = sms.plan_sequence({"left_arm_shoulder_lift": 0.0, "right_arm_shoulder_lift": 0.0})
    for seq in plan.arm_targets.values():
        assert seq[0] == 0.0  # home
        assert seq[1] == sms.ARM_LIFT_DELTA  # up
        assert seq[2] == 0.0  # back home
        assert seq[0] == seq[2]


def test_arm_sequence_respects_nonzero_home():
    plan = sms.plan_sequence({"left_arm_shoulder_lift": 10.0, "right_arm_shoulder_lift": -5.0})
    assert plan.arm_targets["left_arm_shoulder_lift"] == [10.0, 10.0 + sms.ARM_LIFT_DELTA, 10.0]
    assert plan.arm_targets["right_arm_shoulder_lift"] == [-5.0, -5.0 + sms.ARM_LIFT_DELTA, -5.0]


def test_base_duration_is_distance_over_speed():
    plan = sms.plan_sequence({"left_arm_shoulder_lift": 0.0})
    assert plan.base_duration_s == pytest.approx(sms.BASE_DISTANCE_M / sms.BASE_SPEED_MS)


def test_base_legs_equal_and_opposite():
    plan = sms.plan_sequence({"left_arm_shoulder_lift": 0.0})
    fwd, back = plan.base_legs
    assert fwd.x_vel == pytest.approx(sms.BASE_SPEED_MS)
    assert back.x_vel == pytest.approx(-sms.BASE_SPEED_MS)
    assert fwd.x_vel == pytest.approx(-back.x_vel)
    assert fwd.duration_s == back.duration_s


def test_base_tick_count_matches_rate():
    plan = sms.plan_sequence({"left_arm_shoulder_lift": 0.0}, control_hz=50)
    for leg in plan.base_legs:
        assert leg.tick_count == round(leg.duration_s * 50)
    # Default conservative profile: 0.5 s * 50 Hz = 25 ticks.
    assert plan.base_legs[0].tick_count == 25


def test_expected_default_plan_shape():
    plan = sms.plan_sequence({"left_arm_shoulder_lift": 0.0, "right_arm_shoulder_lift": 0.0})
    assert plan.arm_targets["left_arm_shoulder_lift"] == [0.0, 12.0, 0.0]
    legs = [(leg.x_vel, leg.duration_s, leg.tick_count) for leg in plan.base_legs]
    assert legs == [(0.10, 0.5, 25), (-0.10, 0.5, 25)]


# --------------------------------------------------------------------------- #
# Helpers / fakes
# --------------------------------------------------------------------------- #
class _RecordingRobot:
    """Fake robot recording calls; simulates perfect arm tracking."""

    def __init__(self, home_positions, raise_on_send_index=None):
        self._pos = {f"{j}.pos": v for j, v in home_positions.items()}
        self.actions = []
        self.calls = []
        self._raise_on = raise_on_send_index

    def connect(self):
        self.calls.append("connect")

    def get_observation(self):
        obs = dict(self._pos)
        obs.update({"x.vel": 0.0, "y.vel": 0.0, "theta.vel": 0.0})
        return obs

    def send_action(self, action):
        if self._raise_on is not None and len(self.actions) == self._raise_on:
            raise RuntimeError("boom (simulated mid-phase failure)")
        self.actions.append(action)
        self.calls.append("send_action")
        for k, v in action.items():
            if k.endswith(".pos"):
                self._pos[k] = v
        return action

    def stop_base(self):
        self.calls.append("stop_base")

    def disconnect(self):
        self.calls.append("disconnect")


def _no_sleep(_):
    return None


# --------------------------------------------------------------------------- #
# US-004 - dry-run executor never touches hardware
# --------------------------------------------------------------------------- #
def test_dry_run_exits_zero_and_skips_xlerobot(monkeypatch):
    monkeypatch.setattr(sms.time, "sleep", _no_sleep)

    # If the dry-run path constructed XLerobot this sentinel would fire.
    import lerobot.robots.xlerobot as xle

    def _boom(*a, **k):
        raise AssertionError("dry-run must not construct XLerobot")

    monkeypatch.setattr(xle, "XLerobot", _boom)

    lines = []
    rc = sms.main(["--dry-run"], log=lines.append)
    assert rc == 0
    text = "\n".join(lines)
    assert "DRY-RUN" in text
    assert "0.500" in text  # derived base duration is printed


def test_dry_run_simrobot_returns_to_home():
    home = dict.fromkeys(sms.ARM_JOINTS, 0.0)
    robot = sms.SimRobot(home, log=lambda *_: None)
    plan = sms.plan_sequence(home)
    sms.run_sequence(robot, plan, sleeper=_no_sleep, log=lambda *_: None)
    obs = robot.get_observation()
    for joint in sms.ARM_JOINTS:
        assert obs[f"{joint}.pos"] == pytest.approx(0.0, abs=sms.POS_TOLERANCE)


# --------------------------------------------------------------------------- #
# US-005 - execute path uses the driver correctly
# --------------------------------------------------------------------------- #
def test_execute_only_commands_shoulder_lift_and_zero_lateral(monkeypatch):
    home = dict.fromkeys(sms.ARM_JOINTS, 0.0)
    fake = _RecordingRobot(home)

    class _FakeConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    monkeypatch.setattr(sms.time, "sleep", _no_sleep)
    # Patch the lazy import target.
    import lerobot.robots.xlerobot as xle

    monkeypatch.setattr(xle, "XLerobot", lambda config: fake)
    monkeypatch.setattr(xle, "XLerobotConfig", _FakeConfig)

    rc = sms.main(["--execute", "--yes"], log=lambda *_: None)
    assert rc == 0

    pos_keys = {k for a in fake.actions for k in a if k.endswith(".pos")}
    assert pos_keys == {"left_arm_shoulder_lift.pos", "right_arm_shoulder_lift.pos"}

    # Base actions never command lateral or rotational velocity.
    for a in fake.actions:
        if "x.vel" in a:
            assert a["y.vel"] == 0.0
            assert a["theta.vel"] == 0.0

    # stop_base() is called after each base leg (2 legs) plus the safety finally.
    assert fake.calls.count("stop_base") >= 2
    assert fake.calls[-1] == "disconnect"


def test_execute_sets_max_relative_target(monkeypatch):
    home = dict.fromkeys(sms.ARM_JOINTS, 0.0)
    fake = _RecordingRobot(home)
    captured = {}

    class _FakeConfig:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(sms.time, "sleep", _no_sleep)
    import lerobot.robots.xlerobot as xle

    monkeypatch.setattr(xle, "XLerobot", lambda config: fake)
    monkeypatch.setattr(xle, "XLerobotConfig", _FakeConfig)

    sms.main(["--execute", "--yes"], log=lambda *_: None)
    assert captured["max_relative_target"] == sms.MAX_RELATIVE_TARGET


# --------------------------------------------------------------------------- #
# US-006 - guaranteed safe shutdown
# --------------------------------------------------------------------------- #
def test_execute_failure_still_stops_and_disconnects(monkeypatch):
    home = dict.fromkeys(sms.ARM_JOINTS, 0.0)
    fake = _RecordingRobot(home, raise_on_send_index=1)  # fail mid arm phase

    class _FakeConfig:
        def __init__(self, **kwargs):
            pass

    monkeypatch.setattr(sms.time, "sleep", _no_sleep)
    import lerobot.robots.xlerobot as xle

    monkeypatch.setattr(xle, "XLerobot", lambda config: fake)
    monkeypatch.setattr(xle, "XLerobotConfig", _FakeConfig)

    with pytest.raises(RuntimeError):
        sms.main(["--execute", "--yes"], log=lambda *_: None)

    # Even on failure, the safety finally ran in order.
    assert "stop_base" in fake.calls
    assert fake.calls[-1] == "disconnect"


# --------------------------------------------------------------------------- #
# CLI guard rails
# --------------------------------------------------------------------------- #
def test_arms_only_and_base_only_conflict():
    rc = sms.main(["--arms-only", "--base-only"], log=lambda *_: None)
    assert rc == 2
