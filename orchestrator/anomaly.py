"""Auto-bitácora de anomalías: el director conoce sus invariantes ("esto no
debería pasar") y cuando uno se rompe escribe una línea JSONL con el snapshot
de qué estaba haciendo. Para cazar bugs con contexto en vez de adivinar:
"hizo algo raro a la mitad de la rola" → grep del minuto en logs/anomalias.jsonl.
"""

import json
import os
import time


class AnomalyLog:
    def __init__(
        self,
        frame_rate: float,
        path: str | None = None,
        cooldown_seconds: float = 10.0,
        max_bytes: int = 5_000_000,
    ):
        if path is None:
            root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            path = os.path.join(root, "logs", "anomalias.jsonl")
        self.path = path
        self._fr = frame_rate
        self._cooldown = int(frame_rate * cooldown_seconds)
        self._max_bytes = max_bytes
        self._until: dict[str, int] = {}  # tipo → frame hasta el que calla
        self.last: str = ""  # último tipo reportado (para el ⚠️ del debug)
        self.last_frame: int = -(10**9)
        os.makedirs(os.path.dirname(self.path), exist_ok=True)

    def report(self, frame: int, kind: str, snapshot: dict) -> bool:
        """Reporta una anomalía (con cooldown por tipo). True si se escribió."""
        if frame < self._until.get(kind, 0):
            return False
        self._until[kind] = frame + self._cooldown
        self.last = kind
        self.last_frame = frame
        self._rotate_if_big()
        entry = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "tipo": kind, **snapshot}
        try:
            with open(self.path, "a") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass  # la bitácora nunca debe tirar el show
        return True

    def _rotate_if_big(self) -> None:
        try:
            if os.path.getsize(self.path) > self._max_bytes:
                os.replace(self.path, self.path + ".1")  # una generación basta
        except OSError:
            pass

    def reset(self) -> None:
        self._until.clear()
        self.last = ""


# --- Detectores: viven aquí (censo/vigilancia), el director solo los llama ---

def snapshot_of(d) -> dict:
    """Qué estaba haciendo el director — el contexto de una anomalía."""
    return {
        "seg": round(d._frame / d._frame_rate, 1),
        "move": d.move,
        "figura": d.state,
        "color": d.color,
        "socio": d._partner,
        "pendiente": d._pending_color,
        "lead": round(d._lead, 2),
        "foco": round(d.focus, 2),
        "calma": d._fallback,
        "mel_conf": round(d.melody_conf, 2),
        "mel_act": round(d.melody_act, 2),
        "tempo_conf": round(d.tempo.confidence, 2),
        "bpm": round(d.tempo.bpm, 1),
        "energia": round(d._energy_ema, 3),
        "heat": round(d._effect_heat, 2),
        "swell": round(d._swell, 2),
        "fade_left": d._fade_left,
    }


def check_anomalies(
    d, hue: float, dimming: float, in_dip: bool, energy: float, mid: float,
    stepped: bool = False,
) -> None:
    """Invariantes del director: si algo 'que no debería pasar' pasa, va a
    la bitácora con snapshot. Cada chequeo es barato; el cooldown evita spam."""
    fr = d._frame_rate
    # socio == color: el par no tiene a dónde degradar (bug A→A)
    if d.move == "GROOVE" and d._partner == d.color:
        d._anom_partner_eq += 1
        if d._anom_partner_eq > fr:
            d.anomalies.report(d._frame, "socio==color", snapshot_of(d))
    else:
        d._anom_partner_eq = 0
    # color pegado: mide el último cambio VISIBLE del color base (independiente
    # del contador de fatiga, que un escape roto puede resetear sin cambiar nada)
    if d.color != d._anom_prev_color:
        d._anom_prev_color = d.color
        d._anom_color_since = d._frame
    elif (
        d._frame - d._anom_color_since
        > 2.2 * fr * d.tuning.fatigue_seconds
    ):
        d.anomalies.report(d._frame, "color-pegado", snapshot_of(d))
    # transición cuantizada que nunca cayó en un beat
    if (
        d._pending_color is not None
        and d._frame - d._pending_set_frame > 2.5 * d.tempo.period
    ):
        d.anomalies.report(d._frame, "transicion-no-cayo", snapshot_of(d))
    # fallback (~calma) largo CON música sonando: el conductor está perdido
    if d._fallback and energy > 0.3:
        if d._fallback_start < 0:
            d._fallback_start = d._frame
        elif d._frame - d._fallback_start > 20 * fr:
            d.anomalies.report(d._frame, "calma-con-musica", snapshot_of(d))
    else:
        d._fallback_start = -1
    # mando titubeando: el LÍDER COMPROMETIDO cambia de bando muy seguido.
    # (El foco crudo tiembla en 0.5 todo el tiempo — eso lo absorbe la
    # histéresis y NO es anomalía; lo aprendimos de un falso positivo real.)
    # gracia post-blackout: el cambio de sección ES un vuelco musical — el
    # mando pelea unos segundos legítimamente (visto en vivo: los 3 titubeos
    # de una sesión de horas coincidían con apagones de sección)
    in_section_grace = d._frame - d._blackout_until < 6 * fr
    side = 1 if d._lead > 0.55 else (-1 if d._lead < 0.45 else 0)
    if side != 0 and side != d._lead_side and not in_section_grace:
        if d._lead_side != 0:  # flip real (el primer compromiso no cuenta)
            d._focus_crossings.append(d._frame)
            d._focus_crossings = [
                f for f in d._focus_crossings if d._frame - f < 10 * fr
            ]
            # 4+: alternar cada ~3s es música (verso stop-start, visto en
            # vivo sin síntoma visual — el suavizado del lead lo amortigua)
            if len(d._focus_crossings) >= 4:
                d.anomalies.report(
                    d._frame, "mando-titubeando", snapshot_of(d)
                )
        d._lead_side = side
    # salto de hue grande sin ningún gesto que lo justifique
    jump = abs(((hue - d._last_hue + 0.5) % 1.0) - 0.5)
    intentional = (
        stepped  # cambio de base declarado (frontera de figura, corte brusco)
        or in_dip
        or d._fade_left > 0
        or d._frame < d._accent_hit_until
        or d._accent_release_left > 0
        or d._burst_color is not None
        or d._frame <= d._blackout_until
        or d.move == "MONO"  # su cambio de fatiga es seco a propósito
        # figuras de paso DISCRETO: sus saltos de hue son su lenguaje
        or d.state in ("STEPS", "SHADOW", "BOUNCE")
        # cambio CUANTIZADO: salto en el tick de beat = la promesa de la
        # gramática (los swaps A/B de las figuras caen ahí)
        or (d.move == "GROOVE" and d._frame - d._last_beat_frame <= 2)
    )
    if jump > 0.25 and not intentional:
        d.anomalies.report(
            d._frame, "salto-color-sin-gesto",
            {**snapshot_of(d), "salto": round(jump, 3)},
        )
    # luz muerta: dim en el piso con música y sin razón declarada
    if (
        dimming <= d._blackout_floor + 0.03
        and energy > 0.25
        and not (in_dip or d._dry_stop or d.breakdown)
        and d._frame >= d._blackout_until
    ):
        d._low_dim_frames += 1
        if d._low_dim_frames > 5 * fr:
            d.anomalies.report(d._frame, "luz-muerta", snapshot_of(d))
    else:
        d._low_dim_frames = 0
    # OBSERVACIÓN (para la tabla de precedencia): gesto brillante montándose
    # sobre figura oscura — el usuario siente que "las figuras se pisan".
    # Junta cuentas de QUÉ pares chocan; no es bug per se, es censo.
    bright_gesture = (
        d._frame < d._accent_hit_until or d._burst_color is not None
    )
    if bright_gesture and d.state in ("EMBER", "GATE") and dimming > 0.3:
        d.anomalies.report(
            d._frame, "gesto-sobre-oscuro",
            {**snapshot_of(d), "burst": d._burst_color or "-",
             "acento": d._accent_hit_color or "-"},
        )
    # alto en seco con voz presente: falso positivo del detector
    if d._dry_stop and mid > 0.15:
        d._dry_bad_frames += 1
        if d._dry_bad_frames > 0.5 * fr:
            d.anomalies.report(d._frame, "seco-con-voz", snapshot_of(d))
    else:
        d._dry_bad_frames = 0

