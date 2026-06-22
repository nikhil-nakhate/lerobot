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

"""Auto-detect which serial port is which XLeRobot bus.

USB enumeration order (``/dev/ttyACM0`` vs ``/dev/ttyACM1``) is not stable across
reboots/replugs, so the default ``XLerobotConfig`` ports can end up swapped. The
two buses are unambiguously distinguishable by motor count:

* ``port1`` = left arm (6) + head (2)  = **8 motors**
* ``port2`` = right arm (6) + base (3) = **9 motors**

This probes only the known 1 Mbaud rate (fast, read-only, no torque) and assigns
ports by count.
"""

from __future__ import annotations

import glob
import logging

from lerobot.motors.feetech import FeetechMotorsBus

logger = logging.getLogger(__name__)

DEFAULT_BAUDRATE = 1_000_000
LEFT_HEAD_MOTOR_COUNT = 8
RIGHT_BASE_MOTOR_COUNT = 9


def count_motors(port: str, baudrate: int = DEFAULT_BAUDRATE) -> set[int]:
    """Return the set of motor IDs answering on ``port`` (read-only, no torque)."""
    bus = FeetechMotorsBus(port, {})
    bus._connect(handshake=False)
    try:
        bus.set_baudrate(baudrate)
        found = bus.broadcast_ping() or {}
        return set(found)
    finally:
        bus.port_handler.closePort()


def detect_xlerobot_ports(
    candidates: list[str] | None = None, baudrate: int = DEFAULT_BAUDRATE
) -> tuple[str, str]:
    """Return ``(port1, port2)`` = (left+head bus, right+base bus).

    Raises ``RuntimeError`` if the two buses cannot be identified by motor count.
    """
    candidates = candidates or sorted(glob.glob("/dev/ttyACM*"))
    counts = {port: len(count_motors(port, baudrate)) for port in candidates}
    logger.info("XLeRobot port scan: %s", counts)

    port1 = next((p for p, n in counts.items() if n == LEFT_HEAD_MOTOR_COUNT), None)
    port2 = next((p for p, n in counts.items() if n == RIGHT_BASE_MOTOR_COUNT), None)
    if port1 is None or port2 is None:
        raise RuntimeError(
            f"Could not identify XLeRobot buses by motor count: {counts}. "
            f"Expected one bus with {LEFT_HEAD_MOTOR_COUNT} motors (left arm + head) and one "
            f"with {RIGHT_BASE_MOTOR_COUNT} (right arm + base). Check power and wiring."
        )
    return port1, port2
