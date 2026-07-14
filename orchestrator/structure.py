"""Estructura temporal: los TIMERS y DETECTORES que puntúan la canción —
blackout de sección, micro-apagón, breakdown, alto en seco, rotación de
paleta con momentum y la veda de colores. Operan sobre el director (d)."""

import random

from .gestures import fire_accent


def trigger_blackout(d) -> None:
    contrast = d.grammar.cut_from(d.color)
    d._blackout_reseed = contrast
    d._blackout_until = d._frame + d._blackout_frames


def trigger_micro_black(d) -> None:
    """Apagón cortito de puntuación al cambiar de color base, para que
    el nuevo estalle en vez de fundirse. Con reja de tiempo: si vienen
    muchos seguidos marea, el chiste es el timing."""
    if d._frame < d._micro_black_cooldown:
        return
    d._micro_black_until = d._frame + d._micro_black_frames
    d._micro_black_cooldown = d._frame + d._micro_black_gap_frames


def update_breakdown(d, energy: float, mid: float) -> None:
    """Respiro: la energía cae fuerte pero sigue habiendo voz/medios
    (el cantante solo, la música se calla). Momento de llevar el brillo
    a un extremo. Heurístico y conservador."""
    if not d._breakdown_enabled:
        return
    quiet = energy < d._energy_ema * d._breakdown_ratio and energy > 1e-3
    voice = mid > d._breakdown_voice_min
    if not d.breakdown:
        if quiet and voice:
            d._breakdown_count += 1
            if d._breakdown_count >= d._breakdown_frames:
                d.breakdown = True
        else:
            d._breakdown_count = 0
    elif energy > d._energy_ema * 0.9:
        d.breakdown = False
        d._breakdown_count = 0

def palette_policies(d) -> None:
    """Veda + rotación de fondo con momentum (no interrumpir un build)."""
    # Rotación de FONDO: cada palette_rotate_seconds entra un color NUEVO al
    # pool aunque no cambie la sección → la paleta evoluciona, no cicla los
    # mismos 5 para siempre (lo que se sentía repetitivo en secciones largas).
    # MOMENTUM: si hay una construcción melódica buena en curso (la melodía
    # lidera Y se mueve), el sistema NO la interrumpe — pospone la rotación
    # (con tope 2× para no re-atascar). "Se cambia, no por la música" ← esto.
    # VEDA de colores: cada veda_seconds se vetan 1-2 colores por
    # veda_duration — el MÁS USADO descansa (el ojo lo agradece) y a veces
    # cae uno al azar (sorpresa). Nunca el color en pantalla. Fuerza
    # exploración más allá del heat (idea del usuario).
    if d.tuning.veda_seconds > 0 and (
        d._frame - d._last_veda_frame
        > d._frame_rate * d.tuning.veda_seconds
    ):
        d._last_veda_frame = d._frame
        candidates = [c for c in d.deck.heat if c != d.color]
        victims = [max(candidates, key=lambda c: d.deck.heat[c])]
        if random.random() < 0.5:
            rest = [c for c in candidates if c != victims[0]]
            if rest:
                victims.append(random.choice(rest))
        d.deck.ban(
            victims, int(d._frame_rate * d.tuning.veda_duration)
        )
        # divorcio inmediato: socio/tríada ya elegidos no respetan la veda
        # (la figura los rendería hasta 4s más — medido: 24% de fuga)
        if d._partner in d.deck.banned:
            d._partner = d._pick_partner()
        if d._triad_color in d.deck.banned:
            d._triad_color = d._pick_partner()
        if d._beat_accent_color in d.deck.banned:
            d._beat_accent_color = d._triad_color
        if d._motif_color in d.deck.banned:
            d._motif_color = None  # el próximo motivo se elige de nuevo

    building = (
        d._lead < 0.35 and d.melody_act > 0.35 and d.melody_conf > 0.35
    )
    rotate_frames = int(d._frame_rate * d.tuning.palette_rotate_seconds)
    overdue = d._frame - d._last_promote_frame > 2 * rotate_frames
    if d._frame - d._last_promote_frame > rotate_frames and (
        not building or overdue
    ):
        d.color = d.deck.promote()
        if d._partner == d.color:  # el promovido era el socio → re-elegir
            d._partner = d._pick_partner()
        d._start_fade()
        d._last_promote_frame = d._frame


def dry_stop_update(d, energy: float, mid: float) -> None:
    # ALTO EN SECO: la música se corta de golpe (todo cae, sin voz) → la luz
    # corta YA (sostiene el color casi a oscuras) y REANUDA CON GOLPE cuando
    # la música vuelve. Distinto del breakdown (ahí queda voz/medios).
    if not d._dry_stop:
        if (
            d._energy_ema > 0.15
            and energy < 0.10 * d._energy_ema
            and mid < 0.05
        ):
            d._dry_count += 1
            if d._dry_count >= int(0.15 * d._frame_rate):
                d._dry_stop = True
        else:
            d._dry_count = 0
    elif energy > 0.45 * d._energy_ema:
        d._dry_stop = False
        d._dry_count = 0
        # reanudar con golpe: el tercer color pega al regresar la música
        fire_accent(d, 
            d._triad_color, int(0.5 * d.tempo.period), prio=2, boost=0.15
        )

