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

"""Make Feetech/Dynamixel bus I/O tolerant of occasional corrupted packets.

The stock ``XLerobot.connect()`` / ``configure()`` issue a large burst of register
writes with ``num_retry=0`` (e.g. ``enable_torque`` passes ``0`` explicitly). On a
marginally noisy serial link a single dropped/garbled packet then aborts the whole
bring-up with "Incorrect status packet" / "There is no status packet".

There is no public knob for this, so we patch the lowest-level
``_read``/``_write``/``_sync_read``/``_sync_write`` on ``MotorsBus`` to enforce a
minimum retry count, regardless of what callers pass. This is a runtime monkeypatch
(no core files modified) and is idempotent.

NOTE: retries make a flaky link *usable*, not *healthy* — if you need this, also
re-seat the USB and motor daisy-chain connectors.
"""

from __future__ import annotations

import functools
import logging

from lerobot.motors.motors_bus import MotorsBus

logger = logging.getLogger(__name__)

_PATCH_FLAG = "_lerobot_vr_resilient"
_LOW_LEVEL_METHODS = ("_read", "_write", "_sync_read", "_sync_write")


def enable_bus_retries(min_retries: int = 3) -> None:
    """Force at least ``min_retries`` retries on every low-level bus read/write."""
    if getattr(MotorsBus, _PATCH_FLAG, False):
        return

    patched = []
    for name in _LOW_LEVEL_METHODS:
        orig = getattr(MotorsBus, name, None)
        if orig is None:
            continue

        @functools.wraps(orig)
        def wrapper(self, *args, _orig=orig, **kwargs):
            current = kwargs.get("num_retry", 0) or 0
            kwargs["num_retry"] = max(current, min_retries)
            return _orig(self, *args, **kwargs)

        setattr(MotorsBus, name, wrapper)
        patched.append(name)

    setattr(MotorsBus, _PATCH_FLAG, True)
    logger.info("Bus retries enabled (min_retries=%d) on: %s", min_retries, ", ".join(patched))
