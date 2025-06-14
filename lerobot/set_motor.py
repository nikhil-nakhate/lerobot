#!/usr/bin/env python3

"""
Simple script to set the ID and baudrate of a connected Feetech motor.
"""

import logging
from dataclasses import dataclass

import draccus

from lerobot.common.motors.feetech import FeetechMotorsBus
from lerobot.common.utils.utils import init_logging

logger = logging.getLogger(__name__)

@dataclass
class SetMotorConfig:
    port: str
    current_id: int  # Current ID of the motor
    new_id: int  # New ID to set
    model: str = "sts3215"  # Default model, change if needed

def set_motor_config(cfg: SetMotorConfig):
    """Set the motor ID and baudrate.
    
    Args:
        cfg: Configuration containing the port, current ID, and new ID
    """
    init_logging()
    
    from lerobot.common.motors import Motor, MotorNormMode

    # Initialize the bus with just one motor
    bus = FeetechMotorsBus(
        port=cfg.port,
        motors={
            "motor": Motor(cfg.current_id, cfg.model, MotorNormMode.RANGE_0_100)
        },
    )
    
    try:
        # Connect to the bus first
        bus.connect()
        # Set the new ID (address 5, length 1)
        bus.write("ID", "motor", cfg.new_id)
        logger.info(f"Successfully set motor ID from {cfg.current_id} to {cfg.new_id}")
        
        # Set the baudrate to 1000000 (address 6, length 1)
        # For STS series, 1000000 maps to value 0
        bus.write("Baud_Rate", "motor", 0)  # 0 corresponds to 1000000 baud
        logger.info("Successfully set baudrate to 1000000")
        
    except Exception as e:
        logger.error(f"Failed to configure motor: {e}")
    finally:
        if hasattr(bus, 'close'):
            bus.close()

def main():
    cfg = draccus.parse(SetMotorConfig)
    set_motor_config(cfg)

if __name__ == "__main__":
    main()
