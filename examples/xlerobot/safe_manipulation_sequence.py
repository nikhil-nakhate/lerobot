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

"""Run a deliberately tiny, safe demonstration sequence on the XLeRobot.

Both arms perform a small ``shoulder_lift`` up-then-down (returning to start) and
the mobile base performs a short forward-then-back move. Every motion is bounded
and self-reversing.

Safety model (see ``.ralph/specs/requirements.md`` for the full PRD):
  * Dry-run is the DEFAULT. Without ``--execute`` the script touches no hardware:
    it never opens serial ports and never calls ``robot.connect()``. It simulates
    the run and prints every planned action.
  * Real motion requires ``--execute`` plus an interactive confirmation.
  * Arm steps are clamped by the driver via ``max_relative_target``.
  * The base is velocity-controlled with no position feedback, so distance is
    open-loop (velocity x time); ``y.vel`` and ``theta.vel`` are always 0.0.
  * Every ``--execute`` run guarantees ``stop_base()`` then ``disconnect()`` in a
    ``finally`` block, including on exception and Ctrl-C.

Conservative safety profile:
    base distance 0.05 m @ 0.10 m/s  |  arm shoulder_lift delta ~12 units
    max_relative_target = 5          |  control 50 Hz, Kp 0.5

Usage:
    # Dry-run (default, no hardware)
    PYTHONPATH=src python examples/xlerobot/safe_manipulation_sequence.py

    # FIRST real run: calibrate once (interactive) and save it under --robot-id
    PYTHONPATH=src python examples/xlerobot/safe_manipulation_sequence.py \
        --execute --calibrate --robot-id xlerobot

    # SUBSEQUENT runs: restore the saved calibration non-interactively
    PYTHONPATH=src python examples/xlerobot/safe_manipulation_sequence.py \
        --execute --robot-id xlerobot

    # Override ports / isolate a subsystem
    PYTHONPATH=src python examples/xlerobot/safe_manipulation_sequence.py --execute \
        --port1 /dev/ttyACM0 --port2 /dev/ttyACM1
    PYTHONPATH=src python examples/xlerobot/safe_manipulation_sequence.py --arms-only
    PYTHONPATH=src python examples/xlerobot/safe_manipulation_sequence.py --base-only

Calibration:
    The driver stores calibration at
    ``~/.cache/huggingface/lerobot/calibration/robots/xlerobot/<robot-id>.json``.
    Pass ``--calibrate`` to (re)create it interactively; omit it to restore the
    saved file with no prompts. If no file exists and ``--calibrate`` is not given,
    the script aborts before any motion with instructions.
"""

from __future__ import annotations

import argparse
import builtins
import time
from contextlib import contextmanager
from dataclasses import dataclass, field

# --------------------------------------------------------------------------- #
# Safety parameters - SINGLE source of truth (Conservative profile).
# A reviewer must be able to confirm safety by reading this block alone.
# --------------------------------------------------------------------------- #
BASE_DISTANCE_M = 0.05  # ~2 inches of travel per leg
BASE_SPEED_MS = 0.10  # matches the driver's slowest preset
ARM_LIFT_DELTA = 12.0  # normalized-unit up/down on shoulder_lift
MAX_RELATIVE_TARGET = 5  # per-call arm step clamp applied inside the driver
CONTROL_HZ = 50  # control-loop rate
KP = 0.5  # P-control gain
POS_TOLERANCE = 2.0  # "reached target" threshold (normalized units)
PHASE_TIMEOUT_S = 8.0  # per arm sub-phase wall-clock cap
SETTLE_S = 0.5  # pause between phases

# Hard ceilings the constants above must never exceed.
BASE_DISTANCE_CEIL_M = 0.10
BASE_SPEED_CEIL_MS = 0.10
ARM_LIFT_DELTA_CEIL = 20.0

# The two joints this sequence drives (one per arm). Nothing else is commanded.
ARM_JOINTS = ("left_arm_shoulder_lift", "right_arm_shoulder_lift")

DEFAULT_PORT1 = "/dev/ttyACM0"  # bus1: left arm + head
DEFAULT_PORT2 = "/dev/ttyACM1"  # bus2: right arm + base
DEFAULT_ROBOT_ID = "xlerobot"  # calibration file is <robot-id>.json under the cache


# --------------------------------------------------------------------------- #
# Safety validation (US-001)
# --------------------------------------------------------------------------- #
def validate_safety_constants(
    *,
    base_distance_m: float = BASE_DISTANCE_M,
    base_speed_ms: float = BASE_SPEED_MS,
    arm_lift_delta: float = ARM_LIFT_DELTA,
    max_relative_target: int = MAX_RELATIVE_TARGET,
) -> None:
    """Assert that the motion magnitudes are within hard safety ceilings.

    Raises:
        ValueError: if any constant exceeds its ceiling. Callers must abort
            before any motion when this raises.
    """
    if not 0 < base_distance_m <= BASE_DISTANCE_CEIL_M:
        raise ValueError(f"BASE_DISTANCE_M={base_distance_m} must be in (0, {BASE_DISTANCE_CEIL_M}] m")
    if not 0 < base_speed_ms <= BASE_SPEED_CEIL_MS:
        raise ValueError(f"BASE_SPEED_MS={base_speed_ms} must be in (0, {BASE_SPEED_CEIL_MS}] m/s")
    if not 0 < arm_lift_delta <= ARM_LIFT_DELTA_CEIL:
        raise ValueError(f"ARM_LIFT_DELTA={arm_lift_delta} must be in (0, {ARM_LIFT_DELTA_CEIL}] units")
    if max_relative_target < 1:
        raise ValueError(f"MAX_RELATIVE_TARGET={max_relative_target} must be >= 1")


# --------------------------------------------------------------------------- #
# Pure planner - no I/O, no time, no robot (US-002)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class BaseLeg:
    """One open-loop base leg: hold ``x_vel`` for ``duration_s`` then stop."""

    x_vel: float
    duration_s: float
    tick_count: int
    label: str


@dataclass(frozen=True)
class Plan:
    """A fully resolved, hardware-free description of the sequence."""

    arm_targets: dict[str, list[float]]  # joint -> [home, up, home]
    base_legs: list[BaseLeg]  # [forward, back]
    base_duration_s: float
    control_hz: int = CONTROL_HZ
    control_period_s: float = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "control_period_s", 1.0 / self.control_hz)

    def arm_up_targets(self) -> dict[str, float]:
        return {joint: seq[1] for joint, seq in self.arm_targets.items()}

    def arm_home_targets(self) -> dict[str, float]:
        return {joint: seq[0] for joint, seq in self.arm_targets.items()}


def plan_sequence(
    home_positions: dict[str, float],
    *,
    arm_lift_delta: float = ARM_LIFT_DELTA,
    base_distance_m: float = BASE_DISTANCE_M,
    base_speed_ms: float = BASE_SPEED_MS,
    control_hz: int = CONTROL_HZ,
) -> Plan:
    """Build the ordered, self-reversing plan from each arm's home position.

    Args:
        home_positions: Maps each arm joint name (e.g. ``left_arm_shoulder_lift``)
            to its captured home value.
        arm_lift_delta: Up/down delta applied to each joint.
        base_distance_m: Open-loop distance per base leg.
        base_speed_ms: Base speed.
        control_hz: Control-loop rate (sets tick counts).

    Returns:
        A :class:`Plan`. Arm targets are ``[home, home+delta, home]`` per joint;
        base legs are forward then equal-and-opposite back. ``y.vel``/``theta.vel``
        are never produced here (the executor hard-codes them to 0.0).
    """
    arm_targets = {joint: [home, home + arm_lift_delta, home] for joint, home in home_positions.items()}

    duration_s = base_distance_m / base_speed_ms
    tick_count = round(duration_s * control_hz)
    base_legs = [
        BaseLeg(x_vel=+base_speed_ms, duration_s=duration_s, tick_count=tick_count, label="forward"),
        BaseLeg(x_vel=-base_speed_ms, duration_s=duration_s, tick_count=tick_count, label="back"),
    ]

    return Plan(
        arm_targets=arm_targets,
        base_legs=base_legs,
        base_duration_s=duration_s,
        control_hz=control_hz,
    )


# --------------------------------------------------------------------------- #
# Dry-run stand-in robot (US-004)
# --------------------------------------------------------------------------- #
class SimRobot:
    """No-hardware stand-in used in dry-run.

    Prints every action and simulates perfect tracking so the executor's control
    loops terminate. It intentionally has NO ``connect()`` - dry-run must never
    connect to hardware.
    """

    def __init__(self, home_positions: dict[str, float], log=print):
        self._pos = {f"{joint}.pos": value for joint, value in home_positions.items()}
        self._log = log

    def get_observation(self) -> dict[str, float]:
        obs = dict(self._pos)
        obs.update({"x.vel": 0.0, "y.vel": 0.0, "theta.vel": 0.0})
        return obs

    def send_action(self, action: dict[str, float]) -> dict[str, float]:
        self._log(f"    [SIM] send_action {_fmt_action(action)}")
        for key, value in action.items():
            if key.endswith(".pos"):
                self._pos[key] = value  # simulate perfect tracking
        return action

    def stop_base(self) -> None:
        self._log("    [SIM] stop_base()")

    def disconnect(self) -> None:  # not called in dry-run; present for symmetry
        self._log("    [SIM] disconnect()")


def _fmt_action(action: dict[str, float]) -> str:
    return "{" + ", ".join(f"{k}={v:.4f}" for k, v in action.items()) + "}"


# --------------------------------------------------------------------------- #
# Executor (US-004 dry-run / US-005 execute / US-006 safe shutdown)
# --------------------------------------------------------------------------- #
def _drive_arm_to(
    robot,
    target_map: dict[str, float],
    *,
    kp: float,
    pos_tolerance: float,
    phase_timeout_s: float,
    period_s: float,
    label: str,
    sleeper=None,
    monotonic=None,
    log=print,
) -> None:
    """P-control both arm joints toward ``target_map`` until reached or timeout."""
    sleeper = time.sleep if sleeper is None else sleeper
    monotonic = time.monotonic if monotonic is None else monotonic
    log(f"  Arm phase: {label} -> { {k: round(v, 2) for k, v in target_map.items()} }")
    deadline = monotonic() + phase_timeout_s
    while True:
        obs = robot.get_observation()
        action = {}
        max_err = 0.0
        for joint, target in target_map.items():
            current = obs[f"{joint}.pos"]
            error = target - current
            max_err = max(max_err, abs(error))
            action[f"{joint}.pos"] = current + kp * error
        robot.send_action(action)

        if max_err <= pos_tolerance:
            break
        if monotonic() >= deadline:
            log(f"  WARNING: arm phase '{label}' hit timeout ({phase_timeout_s}s); continuing")
            break
        sleeper(period_s)


def _run_base_leg(robot, leg: BaseLeg, *, period_s: float, sleeper=None, log=print) -> None:
    """Hold a single-DOF base velocity for the leg's ticks, then stop the base."""
    sleeper = time.sleep if sleeper is None else sleeper
    log(
        f"  Base phase: {leg.label} x.vel={leg.x_vel:+.3f} m/s for "
        f"{leg.duration_s:.3f}s ({leg.tick_count} ticks), y.vel=0, theta.vel=0"
    )
    action = {"x.vel": leg.x_vel, "y.vel": 0.0, "theta.vel": 0.0}
    for _ in range(leg.tick_count):
        robot.send_action(action)
        sleeper(period_s)
    robot.stop_base()


def run_sequence(
    robot,
    plan: Plan,
    *,
    do_arms: bool = True,
    do_base: bool = True,
    kp: float = KP,
    pos_tolerance: float = POS_TOLERANCE,
    phase_timeout_s: float = PHASE_TIMEOUT_S,
    settle_s: float = SETTLE_S,
    sleeper=None,
    monotonic=None,
    log=print,
) -> None:
    """Execute the ordered sequence against ``robot`` (real or simulated).

    The robot only needs ``get_observation``, ``send_action`` and ``stop_base``.
    Connection/teardown is the caller's responsibility (see :func:`main`).
    """
    sleeper = time.sleep if sleeper is None else sleeper
    monotonic = time.monotonic if monotonic is None else monotonic
    period_s = plan.control_period_s

    if do_arms:
        _drive_arm_to(
            robot,
            plan.arm_up_targets(),
            kp=kp,
            pos_tolerance=pos_tolerance,
            phase_timeout_s=phase_timeout_s,
            period_s=period_s,
            label="up",
            sleeper=sleeper,
            monotonic=monotonic,
            log=log,
        )
        _drive_arm_to(
            robot,
            plan.arm_home_targets(),
            kp=kp,
            pos_tolerance=pos_tolerance,
            phase_timeout_s=phase_timeout_s,
            period_s=period_s,
            label="down (home)",
            sleeper=sleeper,
            monotonic=monotonic,
            log=log,
        )

    if do_base:
        for leg in plan.base_legs:
            sleeper(settle_s)
            _run_base_leg(robot, leg, period_s=period_s, sleeper=sleeper, log=log)

    if do_arms:
        # Idempotent final ensure-home (no-op if already there).
        _drive_arm_to(
            robot,
            plan.arm_home_targets(),
            kp=kp,
            pos_tolerance=pos_tolerance,
            phase_timeout_s=phase_timeout_s,
            period_s=period_s,
            label="teardown ensure-home",
            sleeper=sleeper,
            monotonic=monotonic,
            log=log,
        )


# --------------------------------------------------------------------------- #
# Plan printing
# --------------------------------------------------------------------------- #
def print_plan(plan: Plan, *, execute: bool, do_arms: bool, do_base: bool, log=print) -> None:
    mode = "EXECUTE (real motion)" if execute else "DRY-RUN (no hardware)"
    log("=" * 70)
    log(f"XLeRobot Safe Manipulation Sequence - {mode}")
    log("=" * 70)
    log("Safety profile (conservative):")
    log(f"  base distance       : {BASE_DISTANCE_M} m @ {BASE_SPEED_MS} m/s")
    log(f"  base leg duration   : {plan.base_duration_s:.3f} s (= distance / speed)")
    log(f"  arm lift delta      : {ARM_LIFT_DELTA} normalized units on shoulder_lift")
    log(f"  max_relative_target : {MAX_RELATIVE_TARGET} (per-call arm clamp)")
    log(f"  control rate / Kp   : {plan.control_hz} Hz / {KP}")
    log("Plan:")
    if do_arms:
        for joint, seq in plan.arm_targets.items():
            log(f"  {joint}: home={seq[0]:.2f} -> up={seq[1]:.2f} -> home={seq[2]:.2f}")
    else:
        log("  arms: SKIPPED (--base-only)")
    if do_base:
        for leg in plan.base_legs:
            log(
                f"  base {leg.label}: x.vel={leg.x_vel:+.3f} m/s for "
                f"{leg.duration_s:.3f}s ({leg.tick_count} ticks)"
            )
    else:
        log("  base: SKIPPED (--arms-only)")
    log("-" * 70)


# --------------------------------------------------------------------------- #
# CLI / main (US-001, US-004, US-005, US-006)
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a tiny, safe XLeRobot arm+base demo (dry-run by default).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Drive the REAL robot. Without this flag the script only simulates.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Explicitly request dry-run (this is already the default).",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the interactive confirmation prompt in --execute mode.",
    )
    parser.add_argument("--port1", default=DEFAULT_PORT1, help="bus1 port (left arm + head)")
    parser.add_argument("--port2", default=DEFAULT_PORT2, help="bus2 port (right arm + base)")
    parser.add_argument(
        "--robot-id",
        default=DEFAULT_ROBOT_ID,
        help="Robot id selecting the calibration file <robot-id>.json (default: %(default)s).",
    )
    parser.add_argument(
        "--calibrate",
        action="store_true",
        help="Run interactive calibration and save it, instead of restoring a saved file.",
    )
    parser.add_argument("--arms-only", action="store_true", help="Run only the arm motion.")
    parser.add_argument("--base-only", action="store_true", help="Run only the base motion.")
    return parser


def _run_dry(args, *, log=print) -> int:
    """Dry-run path: never imports/opens hardware, never calls connect()."""
    do_arms = not args.base_only
    do_base = not args.arms_only
    home_positions = dict.fromkeys(ARM_JOINTS, 0.0)
    plan = plan_sequence(home_positions)
    print_plan(plan, execute=False, do_arms=do_arms, do_base=do_base, log=log)
    robot = SimRobot(home_positions, log=log)
    run_sequence(robot, plan, do_arms=do_arms, do_base=do_base, log=log)
    log("Dry-run complete. No hardware was touched. Re-run with --execute to move the robot.")
    return 0


@contextmanager
def _auto_input(responses, *, log=print):
    """Temporarily answer ``input()`` prompts automatically.

    Used ONLY to auto-accept the driver's single "restore calibration?" prompt so
    re-runs are non-interactive. Never wrap an interactive *calibration* in this -
    the calibration steps need real human input.
    """
    original = builtins.input
    it = iter(responses)

    def _fake_input(prompt: str = "") -> str:
        try:
            reply = next(it)
        except StopIteration:
            reply = ""
        log(f"{prompt}{reply!r}  [auto]")
        return reply

    builtins.input = _fake_input
    try:
        yield
    finally:
        builtins.input = original


def _connect_with_calibration(robot, *, calibrate: bool, log=print) -> None:
    """Connect the robot, either calibrating fresh or restoring a saved file.

    Args:
        robot: An ``XLerobot`` instance (already constructed with the desired id).
        calibrate: If True, run the driver's interactive calibration and save it.
            If False, restore the existing calibration file non-interactively.

    Raises:
        SystemExit: if restore is requested but no calibration file exists, or if
            the robot is not calibrated after connecting.
    """
    fpath = robot.calibration_fpath
    if calibrate:
        log(f"Calibration: running INTERACTIVE calibration; will be saved to {fpath}")
        log("Follow the on-screen prompts (move each joint through its range).")
        robot.connect(calibrate=True)
    elif fpath.is_file():
        log(f"Calibration: restoring from {fpath} (no recalibration).")
        # The restore branch of the driver asks one yes/ENTER question; auto-accept.
        with _auto_input([""], log=log):
            robot.connect(calibrate=False)
    else:
        raise SystemExit(
            f"No calibration file found at {fpath}.\n"
            f"Calibrate once first, e.g.:\n"
            f"  PYTHONPATH=src python examples/xlerobot/safe_manipulation_sequence.py "
            f"--execute --calibrate --robot-id {robot.id}"
        )

    if not robot.is_calibrated:
        raise SystemExit("Robot reports NOT calibrated after connect; aborting before any motion.")


def _run_execute(args, *, log=print, input_fn=input) -> int:
    """Execute path: connect, run, and ALWAYS stop_base()+disconnect() in finally."""
    # Imported here so dry-run has no hardware import dependency.
    from lerobot.robots.xlerobot import XLerobot, XLerobotConfig

    do_arms = not args.base_only
    do_base = not args.arms_only

    config = XLerobotConfig(
        id=args.robot_id,
        port1=args.port1,
        port2=args.port2,
        max_relative_target=MAX_RELATIVE_TARGET,
    )
    robot = XLerobot(config)

    # Pre-connect calibration gate (no hardware action yet, so no finally needed).
    if not args.calibrate and not robot.calibration_fpath.is_file():
        log(f"No calibration file found at {robot.calibration_fpath}.")
        log("Run once with --calibrate to create it, e.g.:")
        log(
            f"  PYTHONPATH=src python examples/xlerobot/safe_manipulation_sequence.py "
            f"--execute --calibrate --robot-id {args.robot_id}"
        )
        return 2

    log("!" * 70)
    log("WARNING: --execute will PHYSICALLY MOVE the robot.")
    log("Ensure the robot is connected and on a clear ~0.5 m surface.")
    if args.calibrate:
        log("Mode: CALIBRATE then run (interactive calibration follows).")
    else:
        log(f"Mode: restore calibration '{args.robot_id}' then run.")
    log("!" * 70)
    if not args.yes:
        reply = input_fn("Type ENTER to proceed, or Ctrl-C to abort: ")
        if reply.strip().lower() in {"n", "no", "q", "quit"}:
            log("Aborted by operator.")
            return 1

    try:
        _connect_with_calibration(robot, calibrate=args.calibrate, log=log)
        obs = robot.get_observation()
        home_positions = {joint: obs[f"{joint}.pos"] for joint in ARM_JOINTS}
        plan = plan_sequence(home_positions)
        print_plan(plan, execute=True, do_arms=do_arms, do_base=do_base, log=log)
        run_sequence(robot, plan, do_arms=do_arms, do_base=do_base, log=log)
        log("Execute complete. Robot returned to its starting state.")
        return 0
    except KeyboardInterrupt:
        log("\nInterrupted - stopping base and disconnecting safely.")
        return 130
    finally:
        # Guaranteed safe shutdown on every path (US-006). Best-effort: never let
        # a teardown error mask the original outcome or crash an aborted connect.
        if getattr(robot, "is_connected", False):
            try:
                robot.stop_base()
            except Exception as exc:  # noqa: BLE001
                log(f"warning: stop_base() during teardown failed: {exc}")
            try:
                robot.disconnect()
            except Exception as exc:  # noqa: BLE001
                log(f"warning: disconnect() during teardown failed: {exc}")


def main(argv: list[str] | None = None, *, log=print, input_fn=input) -> int:
    args = build_parser().parse_args(argv)

    try:
        validate_safety_constants()
    except ValueError as exc:
        log(f"SAFETY CHECK FAILED: {exc}")
        return 2

    if args.arms_only and args.base_only:
        log("ERROR: --arms-only and --base-only are mutually exclusive.")
        return 2

    if args.execute:
        return _run_execute(args, log=log, input_fn=input_fn)
    return _run_dry(args, log=log)


if __name__ == "__main__":
    raise SystemExit(main())
