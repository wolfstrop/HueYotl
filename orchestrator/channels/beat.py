from collections import deque

from audio_analyzer.tempo import TempoTracker


class BeatChannel:
    """Sensor de ritmo: envuelve el TempoTracker y lleva la contabilidad de
    onsets (último, densidad en ventana de 5s). Percepción pura — las figuras
    y los acentos (gestos) son del director.

    La confianza del canal es `tempo.confidence` (lock del PLL).
    """

    def __init__(self, frame_rate: float):
        self._fr = frame_rate
        self.tempo = TempoTracker(frame_rate)
        self.last_onset_frame = 0
        self._onset_frames: deque[int] = deque(maxlen=64)

    def update(self, frame: int, strong_onset: bool) -> None:
        self.tempo.update(frame, strong_onset)
        if strong_onset:
            self.last_onset_frame = frame
            self._onset_frames.append(frame)

    def onset_density(self, frame: int) -> float:
        """Onsets por segundo en los últimos 5s."""
        window = self._fr * 5
        recent = sum(1 for f in self._onset_frames if frame - f <= window)
        return recent / 5.0

    @property
    def confidence(self) -> float:
        return self.tempo.confidence

    def reset(self) -> None:
        self.tempo.reset()
        self.last_onset_frame = 0
        self._onset_frames.clear()
