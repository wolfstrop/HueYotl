"""Los MOVES: cómo pinta cada modo del director — FLOW (deriva orgánica +
RIFF por notas), MONO (drama respirando) y GROOVE (corredor de figuras con
beats/pending/ráfaga). Operan sobre el estado del director (d)."""

import math
import random

from rgb_mapper.grammar import SHADOW_HUE

from .figures import FigureContext
from .gestures import fire_accent


def _lerp_hue(a: float, b: float, t: float) -> float:
    diff = ((b - a + 0.5) % 1.0) - 0.5
    return (a + diff * t) % 1.0


def _clamp01(x: float) -> float:
    return min(1.0, max(0.0, x))


def render_move(d, level: str, phase: float) -> tuple[float, float, bool]:
    # BRILLO ← DINÁMICA MUSICAL: la intensidad (0.4s) hace el cuerpo y el
    # crescendo (trend subiendo) el SWELL — el brillo respira con la FRASE.
    # En lo bajo se hunde (recupera el juego oscuro); no es destello por golpe.
    cresc = _clamp01(d.dyn.trend / max(0.05, d.tuning.surge_threshold))
    swell = _clamp01(d.dyn.intensity * 0.75 + cresc * 0.25)
    # curva: hunde los medios (juego oscuro) y reserva el brillo para picos/crescendo
    dyn_dim = 0.06 + (d.tuning.brightness_ceiling - 0.06) * swell ** 1.4
    w = d.tuning.brightness_dynamics
    base_dim = d._energy_envelope * (1.0 - w) + dyn_dim * w
    # SWELL de nota sostenida: build encima de la envolvente — crece con la
    # nota (a todo pulmón) y se suelta al soltarla. Gesto de LD, no acento.
    base_dim = _clamp01(
        base_dim + d._swell * 0.45 * d.tuning.swell_strength
    )
    # "MÁS COLOR, NO MÁS BRILLO": en el oscuro puro (EMBER) la intensidad NO
    # empuja el brillo hacia arriba (eso mataba el juego oscuro: "va al rojo
    # y quiere más brillo") — se expresa como VELOCIDAD de cambio de color.
    if d.move == "GROOVE" and d.state == "EMBER":
        base_dim = min(base_dim, d.tuning.brightness_ceiling * 0.55)
    glow = _clamp01(d.glow) * d._glow_gain

    if d.move == "GROOVE":
        return render_groove(d, level, phase, base_dim, glow)

    if d.move == "MONO":
        d.state = "-"
        d._wobble_phase += d._wobble_speed
        hue = (d.grammar.hue(d.color) + 0.02 * math.sin(d._wobble_phase)) % 1.0
        return hue, min(1.0, base_dim + 0.15 * glow), False

    # RIFF (reloj melódico v1): cuando la melodía ES el ritmo — notas
    # rápidas (tararara-tururú) con la melodía al mando — el color CAMBIA
    # POR NOTA entre el color y el socio, seco. La deriva no puede seguir
    # eso; el reloj de notas sí. Escaso a propósito: pide tasa sostenida.
    mc = d.melody_channel
    if mc.note_rate >= 2.0 and mc.confidence > 0.35 and d._lead < 0.5:
        d.state = "RIFF"
        if mc.note_tick:
            d._riff_side = 1 - d._riff_side
        hue = d.grammar.hue(
            d.color if d._riff_side == 0 else d._flow_partner
        )
        mel_b = math.tanh((d._melody_bright_c - 0.5) * 2.2) * 0.5 * d.tuning.melody_bright
        return hue, min(0.85, _clamp01(base_dim + 0.12 * glow + mel_b)), False

    # FLOW: deriva orgánica con INERCIA (Fase 3 recuperada) por caminos de
    # la gramática — solo entre fade-partners, así nunca choca. El pitch
    # acelera (agudo) o frena (grave); el onset da una patada al movimiento;
    # al llegar al socio, se elige un nuevo socio fundible (camina el grafo).
    d.state = "-"
    target = d.grammar.hue(d._flow_partner)
    diff = ((target - d._flow_hue + 0.5) % 1.0) - 0.5
    # velocidad-crucero hacia el socio; melodía aguda acelera (1.5x), grave frena (0.5x)
    pitch_accel = 0.5 + _clamp01(d._melody_mid)
    desired = math.copysign(d._flow_speed * pitch_accel, diff or 1.0)
    d._flow_vel += (desired - d._flow_vel) * d._flow_ease  # inercia
    if d._last_onset_frame == d._frame:  # el onset da una patada
        d._flow_vel += math.copysign(d._flow_kick, diff or 1.0)
    cap = 6 * d._flow_speed
    d._flow_vel = max(-cap, min(cap, d._flow_vel))
    d._flow_hue = (d._flow_hue + d._flow_vel) % 1.0
    if abs(diff) < 0.01:
        d._flow_arrivals += 1
        if d._flow_arrivals % 3 == 0:
            # cada 3 llegadas: SALTA a un color nuevo del deck (mueve paleta)
            d.color = d._flow_partner
            partners = [
                p
                for p in d.grammar.fade_partners(d._flow_partner)
                if p in d.deck.principals or p == d.deck.incoming
            ] or d.grammar.fade_partners(d._flow_partner)
            if partners:
                # ponderado por mood: la deriva no se fuga de la clave
                d._flow_partner = d.deck.choose(partners)
        else:
            # ping-pong: regresa al color anterior → JUEGA entre 2, no avanza
            d.color, d._flow_partner = d._flow_partner, d.color
    # brillo sigue el contorno lento CON AGC (swing garantizado: riffs y
    # piano de pocas notas también respiran — medido: sin AGC llegaba ±6%),
    # con PLATEAU en los extremos (tanh) para no blanquear en la voz aguda
    mel_bright = math.tanh((d._melody_bright_c - 0.5) * 2.2) * 0.5 * d.tuning.melody_bright
    return d._flow_hue, min(0.85, _clamp01(base_dim + 0.12 * glow + mel_bright)), False


def render_groove(
    d, level: str, phase: float, base_dim: float, glow: float
) -> tuple[float, float, bool]:
    ahead = d._frame + d._lookahead
    beat_idx = d.tempo.beat_index(ahead)
    changed = False

    if d._last_beat_idx == -1:
        d._last_beat_idx = beat_idx
        d._last_beat_frame = d._frame
    else:
        crossed = (
            beat_idx != d._last_beat_idx
            and d._frame - d._last_beat_frame >= 0.5 * d.tempo.period
        )
        # Respaldo por TIEMPO: si el PLL se atora (onsets ambiguos en un
        # pasaje sostenido), tickea igual cada periodo → la figura NUNCA se
        # congela esperando un beat que no llega.
        timeout = d._frame - d._last_beat_frame >= d.tempo.period
        if crossed or timeout:
            # actualizar el índice SOLO al tickear: si el guard de 0.5·periodo
            # suprime un cruce, el tick se DIFIERE (antes se perdía → la
            # paridad de GATE y los patrones 4/8 se corrompía y "se desfasaba")
            d._last_beat_idx = beat_idx
            d._last_beat_frame = d._frame
            d._beat_count += 1
            # TRANSICIÓN cuantizada: el color de transición cae EN el beat
            # (no a destiempo), con fundido corto → cambio limpio en ritmo.
            if d._pending_color is not None:
                d.color = d._pending_color
                d._pending_color = None
                d._partner = d._pick_partner()
                d._start_fade()
            if d._figure is not None:
                d._figure.on_beat(d._beat_count - d._figure_start_beat)
            # patrón rítmico: el acento golpea cada 2° tiempo (destellos
            # espaciados, no un relleno) durante la ventana de 4/8 tiempos
            if d._beat_accent_left > 0 and d._beat_accent_color:
                d._beat_accent_left -= 1
                if d._beat_accent_left % 2 == 0:
                    fire_accent(d, d._beat_accent_color, 0, prio=2, boost=0.2)
            # RÁFAGA: cuando el ritmo GRITA (groove+intensidad altos y el
            # beat manda), el color CAMBIA SECO cada beat ciclando la tríada
            # — cambios de color rítmicos, no una figura suave. Es COLOR al
            # ritmo, no brillo (los ejes no compiten).
            if (
                d.tuning.burst_drive < 1.0
                and d.dyn.groove > d.tuning.burst_drive
                and d.dyn.intensity > 0.45
                and d._lead > 0.65
                and not d._fallback
            ):
                d._burst_idx += 1
                cycle = (d.color, d._partner, d._triad_color)
                d._burst_color = cycle[d._burst_idx % 3]
            else:
                d._burst_color = None

    beats_done = d._beat_count - d._figure_start_beat
    # tope por TIEMPO además de por beats: en tempo lento/ambiguo una figura
    # no debe estirarse a >figure_max_seconds sosteniendo un color (congelamiento)
    too_long = (
        d._frame - d._figure_start_frame
        > d._frame_rate * d.tuning.figure_max_seconds
    )
    # PRECEDENCIA #1 (del censo, SOAD): si la RÁFAGA está activa, EMBER es
    # la figura equivocada — íntima y oscura bajo un ritmo que grita. Cede.
    incoherent = d._burst_color is not None and (
        d._figure is not None and d._figure.name == "EMBER"
    )
    if (
        d._figure is None
        or beats_done >= d._figure.total_beats
        or too_long
        or incoherent
    ):
        changed = d._next_figure()
        beats_done = 0

    d.state = d._figure.name
    ctx = FigureContext(
        phase=phase,
        beats_done=beats_done,
        beats_per_measure=d._beats_per_measure,
        hue_a=d.grammar.hue(d.color),
        hue_b=d.grammar.hue(d._partner),
        base_dim=base_dim,
        glow=glow,
        pitch=d._melody_mid,
        pitch_gain=d._pitch_gain * (1.0 - d._lead),  # melodía calla si el beat lidera
        aggression=d.dyn.intensity * d.tuning.dynamics_strength,
        shadow_hue_blend=d._shadow_blend,
        shadow_hue=SHADOW_HUE,
        shadow_dim=d._shadow_dim,
    )
    hue, dim = d._figure.render(ctx)
    if d._burst_color is not None:
        hue = d.grammar.hue(d._burst_color)  # ráfaga: color seco por beat
    return hue, dim, changed

