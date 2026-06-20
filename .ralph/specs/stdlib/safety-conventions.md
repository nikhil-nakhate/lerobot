# Stdlib — Robot Motion Safety Conventions

Reusable conventions every motion script in this repo should follow. Referenced by
`.ralph/specs/requirements.md`.

## 1. Default to no motion
- Scripts that move real hardware default to a **dry-run** that prints planned
  actions and touches nothing. Real motion is opt-in via an explicit `--execute`
  flag plus an interactive ENTER confirmation.

## 2. Bound everything, centrally
- Put every magnitude (distance, speed, joint delta, gains, timeouts) in ONE
  constants block near the top of the file. A reviewer must be able to confirm
  safety by reading that block alone.
- Assert hard invariants at startup; exit non-zero before any motion if violated.

## 3. Self-reversing motions
- Each demonstrated motion returns to its captured start state (up→down,
  forward→back). Safety must not depend on a sign/direction that is calibration-
  dependent.

## 4. Use the driver's built-in clamps
- For position-controlled arms, set `max_relative_target` on the robot config so
  `ensure_safe_goal_position` caps per-call joint steps.
- For velocity-controlled bases, command only the intended DOF; hold all other
  velocity components at exactly 0.0.

## 5. Open-loop base moves
- The XLeRobot base has no position feedback. Distance = velocity × time. Keep
  speeds at/below the driver's slowest preset (0.10 m/s) and durations short.
  Accept small drift; never chain many legs that could accumulate error.

## 6. Guaranteed safe shutdown
- Wrap the run in `try/finally`. The `finally` always stops the base
  (`stop_base()`) and disconnects (`disconnect()`, which also releases torque).
- Handle `KeyboardInterrupt` so Ctrl-C stops motion immediately.

## 7. Separate planning from actuation
- Keep a pure planner (no I/O, no `time`, no robot) so the entire plan is unit-
  testable with no hardware. The executor is the only part that talks to the robot.
