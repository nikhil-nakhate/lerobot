#!/usr/bin/env python3

"""
Script to clear motor alarms.
"""

import logging
from dataclasses import dataclass

import draccus

from lerobot.common.motors import Motor, MotorNormMode
from lerobot.common.motors.feetech import FeetechMotorsBus
from lerobot.common.utils.utils import init_logging

logger = logging.getLogger(__name__)

@dataclass
class ClearAlarmsConfig:
    port: str = "/dev/ttyACM1"
    motor_id: str = "1"  # draccus expects string
    model: str = "sts3215"  # Default model, change if needed

def clear_alarms(cfg: ClearAlarmsConfig):
    """Clear motor alarms.

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

        # Clear LED alarm condition
        bus.write("LED_Alarm_Condition", 0, "motor")
        print("\nCleared LED Alarm Condition")

        # Read back the values to confirm
        led_alarm = bus.read("LED_Alarm_Condition", "motor")
        print(f"New LED Alarm Condition: {led_alarm}")

    except Exception as e:
        print(f"\nError: {str(e)}")
    finally:
        if hasattr(bus, 'close'):
            bus.close()

@draccus.wrap()
def main(cfg: ClearAlarmsConfig):
    init_logging()
    clear_alarms(cfg)

if __name__ == "__main__":
    main()
