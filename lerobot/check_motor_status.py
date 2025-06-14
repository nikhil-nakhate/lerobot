#!/usr/bin/env python3

"""
Script to check motor status and alarms.
"""

import logging
from dataclasses import dataclass

import draccus

from lerobot.common.motors import Motor, MotorNormMode
from lerobot.common.motors.feetech import FeetechMotorsBus
from lerobot.common.utils.utils import init_logging

logger = logging.getLogger(__name__)

@dataclass
class CheckMotorConfig:
    port: str = "/dev/ttyACM0"
    motor_id: str = "1"  # draccus expects string
    model: str = "sts3215"  # Default model, change if needed

def check_motor_status(cfg: CheckMotorConfig):
    """Check motor status and alarms.

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

        # Read various status registers
        led_alarm = bus.read("LED_Alarm_Condition", "motor")
        print(f"\nLED Alarm Condition: {led_alarm}")
        
        voltage = bus.read("Present_Voltage", "motor")
        print(f"Present Voltage: {voltage}")
        
        temp = bus.read("Present_Temperature", "motor")
        print(f"Present Temperature: {temp}")
        
        load = bus.read("Present_Load", "motor")
        print(f"Present Load: {load}")
        
        # Check operating mode and drive mode
        op_mode = bus.read("Operating_Mode", "motor")
        print(f"Operating Mode: {op_mode}")

    except Exception as e:
        print(f"\nError: {str(e)}")
    finally:
        if hasattr(bus, 'close'):
            bus.close()

@draccus.wrap()
def main(cfg: CheckMotorConfig):
    init_logging()
    check_motor_status(cfg)

if __name__ == "__main__":
    main()
