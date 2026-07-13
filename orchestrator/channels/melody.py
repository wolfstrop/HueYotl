from dataclasses import dataclass


def _clamp01(x: float) -> float:
    return min(1.0, max(0.0, x))


@dataclass
class MelodyReport:
    """Lo que el canal de melodía reporta cada frame."""
    contour: float       # ~130ms — señal base (posición relativa del centroide)
    contour_mid: float   # ~0.35s — para el COLOR (contorno, no cada nota)
    contour_slow: float  # ~0.8s  — para el BRILLO (forma, no vibra)
    confidence: float    # tonalness — ¿hay melodía real o es batería/ruido?
    activity: float      # cuánto se MUEVE el contorno (0 = nota sostenida/estática)


class MelodyChannel:
    """Sensor de melodía: sigue el CONTORNO relativo del centroide melódico
    (banda media, sin batería) en tres escalas de tiempo, y reporta la
    CONFIANZA de que hay melodía real (tonalness). No decide color — percibe.

    El rango es adaptativo: el piso baja rápido/sube lento y el techo al revés,
    así el contorno (0-1) sigue la FORMA de la melodía sea la canción grave o
    aguda, sin pegarse a un extremo.
    """

    def __init__(self, frame_rate: float):
        self._fr = frame_rate
        self._lo = 0.5
        self._hi = 0.5
        self.contour = 0.5
        self.contour_mid = 0.5
        self.contour_slow = 0.5
        self.confidence = 0.0
        self.activity = 0.0

    def update(self, centroid: float, tonalness: float) -> MelodyReport:
        if centroid < self._lo:
            self._lo = centroid
        else:
            self._lo += (centroid - self._lo) * 0.0006  # recentra el piso lento
        if centroid > self._hi:
            self._hi = centroid
        else:
            self._hi += (centroid - self._hi) * 0.0006  # recentra el techo lento
        span = max(0.12, self._hi - self._lo)
        raw = _clamp01((centroid - self._lo) / span)
        prev = self.contour
        self.contour += (raw - self.contour) * 0.02  # ~130ms — señal base
        # ACTIVIDAD: cuánto se mueve el contorno (~0.5s). Una nota sostenida a
        # todo pulmón es muy TONAL pero estática → tonal sin movimiento no es
        # melodía que seguir, es un momento de swell. Distingue ambos casos.
        act_raw = _clamp01(abs(self.contour - prev) * self._fr * 0.5)
        self.activity += (act_raw - self.activity) * (1.0 / (self._fr * 0.5))
        # contorno MEDIO (~0.35s) para el COLOR: sigue la voz sin temblar con
        # cada inflexión/vibrato (voz acústica en vivo movía mucho)
        self.contour_mid += (self.contour - self.contour_mid) * (1.0 / (self._fr * 0.35))
        # contorno LENTO (~0.8s) para el BRILLO: la forma, no cada nota → no vibra
        self.contour_slow += (self.contour - self.contour_slow) * (1.0 / (self._fr * 0.8))
        self.confidence = tonalness  # ya viene suavizada del analizador
        return MelodyReport(
            self.contour, self.contour_mid, self.contour_slow,
            self.confidence, self.activity,
        )

    def reset(self) -> None:
        self.__init__(self._fr)
