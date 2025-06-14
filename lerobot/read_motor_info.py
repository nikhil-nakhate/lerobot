# /dev/ttyACM0

#!/usr/bin/env python3

"""
Simple script to read the baudrate and ID of a connected Feetech motor.
"""

import logging
from dataclasses import dataclass
from typing import Optional

import draccus

from lerobot.common.motors import Motor, MotorNormMode
from lerobot.common.motors.feetech import FeetechMotorsBus
from lerobot.common.utils.utils import init_logging

logger = logging.getLogger(__name__)

@dataclass
class ReadMotorConfig:
    port: str
    model: str = "sts3215"  # Default model, change if needed

def read_motor_info(cfg: ReadMotorConfig) -> tuple[Optional[int], Optional[int]]:
    """Read the baudrate and ID of a connected motor.

    Args:
        cfg: Configuration containing the port and motor model

    Returns:
        tuple: (baudrate, motor_id) if found, or (None, None) if not found
    """
    # Create a temporary motor with ID 1 (default) for scanning
    temp_motor = Motor(1, cfg.model, MotorNormMode.RANGE_M100_100)
    
    # Initialize the bus with our temporary motor
    bus = FeetechMotorsBus(
        port=cfg.port,
        motors={"temp": temp_motor}
    )

    try:
        # Open the port first
        if not bus.port_handler.openPort():
            print(f"\nError: Failed to open port {cfg.port}")
            return None, None

        # Set the default baudrate for initial communication
        if not bus.port_handler.setBaudRate(bus.default_baudrate):
            print(f"\nError: Failed to set baudrate {bus.default_baudrate}")
            return None, None

        # Find the actual motor's baudrate and ID
        baudrate, motor_id = bus._find_single_motor("temp")
        print(f"\nFound motor:")
        print(f"  - ID: {motor_id}")
        print(f"  - Baudrate: {baudrate}")
        return baudrate, motor_id

    except RuntimeError as e:
        print(f"\nError: {str(e)}")
        return None, None
    finally:
        # Clean up
        if hasattr(bus, "port_handler") and bus.port_handler.is_open:
            bus.port_handler.closePort()

@draccus.wrap()
def main(cfg: ReadMotorConfig):
    init_logging()
    read_motor_info(cfg)

if __name__ == "__main__":
    main()