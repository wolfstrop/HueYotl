"""Dinámica de la música en DOS ejes independientes + tendencia.

Ritmo ≠ intensidad: Daft Punk tiene ritmo alto e intensidad baja; una clásica
en crescendo tiene intensidad alta y ritmo bajo. El director usa AMBOS para
decidir CUÁNTO jugar (no solo qué). Un modo forzado (fiesta/chill/rock…) sesga
los ejes a propósito.
"""


def _clamp01(x: float) -> float:
    return min(1.0, max(0.0, x))


# Modos: sesgan/clampan los ejes calculados. AUTO = ejes puros.
# (piso_ritmo, techo_ritmo, piso_int, techo_int, ganancia_int)
MODE_BIAS: dict[str, tuple[float, float, float, float, float]] = {
    "auto":      (0.0, 1.0, 0.0, 1.0, 1.0),
    "fiesta":    (0.4, 1.0, 0.55, 1.0, 1.3),   # siempre movido e intenso
    "chill":     (0.0, 0.7, 0.0, 0.4, 0.8),    # tope bajo, tranqui
    "rock":      (0.0, 1.0, 0.0, 1.0, 1.25),   # exagera la intensidad
    "hyperpop":  (0.6, 1.0, 0.3, 1.0, 1.2),    # ritmo alto, juega mucho
    "classical": (0.0, 0.6, 0.0, 1.0, 1.1),    # ritmo bajo, drama por energía
}


class Dynamics:
    """Calcula `groove` (qué tan marcado el beat) e `intensity` (qué tan al
    tope), suavizados e independientes, más `trend` (subiendo/bajando)."""

    def __init__(
        self,
        frame_rate: float,
        groove_tau_seconds: float = 1.0,
        intensity_tau_seconds: float = 0.4,
        slow_tau_seconds: float = 2.5,
        mode: str = "auto",
    ):
        self._groove_alpha = 1.0 / (frame_rate * groove_tau_seconds)
        self._fast_alpha = 1.0 / (frame_rate * intensity_tau_seconds)
        self._slow_alpha = 1.0 / (frame_rate * slow_tau_seconds)
        self.mode = mode if mode in MODE_BIAS else "auto"

        # Valores públicos (ajustados por modo)
        self.groove = 0.0
        self.intensity = 0.0
        # trend = EMA rápida − lenta (estilo MACD): + subiendo, − bajando, ~0
        # en oscilación por beat (se cancela). Robusto a ritmos fuertes.
        self.trend = 0.0
        self._groove_raw = 0.0
        self._fast = 0.0
        self._slow = 0.0

    def update(
        self,
        confidence: float,
        regularity: float,
        onset_density: float,
        energy_norm: float,
    ) -> None:
        """energy_norm = intensidad cruda 0-1 (loudness + posición relativa)."""
        groove_raw = _clamp01(
            0.5 * confidence + 0.3 * regularity + 0.2 * min(1.0, onset_density / 3.0)
        )
        self._groove_raw += (groove_raw - self._groove_raw) * self._groove_alpha

        x = _clamp01(energy_norm)
        self._fast += (x - self._fast) * self._fast_alpha
        self._slow += (x - self._slow) * self._slow_alpha
        self.trend = self._fast - self._slow

        # Salidas públicas = crudo ajustado por modo (sin retroalimentar el filtro)
        gmin, gmax, imin, imax, igain = MODE_BIAS[self.mode]
        self.groove = _clamp01(min(gmax, max(gmin, self._groove_raw)))
        self.intensity = _clamp01(min(imax, max(imin, self._fast * igain)))

    def reset(self) -> None:
        self.groove = 0.0
        self.intensity = 0.0
        self.trend = 0.0
        self._groove_raw = 0.0
        self._fast = 0.0
        self._slow = 0.0
