"""GestureBus: los GOLPES encima de la figura — bus de acentos con
prioridad y despedida, punch/patrón 4-8, pozos de oscuridad, flash.
Operan sobre el estado del director (d): el director orquesta, aquí viven
los gestos. Extraído del monolito (lijado de la bolita de aluminio)."""

import math
import random


def _lerp_hue(a: float, b: float, t: float) -> float:
    diff = ((b - a + 0.5) % 1.0) - 0.5
    return (a + diff * t) % 1.0


def accent_pick(d) -> str:
    """Color para golpes (stab/riff/punch): LA DESPEDIDA — "para sacar un
    color hay que ponerlo en el beat". El SALIENTE del deck pone el golpe
    (~60%): el sistema anuncia qué color se va. Si el saliente desentona
    con el mood o es el par activo, carta del deck sin repetir el último."""
    out = d.deck.outgoing
    if (
        out
        and out not in (d.color, d._partner)
        and out not in d.deck.banned
        and d.deck._w(out) > 0.05
        and random.random() < 0.6
    ):
        return out
    c = d.deck.pick(d.color, brusque=True)
    if c == d._accent_last_color:
        c = d.deck.pick(d.color, brusque=True)  # segunda carta
    return c


def fire_accent(
    d, color: str | None, duration: int, prio: int, boost: float
) -> None:
    """Bus de acentos: un solo color de golpe a la vez. Un acento nuevo
    solo pisa al vigente si este ya expiró o si trae mayor prioridad
    (motif > punch > stab/guitarra) — así el motivo no se rompe."""
    if color is None:
        return
    if color in d.deck.banned:  # la veda también aplica a los golpes
        color = d._triad_color if d._triad_color not in d.deck.banned else d._partner
    if d._frame < d._accent_hit_until and prio < d._accent_hit_prio:
        return
    # PISO de código: todo acento dura lo suficiente para VERSE (~0.2s / 0.4
    # beat), pase lo que pase en el toml → el beat nunca es un parpadeo.
    # piso EN BEATS: los golpes de color duran proporcional al tempo —
    # en lentas se saborean ("beats morados más largos"), en rápidas encajan
    min_dur = max(int(0.15 * d._frame_rate), int(0.8 * d.tempo.period))
    d._accent_last_color = color
    d._accent_hit_color = color
    d._accent_hit_until = d._frame + max(min_dur, duration)
    d._accent_hit_prio = prio
    d._accent_hit_boost = boost


def fire_gestures(d, improv, strong_onset, onset_intensity, lead_onset, lead_intensity):
    """Dispara los golpes del frame: stab/motivo/punch/pozo/riff."""
    # Todos los "golpes de color" van al MISMO bus con prioridad. Síncopa
    # (stab) y motivo (doble-golpe) vienen ya rate-limitados del improviser.
    if improv.stab:
        fire_accent(d, 
            accent_pick(d),
            max(int(0.35 * d._frame_rate), int(d.tempo.period)),
            prio=1, boost=0.1,
        )
    if improv.motif:
        if d._motif_color is None:
            # por mood: el motivo es PEGAJOSO toda la sección — si cae en un
            # color fuera de clave lo martilla por minutos (medido: ámbar)
            d._motif_color = d.deck.choose(list(d.deck.principals))
        # prioridad máxima: el motivo NO lo pisa un punch/stab
        fire_accent(d, d._motif_color, int(d.tempo.period), prio=3, boost=0.25)

    # Golpe de color: onset fuerte EN el beat (kick/tambor) trae el tercer
    # color por un instante y regresa en seco. Cooldown → puñetazo, no rotación.
    if d._punch_cooldown > 0:
        d._punch_cooldown -= 1
    if (
        d.move == "GROOVE"
        and strong_onset
        and onset_intensity >= d._punch_intensity
        and d._punch_cooldown == 0
        and d._beat_accent_left == 0  # no arrancar patrón sobre otro
        and random.random() < d._lead  # solo si el BEAT lidera (comprometido)
        and d._effect_heat < 1.5       # presupuesto: no si ya hay muchos efectos
        and not d._fallback            # nada claro → no golpear
    ):
        # arranca un PATRÓN rítmico: el color de acento golpea en los próximos
        # 4 u 8 tiempos (se mantiene en el ritmo), no un golpe suelto que se corta
        d._effect_heat += 1.0
        d._beat_accent_color = accent_pick(d)  # la despedida pone el beat
        d._beat_accent_left = random.choice([4, 8])
        fire_accent(d, d._beat_accent_color, 0, prio=2, boost=0.2)  # el 1er golpe ya
        d._beat_accent_left -= 1
        # más intensidad → cooldown más corto → acentos más densos
        base = int(d._frame_rate * d.tuning.punch_cooldown_seconds)
        d._punch_cooldown = d._jit(
            int(base * (1.0 - 0.6 * d.dyn.intensity * d.tuning.dynamics_strength))
        )
    elif (
        d.move == "GROOVE"
        and strong_onset
        and onset_intensity >= d._punch_intensity
        and d._punch_cooldown == 0
        and d._lead < 0.5              # la MELODÍA lidera
        and not d._fallback
        and d.tuning.rhythm_dark > 0.0
    ):
        # RITMO EN EJE OSCURO: cuando la melodía lidera, el beat NO se calla
        # ni compite en brillo — golpea con un POZO de oscuridad corto. La
        # melodía maneja el brillo, el ritmo la sombra: ejes separados.
        d._dark_pulse_until = d._frame + max(
            int(0.12 * d._frame_rate), int(0.3 * d.tempo.period)
        )
        d._punch_cooldown = d._jit(
            int(d._frame_rate * d.tuning.punch_cooldown_seconds * 0.7)
        )

    # Accent por riff de guitarra/lead
    if (
        d.move == "GROOVE"
        and lead_onset
        and lead_intensity >= d._accent_intensity
        and d._frame >= d._accent_block_until
    ):
        fire_accent(d, 
            accent_pick(d),
            int(d.tempo.period), prio=1, boost=0.0,
        )
        d._effect_heat += 0.7  # el riff consume presupuesto → suprime punches/flash encima
        cooldown_beats = d._accent_min_measures * d._beats_per_measure
        d._accent_block_until = d._frame + int(cooldown_beats * d.tempo.period)


def overlay_gestures(d, hue, dimming, improv):
    """Pinta los golpes encima del render: override de acento + cola +
    bump + pozo oscuro. Devuelve (hue, dimming)."""
    # Override único desde el bus de acentos (solo si no hay crossfade:
    # el fade gana). Un color de golpe a la vez, ya resuelto por prioridad.
    if (
        d._fade_left == 0
        and d._frame < d._accent_hit_until
        and d._accent_hit_color
    ):
        hue = d.grammar.hue(d._accent_hit_color)  # el COLOR cambia entero
        # ...pero el brillo del golpe se atenúa: gesto de beat (×_lead) × perilla.
        # Así el golpe se ve como CAMBIO DE COLOR, no como destello de luz.
        dimming = min(
            1.0,
            dimming + d._accent_hit_boost * d._lead * d.tuning.gesture_brightness,
        )
        # armar la COLA: al expirar el golpe, regresa DIFUMINADO al color base
        # (el inverso del fade→snap que ya existía: snap→fade)
        d._accent_release_hue = hue
        d._accent_release_left = d._accent_release_total = max(
            1, int(0.5 * d.tempo.period)
        )
    elif d._accent_release_left > 0 and d._fade_left == 0:
        t = d._accent_release_left / d._accent_release_total
        hue = _lerp_hue(hue, d._accent_release_hue, t)
        d._accent_release_left -= 1

    dimming = min(1.0, dimming + improv.bump * d.tuning.gesture_brightness)

    # RITMO EN EJE OSCURO: el pozo de oscuridad del beat (melodía lidera)
    if d._frame < d._dark_pulse_until:
        dimming *= 1.0 - 0.55 * d.tuning.rhythm_dark
    return hue, dimming

def update_flash(d, onset, onset_intensity, level, in_dip):
    """Envelope del flash blanco (decae al ritmo). Devuelve flash."""
    # Flash blanco que DECAE al ritmo: se dispara en el golpe y baja lineal
    # hasta ~0 en el siguiente beat (envelope propio del director).
    if d._flash_env > 0.0:
        d._flash_env = max(0.0, d._flash_env - d._flash_step)
    if (
        d._flash_enabled
        and onset
        and onset_intensity >= d.tuning.flash_intensity
        and level == "peak"  # solo en los picos reales → el flash es especial, no constante
        and d._flash_cooldown == 0
        and not in_dip
        and d._lead > 0.4          # solo cuando el beat lidera (comprometido)
        and d._effect_heat < 1.5   # presupuesto de actividad
        and not d._fallback        # nada claro → no destellar
    ):
        d._effect_heat += 1.0
        d._flash_env = onset_intensity
        d._flash_step = onset_intensity / max(1.0, d.tuning.flash_beats * d.tempo.period)
        d._flash_cooldown = d._jit(
            int(d._frame_rate * d.tuning.flash_cooldown_seconds)
        )
    flash = d._flash_env
    return flash
