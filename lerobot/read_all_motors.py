#!/usr/bin/env python3

"""
Script to read the baudrate and IDs of all connected Feetech motors.
"""

import logging
from dataclasses import dataclass

import draccus

from lerobot.common.motors import Motor, MotorNormMode
from lerobot.common.motors.feetech import FeetechMotorsBus
from lerobot.common.utils.utils import init_logging

logger = logging.getLogger(__name__)

@dataclass
class ReadMotorsConfig:
    port: str
    model: str = "sts3215"  # Default model, change if needed

def read_all_motors(cfg: ReadMotorsConfig):
    """Read the baudrate and IDs of all connected motors.

    Args:
        cfg: Configuration containing the port and motor model
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
            return

        # Try different baudrates
        for baudrate in [1000000, 500000, 250000, 128000, 115200, 57600, 38400, 19200]:
            # Set the baudrate for communication
            if not bus.port_handler.setBaudRate(baudrate):
                print(f"\nError: Failed to set baudrate {baudrate}")
                continue

            # Broadcast ping to find all motors
            try:
                id_model = bus.broadcast_ping()
                if id_model:
                    print(f"\nFound motors at baudrate {baudrate}:")
                    for motor_id, model_number in id_model.items():
                        print(f"  - ID: {motor_id}")
            except Exception as e:
                logger.debug(f"No response at baudrate {baudrate}: {e}")

    except Exception as e:
        print(f"\nError: {str(e)}")
    finally:
        # Clean up
        if hasattr(bus, "port_handler") and bus.port_handler.is_open:
            bus.port_handler.closePort()

@draccus.wrap()
def main(cfg: ReadMotorsConfig):
    init_logging()
    read_all_motors(cfg)

if __name__ == "__main__":
    main()
