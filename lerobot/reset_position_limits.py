#!/usr/bin/env python3

"""
Script to reset position limits on the motor.
"""

import logging
from dataclasses import dataclass

import draccus

from lerobot.common.motors import Motor, MotorNormMode
from lerobot.common.motors.feetech import FeetechMotorsBus
from lerobot.common.utils.utils import init_logging

logger = logging.getLogger(__name__)

@dataclass
class ResetLimitsConfig:
    port: str = "/dev/ttyACM1"
    motor_id: str = "1"  # draccus expects string
    model: str = "sts3215"  # Default model, change if needed

def reset_limits(cfg: ResetLimitsConfig):
    """Reset position limits on the motor.

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

        # Set min/max position limits to full range
        bus.write("Min_Position_Limit", 0, "motor")
        bus.write("Max_Position_Limit", 4095, "motor")  # Full range for STS3215
        print("\nReset position limits to full range")

        # Read back the values to confirm
        min_pos = bus.read("Min_Position_Limit", "motor")
        max_pos = bus.read("Max_Position_Limit", "motor")
        print(f"New position limits: {min_pos} to {max_pos}")

        # Clear alarms again
        bus.write("LED_Alarm_Condition", 0, "motor")
        led_alarm = bus.read("LED_Alarm_Condition", "motor")
        print(f"LED Alarm Condition: {led_alarm}")

    except Exception as e:
        print(f"\nError: {str(e)}")
    finally:
        if hasattr(bus, 'close'):
            bus.close()

@draccus.wrap()
def main(cfg: ResetLimitsConfig):
    init_logging()
    reset_limits(cfg)

if __name__ == "__main__":
    main()
