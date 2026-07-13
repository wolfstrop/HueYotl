from collections import deque

import numpy as np
from scipy.signal import butter, sosfilt


class BandAnalyzer:
    def __init__(
        self,
        sample_rate: int = 48000,
        chunk_size: int = 256,
        low: tuple[int, int] = (30, 250),
        mid: tuple[int, int] = (250, 4000),
        high: tuple[int, int] = (4000, 16000),
        auto_calibrate: bool = True,
        calibration_window: int = 200,
        calibration_percentile: float = 0.95,
    ):
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self.auto_calibrate = auto_calibrate
        self.calibration_percentile = calibration_percentile
        nyquist = sample_rate / 2

        self._sos_low = butter(4, [low[0] / nyquist, low[1] / nyquist], btype="band", output="sos")
        self._sos_mid = butter(4, [mid[0] / nyquist, mid[1] / nyquist], btype="band", output="sos")
        self._sos_high = butter(4, [high[0] / nyquist, high[1] / nyquist], btype="band", output="sos")

        self._zi_low = np.zeros((len(self._sos_low), 2))
        self._zi_mid = np.zeros((len(self._sos_mid), 2))
        self._zi_high = np.zeros((len(self._sos_high), 2))

        self._buffer_low = deque(maxlen=calibration_window)
        self._buffer_mid = deque(maxlen=calibration_window)
        self._buffer_high = deque(maxlen=calibration_window)
        self._ceiling_low = 0.5
        self._ceiling_mid = 0.5
        self._ceiling_high = 0.5
        self._frame_count = 0
        self._recalc_interval = 50

    def process(self, chunk: np.ndarray) -> tuple[float, float, float]:
        if len(chunk) < 2:
            return 0.0, 0.0, 0.0

        low_out, self._zi_low = sosfilt(self._sos_low, chunk, zi=self._zi_low)
        mid_out, self._zi_mid = sosfilt(self._sos_mid, chunk, zi=self._zi_mid)
        high_out, self._zi_high = sosfilt(self._sos_high, chunk, zi=self._zi_high)

        low_energy = float(np.sqrt(np.mean(low_out**2)))
        mid_energy = float(np.sqrt(np.mean(mid_out**2)))
        high_energy = float(np.sqrt(np.mean(high_out**2)))

        if self.auto_calibrate:
            # No calibrar con silencio: infla la normalización y las partes
            # quietas (piano, intros) se leen como si fueran fuertes
            if low_energy + mid_energy + high_energy > 1e-4:
                self._buffer_low.append(low_energy)
                self._buffer_mid.append(mid_energy)
                self._buffer_high.append(high_energy)
                self._frame_count += 1

            if self._frame_count >= self._recalc_interval and len(self._buffer_low) >= 20:
                self._frame_count = 0
                p = self.calibration_percentile * 100
                new_low = float(np.percentile(list(self._buffer_low), p))
                new_mid = float(np.percentile(list(self._buffer_mid), p))
                new_high = float(np.percentile(list(self._buffer_high), p))
                if len(self._buffer_low) < self._buffer_low.maxlen // 2:
                    # Warmup: snap directo al nivel real (el techo inicial es
                    # arbitrario; sin esto tarda ~1min en bajar)
                    self._ceiling_low = max(0.01, new_low)
                    self._ceiling_mid = max(0.01, new_mid)
                    self._ceiling_high = max(0.01, new_high)
                else:
                    # Techo con decaimiento lento: sube rápido con partes
                    # fuertes, baja despacio en versos quietos
                    self._ceiling_low = max(0.01, self._ceiling_low * 0.99, new_low)
                    self._ceiling_mid = max(0.01, self._ceiling_mid * 0.99, new_mid)
                    self._ceiling_high = max(0.01, self._ceiling_high * 0.99, new_high)

        return low_energy, mid_energy, high_energy

    def normalize(self, low: float, mid: float, high: float, ceiling: float = 0.5) -> tuple[float, float, float]:
        if self.auto_calibrate:
            return (
                min(1.0, low / self._ceiling_low),
                min(1.0, mid / self._ceiling_mid),
                min(1.0, high / self._ceiling_high),
            )
        return (
            min(1.0, low / ceiling),
            min(1.0, mid / ceiling),
            min(1.0, high / ceiling),
        )
