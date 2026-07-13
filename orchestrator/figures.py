import math
import random
from dataclasses import dataclass


def _lerp_hue(a: float, b: float, t: float) -> float:
    diff = ((b - a + 0.5) % 1.0) - 0.5
    return (a + diff * t) % 1.0


def _clamp01(x: float) -> float:
    return min(1.0, max(0.0, x))


@dataclass
class FigureContext:
    """Todo lo que una figura necesita para pintar un frame."""

    phase: float           # posición dentro del beat (0 = en el beat)
    beats_done: int        # beats completos transcurridos en la figura
    beats_per_measure: int
    hue_a: float
    hue_b: float
    base_dim: float
    glow: float
    pitch: float           # centroide 0-1 (0 grave, 1 agudo)
    pitch_gain: float      # cuánto sesga el pitch la posición del degradado
    aggression: float      # 0-1 (intensidad): saltos duros vs fundido suave
    shadow_hue_blend: float
    shadow_hue: float
    shadow_dim: float


class Figure:
    """Una figura corre N compases y pinta (hue, dim) por frame.

    Los cambios discretos ocurren SOLO en on_beat() — cuantización a beat
    garantizada por construcción. render() entre beats solo sostiene o
    curva suavemente.
    """

    name = "FIGURE"

    def __init__(self, measures: int, beats_per_measure: int):
        self.total_beats = measures * beats_per_measure

    def on_beat(self, beats_done: int) -> None:
        pass

    def render(self, ctx: FigureContext) -> tuple[float, float]:
        raise NotImplementedError

    def _pitch_pos(self, pos: float, ctx: FigureContext) -> float:
        """Sesgo del degradado por tono: agudo empuja hacia B, grave
        regresa hacia A (el 'regresa al azul claro')."""
        return _clamp01(pos + (ctx.pitch - 0.5) * ctx.pitch_gain)


class ShadowPlay(Figure):
    """La figura original: color pleno alternando con sombras azuladas
    sostenidas 1-2 beats. Puede repetir el mismo color varios compases."""

    name = "SHADOW"

    def __init__(
        self,
        measures: int,
        beats_per_measure: int,
        play_prob: float,
        min_beats: int,
        max_beats: int,
        swap_prob: float,
    ):
        super().__init__(measures, beats_per_measure)
        self._play_prob = play_prob
        self._min_beats = min_beats
        self._max_beats = max_beats
        self._swap_prob = swap_prob
        self._dark = False
        self._until = 0
        self._swapped = False

    def on_beat(self, beats_done: int) -> None:
        if beats_done % self.total_beats == 0 and beats_done > 0:
            return
        if beats_done % 4 == 0 and random.random() < self._swap_prob:
            self._swapped = not self._swapped
        if beats_done >= self._until:
            duration = random.randint(self._min_beats, self._max_beats)
            self._dark = not self._dark if (self._dark or random.random() < self._play_prob) else False
            self._until = beats_done + duration

    def render(self, ctx: FigureContext) -> tuple[float, float]:
        hue = ctx.hue_b if self._swapped else ctx.hue_a
        if self._dark:
            hue = _lerp_hue(hue, ctx.shadow_hue, ctx.shadow_hue_blend)
            shadow = min(ctx.base_dim, ctx.shadow_dim)
            return hue, shadow + ctx.glow * max(0.0, 0.55 - shadow)
        return hue, min(1.0, ctx.base_dim + 0.2 * ctx.glow)


class Breathe(Figure):
    """Un color respirando: brillo sinusoidal lento (el 'corazón')."""

    name = "BREATHE"

    def __init__(self, measures: int, beats_per_measure: int):
        super().__init__(measures, beats_per_measure)
        self._cycle_beats = random.choice([2, 3, 4])

    def render(self, ctx: FigureContext) -> tuple[float, float]:
        t = (ctx.beats_done + ctx.phase) / self._cycle_beats
        breath = 0.55 + 0.45 * math.sin(2 * math.pi * t - math.pi / 2)
        dim = ctx.base_dim * (0.35 + 0.65 * breath) + 0.1 * ctx.glow
        return ctx.hue_a, min(1.0, dim)


class Bounce(Figure):
    """A↔B con caída de oscuridad en cada cruce — el 'rebote'. Mismo par
    repetido las veces que dure la figura."""

    name = "BOUNCE"

    def __init__(self, measures: int, beats_per_measure: int):
        super().__init__(measures, beats_per_measure)
        self._flip_beats = 2
        self._side = 0

    def on_beat(self, beats_done: int) -> None:
        if beats_done % self._flip_beats == 0:
            self._side = 1 - self._side

    def render(self, ctx: FigureContext) -> tuple[float, float]:
        pos = self._pitch_pos(float(self._side), ctx)
        hue = _lerp_hue(ctx.hue_a, ctx.hue_b, pos)
        # dip de oscuridad breve justo tras el cruce (primer 30% del beat
        # del flip), luego rebota arriba
        in_flip_beat = (ctx.beats_done % self._flip_beats) == 0
        if in_flip_beat and ctx.phase < 0.3:
            depth = 1.0 - (ctx.phase / 0.3)
            dim = ctx.base_dim * (1.0 - 0.6 * depth)
        else:
            dim = ctx.base_dim
        return hue, min(1.0, dim + 0.15 * ctx.glow)


class Steps(Figure):
    """Degradado A→B→A en saltos discretos, uno por beat — el degradado
    que salta en vez de fluir."""

    name = "STEPS"

    def __init__(self, measures: int, beats_per_measure: int):
        super().__init__(measures, beats_per_measure)
        self._n_steps = 4
        self._step = 0
        self._direction = 1

    def on_beat(self, beats_done: int) -> None:
        self._step += self._direction
        if self._step >= self._n_steps:
            self._step = self._n_steps
            self._direction = -1
        elif self._step <= 0:
            self._step = 0
            self._direction = 1

    def render(self, ctx: FigureContext) -> tuple[float, float]:
        pos = self._pitch_pos(self._step / self._n_steps, ctx)
        # agresivo (intensidad alta): el degradado se vuelve saltos DUROS entre
        # A y B (contraste), no un fundido suave por tonos intermedios
        if ctx.aggression > 0.45:
            pos = round(pos)
        return _lerp_hue(ctx.hue_a, ctx.hue_b, pos), min(
            1.0, ctx.base_dim + 0.15 * ctx.glow
        )


class HoldPulse(Figure):
    """Color fijo + golpe de brillo 1:1 con el beat."""

    name = "PULSE"

    def render(self, ctx: FigureContext) -> tuple[float, float]:
        attack = math.exp(-5.0 * ctx.phase)
        dim = ctx.base_dim * (0.7 + 0.3 * attack) + 0.15 * ctx.glow
        return ctx.hue_a, min(1.0, dim)


class Ember(Figure):
    """Color puro profundo a BAJO brillo — el 'led rojo puro' oscuro que da
    mucho juego. Respiración lenta. El brillo bajo es el punto dulce perceptual
    (la percepción es logarítmica: los cambios en lo tenue se ven dramáticos)."""

    name = "EMBER"

    def __init__(self, measures: int, beats_per_measure: int):
        super().__init__(measures, beats_per_measure)
        self._cycle = random.choice([3, 4])

    def render(self, ctx: FigureContext) -> tuple[float, float]:
        t = (ctx.beats_done + ctx.phase) / self._cycle
        breath = 0.5 + 0.5 * math.sin(2 * math.pi * t - math.pi / 2)
        dim = 0.12 + 0.20 * breath + 0.1 * ctx.glow  # profundo, nunca a tope
        # en el VALLE de la respiración jala hacia AZUL OSCURO → juega entre su
        # color puro (arriba) y el azul profundo (abajo), no solo sostiene
        hue = _lerp_hue(ctx.hue_a, ctx.shadow_hue, (1.0 - breath) * 0.5)
        return hue, min(1.0, dim)


# Pesos de selección por nivel de energía: (figura, peso_quiet..peso_peak)
FIGURE_WEIGHTS: dict[str, tuple[float, float, float, float, float]] = {
    "SHADOW": (0.5, 1.0, 2.0, 2.5, 2.5),
    "BREATHE": (3.0, 2.0, 1.0, 0.5, 0.3),
    "BOUNCE": (0.2, 0.5, 1.5, 2.5, 3.0),
    "STEPS": (1.0, 1.5, 1.5, 1.5, 1.0),
    "PULSE": (0.3, 0.8, 1.5, 2.0, 2.5),
    "EMBER": (4.0, 3.0, 1.5, 0.3, 0.0),  # oscuros puros (le encantan): mucho en lo quieto/medio
}
LEVEL_INDEX = {"quiet": 0, "low": 1, "medium": 2, "high": 3, "peak": 4}


def pick_figure(
    level: str,
    current_name: str | None,
    measures: int,
    beats_per_measure: int,
    shadow_kwargs: dict,
    ember_weight: float = 1.0,
) -> Figure:
    """Figura nueva, ponderada por nivel, nunca la misma dos veces seguidas.
    `ember_weight` escala en vivo cuántos oscuros puros salen."""
    idx = LEVEL_INDEX.get(level, 2)
    names = [n for n in FIGURE_WEIGHTS if n != current_name]
    weights = [
        FIGURE_WEIGHTS[n][idx] * (ember_weight if n == "EMBER" else 1.0)
        for n in names
    ]
    name = random.choices(names, weights=weights)[0]
    if name == "SHADOW":
        return ShadowPlay(measures, beats_per_measure, **shadow_kwargs)
    if name == "BREATHE":
        return Breathe(measures, beats_per_measure)
    if name == "BOUNCE":
        return Bounce(measures, beats_per_measure)
    if name == "STEPS":
        return Steps(measures, beats_per_measure)
    if name == "EMBER":
        return Ember(measures, beats_per_measure)
    return HoldPulse(measures, beats_per_measure)
