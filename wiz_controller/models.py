from dataclasses import dataclass
from enum import Enum


class CommandType(Enum):
    RGB = "rgb"
    BRIGHTNESS = "brightness"
    SCENE = "scene"
    ON = "on"
    OFF = "off"


@dataclass
class RGBCommand:
    r: int
    g: int
    b: int
    brightness: int | None = None

    def __post_init__(self):
        self.r = max(0, min(255, self.r))
        self.g = max(0, min(255, self.g))
        self.b = max(0, min(255, self.b))
        if self.brightness is not None:
            self.brightness = max(0, min(255, self.brightness))


@dataclass
class BrightnessCommand:
    brightness: int

    def __post_init__(self):
        self.brightness = max(0, min(255, self.brightness))


@dataclass
class SceneCommand:
    scene_id: int
    speed: int | None = None

    def __post_init__(self):
        self.scene_id = max(1, min(35, self.scene_id))
        if self.speed is not None:
            self.speed = max(0, min(100, self.speed))


@dataclass
class OnCommand:
    brightness: int | None = None
    kelvin: int | None = None


@dataclass
class OffCommand:
    pass
