import statistics
from collections import deque


class TempoTracker:
    """Estima periodo y fase del beat con un PLL simple sobre los onsets.

    Con esto el director puede PREDECIR el siguiente beat y disparar cambios
    con anticipación (compensación de latencia), en vez de reaccionar tarde.
    """

    def __init__(
        self,
        frame_rate: float,
        min_bpm: float = 60.0,
        max_bpm: float = 180.0,
    ):
        self._frame_rate = frame_rate
        self._min_period = 60.0 / max_bpm * frame_rate
        self._max_period = 60.0 / min_bpm * frame_rate
        self._period = frame_rate * 0.5  # arranque en 120 BPM
        self._origin = 0.0
        self._last_onset: int | None = None
        self._intervals: deque[float] = deque(maxlen=12)
        self._hits: deque[int] = deque(maxlen=8)
        # aciertos con ventana ESTRECHA (±12%): el azar no la puede fingir
        # (la de confidence es ±30% = el 60% del beat; ruido acierta seguido)
        self._tight: deque[int] = deque(maxlen=12)

    def update(self, frame: int, onset: bool) -> None:
        if not onset:
            return

        if self._last_onset is not None:
            ioi = float(frame - self._last_onset)
            if self.confidence >= 0.5:
                # Con lock: plegar RELATIVO al periodo vigente. En una balada a
                # 75bpm la corchea (periodo/2) es un periodo válido del rango
                # global (150bpm) → ambigüedad métrica que rompía el lock.
                # Duplicar/dividir hasta la octava del periodo cubre CUALQUIER
                # subdivisión (el set fijo ×0.25-4 se quedaba corto con
                # semicorcheas rápidas → regularity moría → ráfaga muerta).
                while ioi < self._period / 1.5:
                    ioi *= 2
                while ioi > self._period * 1.5:
                    ioi /= 2
                valid = abs(ioi - self._period) <= 0.45 * self._period
            else:
                # Sin lock: plegado global (como antes)
                while ioi < self._min_period:
                    ioi *= 2
                while ioi > self._max_period and ioi / 2 >= self._min_period:
                    ioi /= 2
                valid = self._min_period <= ioi <= self._max_period
            if valid:
                self._intervals.append(ioi)
                median = statistics.median(self._intervals)
                # Ganancia ADAPTATIVA: si la mediana se corre consistentemente
                # (baterista humano acelerando/frenando — discos en vivo), seguir
                # más rápido; estable = suave como antes.
                err = abs(median - self._period) / self._period
                gain = min(0.6, 0.25 + 8.0 * max(0.0, err - 0.01))
                self._period += gain * (median - self._period)
                self._period = max(
                    self._min_period, min(self._max_period, self._period)
                )

        # Corrección de fase: ¿el onset cayó donde predijimos un beat?
        error = ((frame - self._origin + self._period / 2) % self._period) - self._period / 2
        self._tight.append(1 if abs(error) <= self._period * 0.12 else 0)
        if abs(error) <= self._period * 0.3:
            self._origin += 0.35 * error
            self._hits.append(1)
        else:
            self._hits.append(0)
            if sum(self._hits) <= 2:
                # Perdimos el lock: re-anclar al onset actual
                self._origin = float(frame)

        self._last_onset = frame

    def phase(self, frame: float) -> float:
        """Posición dentro del beat (0=en el beat, 0.5=contratiempo)."""
        return ((frame - self._origin) % self._period) / self._period

    def beat_index(self, frame: float) -> int:
        return int((frame - self._origin) // self._period)

    @property
    def confidence(self) -> float:
        if len(self._hits) < 4:
            return 0.0
        return sum(self._hits) / len(self._hits)

    @property
    def precision(self) -> float:
        """Qué tan CLAVADOS caen los onsets en el beat predicho (ventana ±12%).
        El ruido no la puede fingir — para figuras que exigen fase (GATE)."""
        if len(self._tight) < 8:
            return 0.0
        return sum(self._tight) / len(self._tight)

    @property
    def bpm(self) -> float:
        return 60.0 * self._frame_rate / self._period

    @property
    def period(self) -> float:
        """Periodo estimado del beat, en frames."""
        return self._period

    @property
    def regularity(self) -> float:
        """0 = onsets caóticos (rock, fills), 1 = beat de máquina (electrónica).

        Fracción de intervalos recientes a ±20% del periodo estimado (robusto
        al plegado de corcheas/compases, que infla la varianza).
        """
        if len(self._intervals) < 4 or self._period <= 0:
            return 0.0
        near = sum(1 for ioi in self._intervals if abs(ioi - self._period) / self._period < 0.2)
        return near / len(self._intervals)

    def reset(self) -> None:
        self._origin = 0.0
        self._last_onset = None
        self._intervals.clear()
        self._hits.clear()
        self._tight.clear()
        self._period = self._frame_rate * 0.5
