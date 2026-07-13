from dataclasses import dataclass


def _clamp01(x: float) -> float:
    return min(1.0, max(0.0, x))


@dataclass
class Mix:
    """La resolución del conductor este frame."""
    lead: float      # 0 = melodía manda el gesto, 1 = beat manda (COMPROMETIDO)
    focus: float     # foco crudo (suavizado, pre-histéresis) — para debug
    fallback: bool   # ni melodía ni beat confiables → respirar en mood, no gritar


class Conductor:
    """Árbitro del director-de-orquesta. Decide QUIÉN lidera el gesto
    (melodía ↔ beat) por sus CONFIANZAS, con histéresis para no titubear en el
    borde. Si nadie está seguro (pasaje ambiguo, crescendo, break), entra en
    FALLBACK: la señal para calmarse y sostener el mood en vez de saturar.

    El foco crudo combina tres pistas: groove (ritmo marcado sube), prominencia
    de la banda media (melodía presente baja) y —lo nuevo— la DIFERENCIA de
    confianzas beat vs melodía (tempo lock vs tonalness). El sesgo de esa
    diferencia es calibrable en vivo (melody_lead_bias).
    """

    def __init__(self, frame_rate: float, fallback_conf: float = 0.22):
        self._fr = frame_rate
        self._fallback_conf = fallback_conf
        self.focus = 0.5
        self.lead = 0.5
        self._lead_target = 0.5
        self._mel_slow = 0.0  # promedio lento de la confianza de melodía (des-atasco)

    def update(
        self,
        melody_conf: float,
        beat_conf: float,
        groove: float,
        mid_prom: float,
        lead_bias: float,
    ) -> Mix:
        focus_raw = _clamp01(
            0.5
            + (groove - 0.45) * 1.5
            - (mid_prom - 0.35) * 2.0
            + (beat_conf - melody_conf) * lead_bias
        )
        self.focus += (focus_raw - self.focus) * (1.0 / self._fr)  # ~1s
        # DES-ATASCO: si la melodía se DESPLOMA (fin/cambio de frase) no esperes el
        # ~1s de suavizado — empuja el foco al beat de inmediato, así el cambio de
        # color cae en ritmo en vez de quedarse "buscando melodía".
        if melody_conf < self._mel_slow - 0.15 and self.lead < 0.5:
            self.focus = min(1.0, self.focus + 0.25)
        self._mel_slow += (melody_conf - self._mel_slow) * (1.0 / (self._fr * 0.5))
        # histéresis: se compromete con beat (>0.62) o melodía (<0.38) y se PEGA
        # hasta cruzar decididamente el otro lado → no oscila en 0.5
        if self.focus > 0.62:
            self._lead_target = 1.0
        elif self.focus < 0.38:
            self._lead_target = 0.0
        self.lead += (self._lead_target - self.lead) * (1.0 / (self._fr * 0.6))
        fallback = max(melody_conf, beat_conf) < self._fallback_conf
        return Mix(lead=self.lead, focus=self.focus, fallback=fallback)

    def bias_beat(self, amount: float) -> None:
        """Empuje inmediato del foco hacia el beat (para transiciones): no espera
        el suavizado — desatasca el mando cuando hay que cambiar en ritmo."""
        self.focus = min(1.0, self.focus + amount)

    def reset(self) -> None:
        self.focus = 0.5
        self.lead = 0.5
        self._lead_target = 0.5
        self._mel_slow = 0.0
