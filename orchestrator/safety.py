"""Tope DURO anti-estroboscópico (fotosensibilidad / epilepsia).

Es la última capa antes del foco y NO se puede desactivar desde el tuning:
ninguna combinación de perillas puede volver la luz estroboscópica. El umbral
médico relevante es ~3 destellos/segundo; limitamos las transiciones FUERTES de
luminancia (flashes, apagones OFF→ON, cortes secos) a un máximo por segundo.
Un corte ocasional pasa; una ráfaga sostenida se suaviza a transición gradual.
"""

from collections import deque


def _clamp01(x: float) -> float:
    return min(1.0, max(0.0, x))


class SafetyLimiter:
    def __init__(
        self,
        frame_rate: float,
        max_transitions_per_second: int = 3,
        flash_delta: float = 0.4,
        slew_seconds: float = 0.4,
    ):
        self._window = max(1, int(frame_rate))
        self._max = max_transitions_per_second
        self._delta = flash_delta          # salto de luminancia (0-1) que cuenta como flash
        self._slew = 1.0 / (frame_rate * slew_seconds)  # paso gradual por frame al recortar
        self._recent: deque[int] = deque()  # frames de transiciones fuertes recientes
        self._last_lum = 0.0
        self._frame = 0

    def filter(self, r: int, g: int, b: int, dim: int) -> tuple[int, int, int, int]:
        """Devuelve (r, g, b, dim) ya limitado. Si veníamos flasheando de más, un
        salto fuerte de brillo se recorta a rampa gradual en vez de destello."""
        self._frame += 1
        target = dim / 255.0
        while self._recent and self._frame - self._recent[0] > self._window:
            self._recent.popleft()

        if abs(target - self._last_lum) >= self._delta:
            if len(self._recent) >= self._max:
                # demasiadas transiciones fuertes en 1s → recorta a rampa gradual
                # (paso chico por frame → la ráfaga estroboscópica se aplana)
                target = (
                    min(target, self._last_lum + self._slew)
                    if target > self._last_lum
                    else max(target, self._last_lum - self._slew)
                )
            else:
                self._recent.append(self._frame)

        self._last_lum = _clamp01(target)
        return r, g, b, max(10, int(self._last_lum * 255))

    def reset(self) -> None:
        self._recent.clear()
        self._last_lum = 0.0
