import numpy as np
import rerun as rr
from lerobot.common.robots.lekiwi import LeKiwiClient, LeKiwiClientConfig
from lerobot.common.teleoperators.keyboard.teleop_keyboard import KeyboardTeleop, KeyboardTeleopConfig
from lerobot.common.teleoperators.so100_leader import SO100Leader, SO100LeaderConfig
from lerobot.common.utils.visualization_utils import _init_rerun

robot_config = LeKiwiClientConfig(
    remote_ip="192,168.86.29",
    id="rosey",
)

teleop__arm_config = SO100LeaderConfig(
    port="/dev/tty.usbmodem58760431551",
    id="rosey_master",
)

teleop_keyboard_config = KeyboardTeleopConfig(
    id="my_laptop_keyboard",
)

robot = LeKiwiClient(robot_config)
teleop_arm = SO100Leader(teleop__arm_config)
telep_keyboard = KeyboardTeleop(teleop_keyboard_config)
robot.connect()
teleop_arm.connect()
telep_keyboard.connect()

_init_rerun("LeKiwi Teleoperation")

while True:
    observation = robot.get_observation()
    
    for obs, val in observation.items():
        if isinstance(val, np.ndarray):  # Camera images
            rr.log(f"camera/{obs}", rr.Image(val))
    
    arm_action = teleop_arm.get_action()
    arm_action = {f"arm_{k}": v for k, v in arm_action.items()}

    keyboard_keys = telep_keyboard.get_action()
    base_action = robot._from_keyboard_to_base_action(keyboard_keys)

    robot.send_action(arm_action | base_action)
