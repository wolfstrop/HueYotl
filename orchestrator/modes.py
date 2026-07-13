import time
import math


class AmbientMode:
    def __init__(
        self,
        base_color: tuple[int, int, int] = (255, 100, 50),
        cycle_speed: float = 0.1,
        brightness: float = 0.5,
    ):
        self.base_color = base_color
        self.cycle_speed = cycle_speed
        self.brightness = brightness
        self._start_time = time.monotonic()

    def process(self) -> tuple[int, int, int]:
        t = (time.monotonic() - self._start_time) * self.cycle_speed

        r = int((math.sin(t) * 0.5 + 0.5) * self.base_color[0] * self.brightness)
        g = int((math.sin(t + 2.094) * 0.5 + 0.5) * self.base_color[1] * self.brightness)
        b = int((math.sin(t + 4.189) * 0.5 + 0.5) * self.base_color[2] * self.brightness)

        return max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b))

    def set_color(self, r: int, g: int, b: int) -> None:
        self.base_color = (r, g, b)
