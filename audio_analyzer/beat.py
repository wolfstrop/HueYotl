from collections import deque

import numpy as np


class OnsetDetector:
    """Onsets via Superflux-lite sobre bandas logarítmicas.

    - Whitening adaptativo: cada banda se normaliza por su propio pico
      reciente (decae en ~3s) → sensibilidad pareja en todo el espectro,
      sin importar cómo esté mezclada la canción
    - Flux con max-filter de bandas vecinas del frame anterior → inmune
      al vibrato de la voz (el clásico falso onset del cantante)
    - Máscara por rango: "low" para el ritmo (kick/caja), "mid" para
      guitarras/leads (rasgueos, riffs)
    """

    def __init__(
        self,
        band_centers: np.ndarray,
        frame_rate: float,
        flux_threshold: float = 0.5,
        cooldown_ms: int = 300,
        history_size: int = 43,
        energy_gate: float = 0.25,
        min_intensity: float = 0.3,
        flux_band: str = "low",
        whiten_decay_seconds: float = 3.0,
    ):
        self.cooldown_samples = max(1, int(cooldown_ms * frame_rate / 1000))
        if flux_band == "mid":
            self._mask = (band_centers >= 150) & (band_centers <= 4000)
        else:
            self._mask = band_centers < 2000
        if not self._mask.any():
            self._mask = np.ones(len(band_centers), dtype=bool)

        self._whiten_decay = float(np.exp(-1.0 / (frame_rate * whiten_decay_seconds)))
        self._peaks = np.full(len(band_centers), 1e-4)
        self._prev_white: np.ndarray | None = None
        self._flux_history: deque = deque(maxlen=history_size)
        self._threshold_cache: float | None = None
        self._threshold_age = 0
        self._cooldown_counter = 0
        self._onset = False
        self._intensity = 0.0
        self._base_threshold = flux_threshold
        self._energy_gate = energy_gate
        self._min_intensity = min_intensity

    def process(self, bands: np.ndarray, energy: float = 1.0) -> tuple[bool, float]:
        self._onset = False
        self._intensity = 0.0

        if self._cooldown_counter > 0:
            self._cooldown_counter -= 1

        # Whitening adaptativo: pico por banda con decaimiento lento
        self._peaks = np.maximum(bands, self._peaks * self._whiten_decay)
        self._peaks = np.maximum(self._peaks, 1e-4)
        white = bands / self._peaks

        if self._prev_white is None:
            self._prev_white = white
            return False, 0.0

        # Superflux: comparar contra el MÁXIMO de bandas vecinas del frame
        # anterior — el vibrato mueve energía entre vecinas, un golpe no
        prev = self._prev_white
        neighbor_max = np.maximum(
            prev,
            np.maximum(
                np.concatenate(([prev[0]], prev[:-1])),
                np.concatenate((prev[1:], [prev[-1]])),
            ),
        )
        flux = float(np.sum(np.maximum(0.0, white - neighbor_max)[self._mask]))
        self._prev_white = white

        if energy < self._energy_gate:
            return False, 0.0

        self._flux_history.append(flux)
        # p75 cada 8 frames (np.percentile por frame costaba ~0.3ms)
        self._threshold_age += 1
        if self._threshold_age >= 8 or self._threshold_cache is None:
            self._threshold_age = 0
            self._threshold_cache = self._adaptive_threshold()
        threshold = self._threshold_cache

        if flux > threshold and self._cooldown_counter <= 0:
            intensity = min(1.0, flux / max(threshold * 3, 0.001))
            if intensity >= self._min_intensity:
                self._onset = True
                self._intensity = intensity
                self._cooldown_counter = self.cooldown_samples

        return self._onset, self._intensity

    def _adaptive_threshold(self) -> float:
        if len(self._flux_history) < 5:
            return self._base_threshold
        recent = list(self._flux_history)
        p75 = float(np.percentile(recent, 75))
        return max(self._base_threshold, p75 * 2.0)

    @property
    def is_onset(self) -> bool:
        return self._onset

    @property
    def onset_intensity(self) -> float:
        return self._intensity
