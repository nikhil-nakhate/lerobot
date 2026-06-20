# Agent Build / Run / Test Instructions

Project: **lerobot** (with XLeRobot integration). Python package under `src/lerobot`.
Feature under development: `examples/xlerobot/safe_manipulation_sequence.py`.

## Environment
```bash
# Install lerobot in editable mode with test extras (one-time)
pip install -e ".[test]"
# The XLeRobot driver imports numpy + feetech motor bus; both ship with lerobot.
```

If a full install is unavailable in the loop environment, the dry-run and the
planner unit tests still work as long as `numpy` and the `lerobot` package import
(set `PYTHONPATH=src` when running from the repo without an install).

## Run the deliverable
```bash
# Dry-run (DEFAULT — no hardware, safe to run in the loop / CI)
PYTHONPATH=src python examples/xlerobot/safe_manipulation_sequence.py

# Real motion (HUMAN ONLY — robot must be connected, calibrated, on a clear surface)
PYTHONPATH=src python examples/xlerobot/safe_manipulation_sequence.py --execute
```

## Quality Gates (run for files you touched)
```bash
# Lint + format (repo standard is ruff; config in pyproject.toml)
ruff check examples/xlerobot/safe_manipulation_sequence.py tests/examples/test_safe_manipulation_sequence.py
ruff format --check examples/xlerobot/safe_manipulation_sequence.py tests/examples/test_safe_manipulation_sequence.py

# Unit tests for the planner / CLI (no hardware required)
PYTHONPATH=src pytest tests/examples/test_safe_manipulation_sequence.py -q

# End-to-end "can the loop run it" check (dry-run must exit 0)
PYTHONPATH=src python examples/xlerobot/safe_manipulation_sequence.py
```

A story is NOT complete until the relevant gates above pass for the modified files.

## Key Driver Facts (so you don't have to re-derive them)
- `from lerobot.robots.xlerobot import XLerobot, XLerobotConfig`
- Arm targets: `"<side>_arm_shoulder_lift.pos"` (position mode, normalized
  ≈ -100..100 because `use_degrees=False`).
- Base: velocity mode — `{"x.vel": m/s, "y.vel": m/s, "theta.vel": deg/s}`.
- `XLerobotConfig(max_relative_target=...)` enables the per-call arm clamp inside
  `send_action`.
- `robot.connect()` is interactive (calibration prompt) — only in `--execute`.
- `robot.disconnect()` stops the base and releases torque.
- Established P-control pattern: see `examples/4_xlerobot_teleop_keyboard.py`
  (`cmd = current + KP*(target - current)` at ~50 Hz).

## Key Learnings
- The full feature (US-001…US-007 + optional switches) is implemented and green:
  `examples/xlerobot/safe_manipulation_sequence.py` + 19 passing tests.
- `examples/` is NOT an importable package; the test loads the module by file path
  via `importlib`. It MUST register the module in `sys.modules` before
  `exec_module`, otherwise `@dataclass` + `from __future__ import annotations`
  fails with `'NoneType' object has no attribute '__dict__'`.
- Do NOT bind `time.sleep`/`time.monotonic` as default arg values — that captures
  the original at def time and defeats monkeypatching. Resolve them at call time
  (`fn = time.sleep if fn is None else fn`).
- `ruff`/`pytest` were not preinstalled in the `lerobot` conda env; install with
  `pip install pytest pytest-timeout ruff` if missing.
- `print` is allowed by ruff here (T201/T203 are ignored in pyproject.toml).

## Git Workflow
- Work on a feature branch (e.g. `feature/safe-manipulation-sequence`), never on
  `main`.
- Conventional commits: `feat(examples): ...`, `test(examples): ...`, `docs: ...`.
- Stage all (`git add -A`), confirm `git status --porcelain` is clean after commit.
- Mark the corresponding `.ralph/fix_plan.md` item `[x]` in the same commit.
