class BrightnessSmoothing:
    def __init__(self, alpha_up: float = 0.95, alpha_down: float = 0.3):
        self.alpha_up = alpha_up
        self.alpha_down = alpha_down
        self._value = 0.0

    def update(self, value: float) -> float:
        alpha = self.alpha_up if value > self._value else self.alpha_down
        self._value = alpha * value + (1 - alpha) * self._value
        return self._value

    def reset(self, value: float = 0.0) -> None:
        self._value = value
