import time
import numpy as np

from lerobot.common.datasets.lerobot_dataset import LeRobotDataset
from lerobot.common.datasets.utils import hw_to_dataset_features
from lerobot.common.robots.lekiwi.config_lekiwi import LeKiwiClientConfig
from lerobot.common.robots.lekiwi.lekiwi_client import LeKiwiClient
from lerobot.common.teleoperators.keyboard import KeyboardTeleop, KeyboardTeleopConfig
from lerobot.common.teleoperators.so100_leader import SO100Leader, SO100LeaderConfig

NB_CYCLES_CLIENT_CONNECTION = 250

leader_arm_config = SO100LeaderConfig(port="/dev/ttyACM0")
leader_arm = SO100Leader(leader_arm_config)

keyboard_config = KeyboardTeleopConfig()
keyboard = KeyboardTeleop(keyboard_config)

robot_config = LeKiwiClientConfig(remote_ip="192.168.86.29", id="rosey_master")
robot = LeKiwiClient(robot_config)

action_features = hw_to_dataset_features(robot.action_features, "action")
obs_features = hw_to_dataset_features(robot.observation_features, "observation")
dataset_features = {**action_features, **obs_features}

dataset = LeRobotDataset.create(
    repo_id="nikx-vla/lekiwi" + str(int(time.time())),
    fps=10,
    features=dataset_features,
    robot_type=robot.name,
)

leader_arm.connect()
keyboard.connect()
robot.connect()

if not robot.is_connected or not leader_arm.is_connected or not keyboard.is_connected:
    exit()

print("Starting LeKiwi teleoperation")
i = 0
while i < NB_CYCLES_CLIENT_CONNECTION:
    arm_action = leader_arm.get_action()
    arm_action = {f"arm_{k}": v for k, v in arm_action.items()}

    keyboard_keys = keyboard.get_action()

    base_action = robot._from_keyboard_to_base_action(keyboard_keys)

    action = {**arm_action, **base_action} if len(base_action) > 0 else arm_action

    action_sent = robot.send_action(action)
    observation = robot.get_observation()

    # Convert state dict to numpy array in the correct order
    print("Full observation:", observation)
    
    # Initialize state dict with zeros if empty
    state_dict = observation.get('observation.state', {})
    if not state_dict:
        print("Warning: No state information received, using zeros")
        state_dict = {k: 0.0 for k in robot._state_order}
    
    # Create state array with default values for missing keys
    state_array = np.array([state_dict.get(k, 0.0) for k in robot._state_order], dtype=np.float32)

    # Create the frame with the correct feature structure
    frame = {
        'action': np.array(list(action_sent.values()), dtype=np.float32),
        'observation.state': state_array,
        'observation.images.front': np.zeros((640, 480, 3), dtype=np.uint8),  # Placeholder image
        'observation.images.wrist': np.zeros((640, 480, 3), dtype=np.uint8)   # Placeholder image
    }
    
    task = "Dummy Example Task Dataset"
    dataset.add_frame(frame, task)
    i += 1

print("Disconnecting Teleop Devices and LeKiwi Client")
robot.disconnect()
leader_arm.disconnect()
keyboard.disconnect()

print("Uploading dataset to the hub")
dataset.save_episode()
# dataset.push_to_hub()
