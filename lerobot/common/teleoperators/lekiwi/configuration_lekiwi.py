from dataclasses import dataclass

from lerobot.common.teleoperators.config import TeleoperatorConfig


@TeleoperatorConfig.register_subclass("lekiwi")
@dataclass
class LeKiwiTeleopConfig(TeleoperatorConfig):
    """Configuration for LeKiwi teleoperator that combines SO100 leader arm and keyboard base control."""
    arm_port: str  # Port for SO100 leader arm
    arm_id: str | None = None  # ID for the SO100 leader arm
    keyboard_id: str | None = None  # ID for the keyboard teleop
