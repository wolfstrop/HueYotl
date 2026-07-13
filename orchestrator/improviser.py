import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Improvisation:
    """Respuestas puntuales a lo que el plan del director no vio."""

    bump: float      # brillo aditivo inmediato (0-1), decae solo
    stab: bool       # golpe de color: cambiar YA a otro principal, breve
    replan: bool     # la predicción está fallando: re-evaluar jugada
    motif: bool      # doble-golpe detectado: "¡brilla con TU color de motivo!"


class Improviser:
    """Reacciona a las sorpresas: picos de energía, golpes fuera de la
    fase predicha (síncopas, fills) y predicciones fallidas del PLL.

    El director es el plan (frases, paletas, predicción); esto es la
    reacción. Todo con cooldown propio — improvisar no es alocarse.
    """

    def __init__(
        self,
        frame_rate: float,
        bump_gain: float = 0.35,
        bump_tau_seconds: float = 0.15,
        spike_ratio: float = 1.6,
        bump_cooldown_seconds: float = 2.0,
        stab_intensity: float = 0.6,
        stab_cooldown_seconds: float = 1.5,
        replan_drop: float = 0.25,
        replan_cooldown_seconds: float = 6.0,
        motif_min_ms: float = 60.0,
        motif_max_ms: float = 600.0,
        motif_cooldown_seconds: float = 2.5,
    ):
        self._bump_gain = bump_gain
        self._bump_decay = math.exp(-1.0 / (frame_rate * bump_tau_seconds))
        self._spike_ratio = spike_ratio
        self._bump_cooldown_frames = int(frame_rate * bump_cooldown_seconds)
        self._stab_intensity = stab_intensity
        self._stab_cooldown_frames = int(frame_rate * stab_cooldown_seconds)
        self._replan_drop = replan_drop
        self._replan_cooldown_frames = int(frame_rate * replan_cooldown_seconds)
        self._conf_alpha = 1.0 / (frame_rate * 3.0)
        self._motif_min_frames = int(frame_rate * motif_min_ms / 1000)
        self._motif_max_frames = int(frame_rate * motif_max_ms / 1000)
        self._motif_cooldown_frames = int(frame_rate * motif_cooldown_seconds)

        self.bump = 0.0
        self._was_spiking = False
        self._bump_cooldown = 0
        self._stab_cooldown = 0
        self._replan_cooldown = 0
        self._conf_ema = 0.0
        self._frame = 0
        self._last_strong = -10_000
        self._motif_cooldown = 0

    def process(
        self,
        energy: float,
        energy_ema: float,
        onset: bool,
        onset_intensity: float,
        beat_phase: float,
        beat_locked: bool,
        confidence: float,
    ) -> Improvisation:
        self._frame += 1
        self.bump *= self._bump_decay
        if self._bump_cooldown > 0:
            self._bump_cooldown -= 1
        if self._stab_cooldown > 0:
            self._stab_cooldown -= 1
        if self._replan_cooldown > 0:
            self._replan_cooldown -= 1
        if self._motif_cooldown > 0:
            self._motif_cooldown -= 1

        # Doble-golpe (los "dos golpes" de It's My Life): dos onsets fuertes
        # muy juntos → motivo — el director responde SIEMPRE con su mismo color
        motif = False
        if onset and onset_intensity >= self._stab_intensity:
            gap = self._frame - self._last_strong
            if (
                self._motif_min_frames <= gap <= self._motif_max_frames
                and self._motif_cooldown == 0
            ):
                motif = True
                self._motif_cooldown = self._motif_cooldown_frames
            self._last_strong = self._frame

        # Pico de energía: solo al CRUZAR el umbral y con cooldown — cada
        # golpe del beat cruza brevemente; sin cooldown el bump sería
        # continuo y dejaría de ser una respuesta puntual
        spiking = energy > energy_ema * self._spike_ratio and energy > 0.3
        if spiking and not self._was_spiking and self._bump_cooldown == 0:
            self.bump = max(self.bump, self._bump_gain)
            self._bump_cooldown = self._bump_cooldown_frames
        self._was_spiking = spiking

        # Golpe fuera de lugar: síncopa/fill lejos de la fase predicha,
        # o golpe muy fuerte cuando ni siquiera hay beat confiable
        stab = False
        if onset and onset_intensity >= self._stab_intensity and self._stab_cooldown == 0:
            offbeat = beat_locked and 0.2 < beat_phase < 0.8
            surprise = not beat_locked and onset_intensity >= 0.75
            if offbeat or surprise:
                stab = True
                self._stab_cooldown = self._stab_cooldown_frames

        # La predicción se está cayendo: confianza muy por debajo de su
        # propia media reciente
        replan = False
        self._conf_ema += (confidence - self._conf_ema) * self._conf_alpha
        if (
            self._replan_cooldown == 0
            and self._conf_ema - confidence > self._replan_drop
        ):
            replan = True
            self._replan_cooldown = self._replan_cooldown_frames

        return Improvisation(bump=self.bump, stab=stab, replan=replan, motif=motif)

    def reset(self) -> None:
        self.bump = 0.0
        self._was_spiking = False
        self._bump_cooldown = 0
        self._stab_cooldown = 0
        self._replan_cooldown = 0
        self._conf_ema = 0.0
        self._frame = 0
        self._last_strong = -10_000
        self._motif_cooldown = 0
