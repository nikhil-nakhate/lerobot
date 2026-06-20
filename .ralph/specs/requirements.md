# PRD — XLeRobot Safe Manipulation Sequence

> Single source of truth for the Ralph loop. The loop reads this file plus
> `.ralph/fix_plan.md` and implements one prioritized item per iteration.

## 1. Overview

Build a single, self-contained Python script that runs a **deliberately tiny,
safe demonstration sequence** on the XLeRobot platform: a small up/down motion of
**both arms** and a short **forward-then-back motion of the mobile base**, with
every motion returning to its exact starting state.

The script must be **safe by default**: it runs in a no-hardware **dry-run /
simulation** mode unless the operator explicitly passes `--execute`. This lets the
Ralph loop (and CI) validate the full logic with no robot attached, while a human
opts in to real motion only when the robot is plugged in, calibrated, and on a
clear surface.

**Why this exists:** to give a known-good, minimal "is the robot alive and
behaving?" routine that is impossible to confuse with a large or dangerous move.
It is a smoke test for the hardware + the `XLerobot` driver, not a task policy.

## 2. Goals

- G1. One command runs a complete, bounded arm + base sequence that always
  returns the robot to its starting state.
- G2. Dry-run is the default; real motion requires an explicit `--execute` flag.
- G3. Motion magnitudes are conservative and centrally configured (one constants
  block), so a reviewer can confirm safety at a glance.
- G4. The motion *planning* logic is pure and unit-tested with no hardware.
- G5. Any exit path (normal, exception, Ctrl-C) leaves the base stopped and
  torque released.

## 3. Non-Goals

- N1. No closed-loop base odometry or SLAM — base distance is **open-loop**
  (velocity × time); small drift is acceptable and expected.
- N2. No inverse kinematics, grasping, or object interaction. The gripper is not
  actuated.
- N3. No teleoperation, dataset recording, cameras, policies, or training.
- N4. No head-motor motion.
- N5. Not a general motion library — it is one fixed, hard-bounded routine.
- N6. No changes to the `XLerobot` driver or any existing `src/lerobot` code.

## 4. Target Hardware & Driver Facts (verified against the codebase)

Source: `src/lerobot/robots/xlerobot/xlerobot.py` and `config_xlerobot.py`.

- Construction:
  ```python
  from lerobot.robots.xlerobot import XLerobot, XLerobotConfig
  ```
- Two Feetech buses:
  - **bus1** (`config.port1`, default `/dev/ttyACM0`): left arm (6 motors) + head (2 motors).
  - **bus2** (`config.port2`, default `/dev/ttyACM1`): right arm (6 motors) + base (3 omni-wheels).
- **Arm joints are position-controlled.** Action/observation keys are
  `"<side>_arm_<joint>.pos"`, e.g. `left_arm_shoulder_lift.pos`,
  `right_arm_shoulder_lift.pos`. `shoulder_lift` is the natural "raise/lower the
  whole arm" joint and is the joint this sequence uses.
- **Units:** `use_degrees=False` by default → arm joints are normalized to the
  `RANGE_M100_100` range (≈ -100..100); the gripper uses `RANGE_0_100`. Deltas in
  this PRD are expressed in those normalized units. (Do **not** assume degrees.)
- **The base is velocity-controlled.** There is no base position feedback. Action
  keys are `"x.vel"` (m/s, forward+), `"y.vel"` (m/s, lateral+), `"theta.vel"`
  (deg/s, yaw). Internally converted to wheel velocities by `_body_to_wheel_raw`.
- **Observations** mirror the action keys: arm/head as `*.pos`, base as
  `x.vel` / `y.vel` / `theta.vel`.
- **Safety clamp already in the driver:** `send_action` applies
  `ensure_safe_goal_position(...)` to all arm/head position targets **iff**
  `config.max_relative_target is not None`. It caps the per-call change to
  `±max_relative_target` per joint (`src/lerobot/robots/utils.py`). This sequence
  MUST set `max_relative_target` so each commanded step is hard-limited.
- **`robot.stop_base()`** writes zero velocity to all three wheels.
- **`robot.disconnect()`** calls `stop_base()` then disconnects both buses;
  with `disable_torque_on_disconnect=True` (the default) it releases torque.
- **`robot.connect()` is interactive**: if a calibration file exists it prompts
  the operator (ENTER to restore / `c` to recalibrate). This only matters in
  `--execute` mode. Dry-run must never call `connect()`.

## 5. The Sequence (exact behavior)

Run in this fixed order. Each phase is bounded and self-reversing.

1. **Setup**
   - Parse flags. Build `XLerobotConfig` with `max_relative_target` set (see §6).
   - Dry-run: do NOT connect; synthesize a start observation (all `*.pos = 0.0`).
   - Execute: `robot.connect()`, then read the start observation once and cache
     each arm's `shoulder_lift.pos` as that arm's home.

2. **Arm phase — both arms, small up then down**
   - Targets are computed per arm relative to its own cached home:
     `up_target = home + ARM_LIFT_DELTA`, then back to `home`.
   - Drive with a P-control loop at `CONTROL_HZ` (pattern mirrors
     `examples/4_xlerobot_teleop_keyboard.py`: `cmd = current + KP*(target-current)`),
     commanding `left_arm_shoulder_lift.pos` and `right_arm_shoulder_lift.pos`
     **together** in the same action dict.
   - Hold at the up target until both arms are within `POS_TOLERANCE` of it OR
     `PHASE_TIMEOUT_S` elapses, then ramp back to home with the same tolerance/timeout.
   - No other arm joints, no head, no gripper are commanded.

3. **Settle pause** of `SETTLE_S`.

4. **Base phase — short forward then back**
   - Forward: send `{"x.vel": BASE_SPEED_MS, "y.vel": 0.0, "theta.vel": 0.0}`
     every control tick for `BASE_DURATION_S = BASE_DISTANCE_M / BASE_SPEED_MS`,
     then `robot.stop_base()`.
   - Settle pause.
   - Back: same with `x.vel = -BASE_SPEED_MS` for the same duration, then
     `robot.stop_base()`.
   - `y.vel` and `theta.vel` are always 0 (no lateral, no rotation).

5. **Teardown**
   - Ramp both arms back to home (idempotent if already there).
   - Always `robot.stop_base()` then `robot.disconnect()` in a `finally` block.

In **dry-run** mode, every "send" prints the would-be action dict and the phase
plan (targets, durations, tick counts) instead of touching hardware, and a
simulated observation advances toward the last commanded target so the loop logic
exercises end-to-end.

## 6. Safety Parameters (single constants block — Conservative profile)

| Constant | Value | Meaning |
|---|---|---|
| `BASE_DISTANCE_M` | `0.05` | ~2 inches of travel per leg |
| `BASE_SPEED_MS` | `0.10` | matches the driver's slowest preset |
| `BASE_DURATION_S` | `BASE_DISTANCE_M / BASE_SPEED_MS` (= 0.5 s) | derived, never hard-coded |
| `ARM_LIFT_DELTA` | `12.0` | normalized-unit up/down on `shoulder_lift` |
| `MAX_RELATIVE_TARGET` | `5` | per-call arm step clamp via the driver |
| `CONTROL_HZ` | `50` | control-loop rate |
| `KP` | `0.5` | P-control gain |
| `POS_TOLERANCE` | `2.0` | "reached target" threshold (normalized units) |
| `PHASE_TIMEOUT_S` | `8.0` | per arm sub-phase wall-clock cap |
| `SETTLE_S` | `0.5` | pause between phases |

Hard invariants enforced in code (assert at startup, see fix_plan US-007):
`BASE_DISTANCE_M <= 0.10`, `0 < BASE_SPEED_MS <= 0.10`, `ARM_LIFT_DELTA <= 20`,
`MAX_RELATIVE_TARGET >= 1`. If any fail, exit non-zero before any motion.

## 7. CLI

```
python examples/xlerobot/safe_manipulation_sequence.py            # dry-run (default)
python examples/xlerobot/safe_manipulation_sequence.py --execute  # real motion
python examples/xlerobot/safe_manipulation_sequence.py --execute \
    --port1 /dev/ttyACM0 --port2 /dev/ttyACM1                     # override ports
```

- Default (no `--execute`): no hardware import side effects beyond constructing
  config/objects; never calls `connect()`. Exits 0 after printing the full plan.
- `--execute`: prints a one-line warning that the robot will physically move and
  requires the operator to confirm by pressing ENTER before connecting.

## 8. Architecture (testability requirement)

Split planning from actuation so the plan is unit-testable with no hardware:

- A **pure planner** producing the ordered list of phases and, for the base,
  `(velocity, duration_s, tick_count)`; for the arms, the target sequence
  `home -> home+delta -> home`. No I/O, no `time.sleep`, no robot.
- An **executor** that consumes the plan and either prints (dry-run) or calls
  `robot.send_action` / `robot.stop_base` (execute).
- A thin `main()` wiring flags → planner → executor with the global `try/finally`.

## 9. Success Criteria / Acceptance

- S1. `python .../safe_manipulation_sequence.py` (no args) runs to completion,
  exits 0, touches no hardware, and prints each phase plan including the derived
  `BASE_DURATION_S` and per-arm targets.
- S2. The pure planner has unit tests proving: base duration = distance/speed;
  forward and back legs are equal & opposite; arm target sequence starts and ends
  at `home`; all safety invariants hold.
- S3. `ruff check` and `ruff format --check` pass on the new files.
- S4. Code review confirms: `max_relative_target` is set; `y.vel`/`theta.vel`
  stay 0; a `finally` block guarantees `stop_base()` + `disconnect()`; `--execute`
  requires explicit confirmation; dry-run never calls `connect()`.
- S5. (Manual, hardware-gated, NOT a CI gate) On a real robot with a clear ~0.5 m
  surface, `--execute` produces a small visible arm up/down on both arms and a
  short forward/back base move with no errors.

## 10. Open Questions

- OQ1. Sign convention of `shoulder_lift` (which way is "up") is calibration-
  dependent. The sequence is symmetric (up then exact return), so safety does not
  depend on the sign; the visible direction may vary per calibration. Acceptable.
- OQ2. Real-hardware verification (S5) cannot run in the autonomous loop; it is a
  human checklist item, not a quality gate.
