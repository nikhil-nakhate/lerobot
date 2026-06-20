# Ralph Fix Plan — XLeRobot Safe Manipulation Sequence

Prioritized, one-iteration-sized stories. Each story names its acceptance
criteria with at least one positive and one negative/edge case. Full context is
in `.ralph/specs/requirements.md`. Do not exceed the scope of the selected story.

Target file: `examples/xlerobot/safe_manipulation_sequence.py`
Test file:   `tests/examples/test_safe_manipulation_sequence.py`

## High Priority

- [x] **US-001 — Script skeleton, constants, CLI, safety asserts**
  - Create `examples/xlerobot/safe_manipulation_sequence.py` with the §6 constants
    block, `argparse` flags (`--execute`, `--port1`, `--port2`), and a
    `validate_safety_constants()` that asserts the §6 invariants.
  - Positive: `python .../safe_manipulation_sequence.py` parses, validates, and
    exits 0 printing the resolved config (no hardware).
  - Negative: temporarily setting `BASE_DISTANCE_M = 0.5` makes
    `validate_safety_constants()` raise/exit non-zero (covered by a unit test that
    calls the validator with an out-of-range value).
  - `ruff check`/`ruff format --check` pass.

- [x] **US-002 — Pure planner (no hardware)**
  - Implement a pure function returning the ordered plan: arm target sequence per
    side (`home -> home+ARM_LIFT_DELTA -> home`) and base legs as
    `(x_vel, duration_s, tick_count)` with `duration_s = BASE_DISTANCE_M/BASE_SPEED_MS`.
  - No I/O, no `time`, no robot object.
  - Positive: given `home=0.0`, the arm sequence is `[0, +12, 0]`; base legs are
    `[(+0.10, 0.5, 25), (-0.10, 0.5, 25)]` at `CONTROL_HZ=50`.
  - Negative: planner never emits non-zero `y.vel` or `theta.vel`.

- [x] **US-003 — Unit tests for the planner**
  - Create `tests/examples/test_safe_manipulation_sequence.py`.
  - Assert: base duration == distance/speed; forward/back equal & opposite; arm
    sequence starts and ends at `home`; tick_count == round(duration*CONTROL_HZ);
    all §6 invariants hold for default constants; validator rejects an
    out-of-range value.
  - `pytest tests/examples/test_safe_manipulation_sequence.py` passes.

- [x] **US-004 — Dry-run executor (default path)**
  - Implement the executor branch that, with no `--execute`, prints each phase
    plan and every would-be action dict, advances a simulated observation toward
    the last commanded target, and never imports/opens hardware ports or calls
    `connect()`.
  - Positive: `python .../safe_manipulation_sequence.py` runs the full sequence
    (arms up/down both sides, base fwd/back), prints derived `BASE_DURATION_S`,
    exits 0.
  - Negative: with no `--execute`, no `XLerobot.connect`/`send_action` is called
    (assert via a unit test that patches `XLerobot`).

## Medium Priority

- [x] **US-005 — Real executor (`--execute`) with arm P-control + base timing**
  - Implement the `--execute` branch: ENTER confirmation, `robot.connect()`,
    cache per-arm `shoulder_lift` home, P-control loop at `CONTROL_HZ` driving
    both arms together to up-target then home (tolerance/timeout), then the base
    forward/back legs using `BASE_DURATION_S` with `stop_base()` after each leg.
  - Build `XLerobotConfig(max_relative_target=MAX_RELATIVE_TARGET, port1=..., port2=...)`.
  - Positive: with `XLerobot` patched by a fake, `--execute` (confirmation
    auto-accepted in the test) issues only `shoulder_lift` `.pos` commands for the
    arms and `x.vel`-only base commands, calls `stop_base()` after each base leg.
  - Negative: `y.vel` and `theta.vel` are always exactly 0.0 in every sent action.

- [x] **US-006 — Guaranteed safe shutdown (finally + signals)**
  - Wrap the whole run in `try/finally` that always calls `robot.stop_base()` then
    `robot.disconnect()` in `--execute`; handle `KeyboardInterrupt` so Ctrl-C
    stops the base and disconnects cleanly.
  - Positive: a fake robot that raises mid-arm-phase still receives `stop_base()`
    and `disconnect()` (unit test asserts call order).
  - Negative: dry-run teardown does not call `disconnect()` (nothing was connected).

## Low Priority

- [x] **US-007 — Operator docs + header**
  - Add a module docstring with the run commands (§7), the safety-profile table,
    and a one-line pointer to `.ralph/specs/requirements.md`.
  - Update `.ralph/AGENT.md` "Key Learnings" with any gotchas discovered.
  - Positive: docstring lists both dry-run and `--execute` invocations and the
    conservative limits.

## Optional (non-blocking)

- [x] Add a `--dry-run` explicit alias (default is already dry-run).
- [x] Add a `--base-only` / `--arms-only` switch for isolating subsystems.

## Completed
- [x] PRD + Ralph scaffold authored (`.ralph/specs/requirements.md`, this plan,
      `PROMPT.md`, `AGENT.md`, `.ralphrc`).
- [x] **US-008 — Calibration restore/calibrate option** (`--robot-id`, `--calibrate`):
      non-interactive restore of a saved calibration file, interactive
      (re)calibration on demand, and a pre-connect abort (rc 2) with guidance when
      no calibration exists. Verified on real hardware (gate aborts before motion).

## Notes
- ONE story per loop. Search before assuming anything is unimplemented.
- Never modify `src/lerobot/**` — this work lives only in `examples/` and `tests/`.
- The real-hardware demo (spec S5) is a human checklist item, not a CI gate.
