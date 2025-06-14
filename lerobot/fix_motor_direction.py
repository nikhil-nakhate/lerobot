#!/usr/bin/env python3

"""
Script to fix motor direction by setting drive mode.
"""

import logging
from dataclasses import dataclass

import draccus

from lerobot.common.motors import Motor, MotorNormMode
from lerobot.common.motors.feetech import FeetechMotorsBus, DriveMode
from lerobot.common.utils.utils import init_logging

logger = logging.getLogger(__name__)

@dataclass
class FixMotorConfig:
    port: str = "/dev/ttyACM0"
    motor_id: str = "1"  # draccus expects string
    model: str = "sts3215"  # Default model, change if needed
    inverted: str = "false"  # draccus expects string

def fix_motor_direction(cfg: FixMotorConfig):
    """Fix motor direction by setting drive mode.

    Args:
        cfg: Configuration containing the port and motor ID
    """
    # Initialize the bus with our motor
    bus = FeetechMotorsBus(
        port=cfg.port,
        motors={
            "motor": Motor(int(cfg.motor_id), cfg.model, MotorNormMode.RANGE_0_100)
        },
    )

    try:
        # Connect to the bus
        bus.connect()

        # Set drive mode based on inverted flag
        drive_mode = DriveMode.INVERTED if cfg.inverted.lower() == "true" else DriveMode.NON_INVERTED
        bus.write("Drive_Mode", drive_mode.value, "motor")
        print(f"\nSet drive mode to: {'INVERTED' if cfg.inverted else 'NON_INVERTED'}")

    except Exception as e:
        print(f"\nError: {str(e)}")
    finally:
        if hasattr(bus, 'close'):
            bus.close()

@draccus.wrap()
def main(cfg: FixMotorConfig):
    init_logging()
    fix_motor_direction(cfg)

if __name__ == "__main__":
    main()
