"""LeKiwi teleoperator that combines SO100 leader arm control with keyboard base control."""

import logging
from pynput import keyboard

from lerobot.common.teleoperators.teleoperator import Teleoperator
from lerobot.common.teleoperators.so100_leader import SO100Leader, SO100LeaderConfig
from lerobot.common.teleoperators.keyboard import KeyboardTeleop, KeyboardTeleopConfig
from lerobot.common.teleoperators.lekiwi.configuration_lekiwi import LeKiwiTeleopConfig


class LeKiwiTeleop(Teleoperator):
    """
    LeKiwi teleoperator that combines:
    - SO100 leader arm for arm control
    - Keyboard input for base control
    """

    config_class = LeKiwiTeleopConfig
    name = "lekiwi"

    @property
    def action_features(self) -> list[str]:
        """Get combined action features from both teleops."""
        # Combine arm and keyboard features
        arm_features = [f"arm_{f}" for f in self.arm_teleop.action_features]
        keyboard_features = self.keyboard_teleop.action_features
        return arm_features + keyboard_features

    @property
    def feedback_features(self) -> list[str]:
        """Get combined feedback features from both teleops."""
        # Currently neither teleop implements feedback
        return []

    def configure(self) -> None:
        """Configure both teleops."""
        self.arm_teleop.configure()
        self.keyboard_teleop.configure()

    def calibrate(self) -> None:
        """Calibrate both teleops."""
        self.arm_teleop.calibrate()
        self.keyboard_teleop.calibrate()

    @property
    def is_calibrated(self) -> bool:
        """Check if both teleops are calibrated."""
        return self.arm_teleop.is_calibrated and self.keyboard_teleop.is_calibrated

    @property
    def is_connected(self) -> bool:
        """Check if both teleops are connected."""
        return self.arm_teleop.is_connected and self.keyboard_teleop.is_connected

    def __init__(self, config: LeKiwiTeleopConfig):
        super().__init__(config)
        self.config = config

        # Initialize SO100 leader arm teleop
        arm_config = SO100LeaderConfig(
            port=config.arm_port,
            id=config.arm_id,
        )
        self.arm_teleop = SO100Leader(arm_config)

        # Initialize keyboard teleop for base control
        keyboard_config = KeyboardTeleopConfig(
            id=config.keyboard_id,
        )
        self.keyboard_teleop = KeyboardTeleop(keyboard_config)

    def connect(self) -> None:
        """Connect both arm and keyboard teleops."""
        self.arm_teleop.connect()
        self.keyboard_teleop.connect()
        logging.info("LeKiwiTeleop connected")

    def get_action(self) -> dict[str, float]:
        """Get combined action from arm and keyboard teleops."""
        # Get arm action and prefix with 'arm_'
        arm_action = self.arm_teleop.get_action()
        arm_action = {f"arm_{k}": v for k, v in arm_action.items()}

        # Add velocity features for arm joints
        arm_vel = {
            'arm_shoulder_pan.vel': 0.0,
            'arm_shoulder_lift.vel': 0.0,
            'arm_elbow_flex.vel': 0.0,
            'arm_wrist_flex.vel': 0.0,
            'arm_wrist_roll.vel': 0.0,
            'arm_gripper.vel': 0.0,
        }
        arm_action.update(arm_vel)

        # Get keyboard action and convert to base action
        keyboard_keys = self.keyboard_teleop.get_action()

        # Convert keyboard keys to base velocities using LeKiwi's logic
        speed_levels = [
            {"xy": 0.1, "theta": 30},  # slow
            {"xy": 0.2, "theta": 60},  # medium
            {"xy": 0.3, "theta": 90},  # fast
        ]
        speed_index = 0  # Start at slow
        speed_setting = speed_levels[speed_index]
        xy_speed = speed_setting["xy"]
        theta_speed = speed_setting["theta"]

        x_cmd = 0.0  # m/s forward/backward
        y_cmd = 0.0  # m/s lateral
        theta_cmd = 0.0  # deg/s rotation

        # Map keyboard keys to commands
        # The keyboard teleop returns a set of pressed keys like {'w', 'a', 's', 'd'}
        if keyboard.Key.up in keyboard_keys or 'w' in keyboard_keys:
            x_cmd += xy_speed
        if keyboard.Key.down in keyboard_keys or 's' in keyboard_keys:
            x_cmd -= xy_speed
        if keyboard.Key.left in keyboard_keys or 'a' in keyboard_keys:
            y_cmd += xy_speed
        if keyboard.Key.right in keyboard_keys or 'd' in keyboard_keys:
            y_cmd -= xy_speed
        if 'q' in keyboard_keys:
            theta_cmd += theta_speed
        if 'e' in keyboard_keys:
            theta_cmd -= theta_speed

        # Create base action with velocities
        base_action = {
            'x.vel': x_cmd,
            'y.vel': y_cmd,
            'z.vel': 0.0,
            'theta.vel': theta_cmd,
        }

        # Combine both actions
        return arm_action | base_action

    def send_feedback(self, feedback: dict[str, float]) -> None:
        """Send feedback to both teleops if needed."""
        # Currently neither teleop implements feedback
        pass

    def disconnect(self) -> None:
        """Disconnect both teleops."""
        self.arm_teleop.disconnect()
        self.keyboard_teleop.disconnect()
        logging.info("LeKiwiTeleop disconnected")
