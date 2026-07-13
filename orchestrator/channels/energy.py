from collections import deque
from dataclasses import dataclass

import numpy as np


def _clamp01(x: float) -> float:
    return min(1.0, max(0.0, x))


@dataclass
class EnergyReport:
    """Lo que el canal de energía reporta cada frame."""
    level: str           # quiet / low / medium / high / peak
    ema: float           # energía suavizada (para breakdown/secciones)
    norm_energy: float   # posición 0-1 de la energía actual en el rango adaptativo
    envelope: float      # brillo base (piso..techo) según la energía
    section_shift: bool  # cambio brusco de energía (CRUDO, sin cooldown)


class EnergyChannel:
    """Sensor de energía: mantiene el rango adaptativo de la canción
    (percentiles), da el nivel/envolvente de brillo, y detecta cambios bruscos
    de energía (secciones). Percepción pura — no decide color ni dispara nada;
    el cooldown de sección y las reacciones (blackout/surge) son del director.
    """

    def __init__(
        self,
        frame_rate: float,
        history_seconds: float = 45.0,
        recalc_seconds: float = 1.0,
        section_window_seconds: float = 2.0,
        section_delta: float = 0.35,
        dimming_floor: float = 0.2,
        ema_seconds: float = 1.5,
    ):
        self._fr = frame_rate
        self._history: deque[float] = deque(maxlen=int(frame_rate * history_seconds))
        self._recalc_interval = max(1, int(frame_rate * recalc_seconds))
        self._section_frames = max(2, int(frame_rate * section_window_seconds))
        self._section_delta = section_delta
        self._dimming_floor = dimming_floor
        self._ema_alpha = 1.0 / (frame_rate * ema_seconds)
        self._frame = 0
        self.ema = 0.0
        self.thresholds = (0.1, 0.25, 0.45, 0.7)

    def update(self, energy: float, brightness_ceiling: float) -> EnergyReport:
        self._frame += 1
        self._history.append(energy)
        self.ema += (energy - self.ema) * self._ema_alpha
        if self._frame % self._recalc_interval == 0:
            self._recalc()
        return EnergyReport(
            level=self.level_of(energy),
            ema=self.ema,
            norm_energy=self._norm(energy),
            envelope=max(self._dimming_floor, self._dimming(self.ema, brightness_ceiling)),
            section_shift=self._section_shift(),
        )

    def level_of(self, energy: float) -> str:
        t_quiet, t_low, t_med, t_high = self.thresholds
        if energy < t_quiet:
            return "quiet"
        if energy < t_low:
            return "low"
        if energy < t_med:
            return "medium"
        if energy < t_high:
            return "high"
        return "peak"

    def _norm(self, energy: float) -> float:
        """Posición 0-1 de la energía en el rango adaptativo de la canción."""
        t_quiet, _, _, t_high = self.thresholds
        span = max(t_high - t_quiet, 0.05)
        return _clamp01((energy - t_quiet) / span)

    def _dimming(self, energy: float, ceiling: float) -> float:
        t_quiet, _, _, t_high = self.thresholds
        span = max(t_high - t_quiet, 0.05)
        t = (energy - t_quiet) / span
        # techo de brillo en vivo: a menor brillo el ojo NOTA más los cambios de
        # color (percepción logarítmica) y hay más presencia de oscuros
        return 0.10 + (ceiling - 0.10) * _clamp01(t)

    def _recalc(self) -> None:
        if len(self._history) < self._fr * 5:
            return
        vals = np.fromiter(self._history, dtype=np.float64)
        p15, p40, p70, p90 = np.percentile(vals, [15, 40, 70, 90])
        eps = 0.02
        self.thresholds = (
            float(p15),
            float(max(p40, p15 + eps)),
            float(max(p70, p40 + 2 * eps)),
            float(max(p90, p70 + 3 * eps)),
        )

    def _section_shift(self) -> bool:
        if len(self._history) < self._section_frames:
            return False
        values = list(self._history)[-self._section_frames:]
        half = len(values) // 2
        first = sum(values[:half]) / half
        second = sum(values[half:]) / (len(values) - half)
        baseline = max(first, 0.05)
        return abs(second - first) / baseline > self._section_delta

    def reset(self) -> None:
        self._history.clear()
        self._frame = 0
        self.ema = 0.0
        self.thresholds = (0.1, 0.25, 0.45, 0.7)
