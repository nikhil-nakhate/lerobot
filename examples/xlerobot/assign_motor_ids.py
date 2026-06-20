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

"""Safely assign a Feetech motor's ID, one isolated motor at a time.

Why this exists: on XLeRobot the head motors and base wheels often ship still at
the factory-default id 1, so they collide with ``shoulder_pan`` (also id 1) on the
shared bus. Colliding motors cannot be addressed individually over a half-duplex
serial bus, so each must be connected ALONE to set its id. See
``.ralph/specs/motor_id_recovery.md``.

This tool refuses to write unless EXACTLY ONE motor is present and reads cleanly
(a collision of two motors at the same id fails a repeated data read - that is how
we detect "more than one motor is connected" even when both share id 1).

Procedure for the current robot (run once per motor, isolating each):
    # bus1 (/dev/ttyACM0): head motors
    python examples/xlerobot/assign_motor_ids.py --port /dev/ttyACM0 --id 7   # head_motor_1
    python examples/xlerobot/assign_motor_ids.py --port /dev/ttyACM0 --id 8   # head_motor_2
    # bus2 (/dev/ttyACM1): base wheels
    python examples/xlerobot/assign_motor_ids.py --port /dev/ttyACM1 --id 7   # base_left_wheel
    python examples/xlerobot/assign_motor_ids.py --port /dev/ttyACM1 --id 8   # base_back_wheel
    python examples/xlerobot/assign_motor_ids.py --port /dev/ttyACM1 --id 9   # base_right_wheel

"Isolate" = only that one motor is electrically on the bus (unplug the rest of the
chain, or connect the single motor straight to the control board). Verify the whole
robot afterwards with: python examples/xlerobot/check_motors.py
"""

from __future__ import annotations

import argparse

from lerobot.motors import Motor, MotorNormMode
from lerobot.motors.feetech import FeetechMotorsBus

NORM = MotorNormMode.RANGE_M100_100
CLEAN_READ_TRIES = 6  # a single motor reads this register cleanly every time


def _find_single(port: str, model: str, log=print) -> tuple[int, int]:
    """Find exactly one connected motor across all baud-rates.

    Returns:
        (baudrate, current_id) of the single motor.

    Raises:
        SystemExit: if zero or more than one motor is detected.
    """
    probe = FeetechMotorsBus(port, {})
    probe.connect(handshake=False)
    try:
        found: dict[int, list[int]] = {}
        for baud in probe.available_baudrates:
            probe.set_baudrate(baud)
            ids_models = probe.broadcast_ping() or {}
            if ids_models:
                found[baud] = sorted(ids_models)
    finally:
        probe.disconnect(disable_torque=False)

    if not found:
        raise SystemExit(
            f"No motor detected on {port} at any baud-rate.\n"
            "Check power and that the motor is plugged into the control board."
        )
    if len(found) > 1 or any(len(ids) > 1 for ids in found.values()):
        raise SystemExit(
            f"More than one motor detected on {port}: {found}\n"
            "Connect ONLY the single motor you want to assign, then retry."
        )

    baud = next(iter(found))
    cur_id = found[baud][0]
    log(f"Detected exactly one motor: id={cur_id} at baud={baud}.")
    return baud, cur_id


def _assert_no_collision(port: str, baud: int, cur_id: int, model: str, log=print) -> None:
    """Confirm a clean repeated read - two motors at the same id would fail this."""
    bus = FeetechMotorsBus(port, {"probe": Motor(cur_id, model, NORM)})
    bus.connect(handshake=False)
    bus.set_baudrate(baud)
    try:
        for _ in range(CLEAN_READ_TRIES):
            bus.read("Model_Number", "probe", num_retry=0)  # raises on collision/garble
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(
            f"Read from id {cur_id} on {port} is not clean ({type(exc).__name__}).\n"
            "This usually means MORE THAN ONE motor is on the bus (e.g. several still at "
            "id 1). Connect ONLY one motor and retry."
        ) from exc
    finally:
        bus.disconnect(disable_torque=False)
    log(f"Clean read confirmed: a single motor is isolated at id {cur_id}.")


def assign_id(port: str, target_id: int, model: str, *, confirm=True, log=print, input_fn=input) -> int:
    baud, cur_id = _find_single(port, model, log=log)
    _assert_no_collision(port, baud, cur_id, model, log=log)

    if cur_id == target_id:
        log(f"Motor already has id {target_id}; nothing to do.")
        return 0

    if confirm:
        reply = input_fn(f"Set the motor at id {cur_id} (baud {baud}) to id {target_id} on {port}? [y/N] ")
        if reply.strip().lower() not in {"y", "yes"}:
            log("Aborted by operator.")
            return 1

    bus = FeetechMotorsBus(port, {"target": Motor(target_id, model, NORM)})
    bus.connect(handshake=False)
    try:
        # Tested lerobot path: writes ID then the bus default baud-rate to EEPROM.
        bus.setup_motor("target", initial_baudrate=baud, initial_id=cur_id)
        model_nb = bus.ping(target_id, num_retry=3)
        if model_nb is None:
            raise SystemExit(f"Wrote id but the motor does not answer at id {target_id}; please retry.")
        bus.read("Model_Number", "target", num_retry=2)  # clean read at the new id
    finally:
        bus.disconnect(disable_torque=False)

    log(f"SUCCESS: motor is now id {target_id} (model {model_nb}) at the bus default baud-rate.")
    log("Re-run examples/xlerobot/check_motors.py after assembling the whole chain.")
    return 0


def main(argv: list[str] | None = None, *, log=print, input_fn=input) -> int:
    parser = argparse.ArgumentParser(description="Assign one isolated Feetech motor's id (safe, guarded).")
    parser.add_argument("--port", required=True, help="serial port, e.g. /dev/ttyACM0")
    parser.add_argument("--id", type=int, required=True, dest="target_id", help="target id to assign (1-253)")
    parser.add_argument("--model", default="sts3215", help="motor model (default: %(default)s)")
    parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    args = parser.parse_args(argv)

    if not 1 <= args.target_id <= 253:
        log("ERROR: --id must be in 1..253")
        return 2

    return assign_id(args.port, args.target_id, args.model, confirm=not args.yes, log=log, input_fn=input_fn)


if __name__ == "__main__":
    raise SystemExit(main())
