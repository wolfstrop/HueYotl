import math
import random

from rgb_mapper.deck import ColorDeck
from rgb_mapper.grammar import SHADOW_HUE, ColorGrammar
from rgb_mapper.mapper import ColorDecision

from config.tuning import Tuning

from .anomaly import AnomalyLog, check_anomalies
from .channels import BeatChannel, EnergyChannel, HarmonyChannel, MelodyChannel
from .conductor import Conductor
from .dynamics import MODE_BIAS, Dynamics
from .figures import FigureContext, pick_figure
from .gestures import accent_pick, fire_accent, fire_gestures, overlay_gestures, update_flash
from .improviser import Improviser
from .moves import render_move
from .structure import (
    dry_stop_update, palette_policies, trigger_blackout, trigger_micro_black,
    update_breakdown,
)


def _lerp_hue(a: float, b: float, t: float) -> float:
    """Interpola hue por el camino corto del círculo."""
    diff = ((b - a + 0.5) % 1.0) - 0.5
    return (a + diff * t) % 1.0


def _clamp01(x: float) -> float:
    return min(1.0, max(0.0, x))


class MusicDirector:
    """Cerebro del color. Emite frame a frame el hue/brillo EXACTOS.

    GROOVE es un corredor de FIGURAS: cada figura (SHADOW/BREATHE/BOUNCE/
    STEPS/PULSE) corre 2-4 compases con un par de colores del deck y luego
    rota — variedad estructural, cambios discretos solo en beats
    (cuantización garantizada), y en finales tranquilos el entrante del
    deck se promueve.

    Overrides con precedencia: BLACKOUT > crossfade > MOTIVO (doble-golpe:
    siempre el mismo color) > STAB (síncopa) > ACCENT (riff de guitarra) >
    figura. El pitch (centroide) sesga el degradado de las figuras de par:
    agudo empuja hacia B, grave regresa a A.
    """

    def __init__(
        self,
        frame_rate: float = 375.0,
        history_seconds: float = 45.0,
        threshold_recalc_seconds: float = 1.0,
        section_window_seconds: float = 2.0,
        section_delta: float = 0.35,
        section_cooldown_seconds: float = 8.0,
        step_intensity: float = 0.35,
        no_beat_fallback_seconds: float = 4.0,
        latency_compensation_seconds: float = 0.12,
        beats_per_measure: int = 4,
        shadow_dim: float = 0.18,
        shadow_blend: float = 0.6,
        state_min_beats: int = 1,
        state_max_beats: int = 2,
        play_prob_fast: float = 0.6,
        play_prob_slow: float = 0.2,
        bpm_fast: float = 125.0,
        bpm_slow: float = 95.0,
        fade_seconds: float = 1.5,
        accent_intensity: float = 0.55,
        accent_min_measures: int = 4,
        glow_gain: float = 0.6,
        glow_tau_seconds: float = 0.4,
        measure_change_prob: float = 0.7,
        figure_min_measures: int = 2,
        figure_max_measures: int = 4,
        pitch_follow_gain: float = 0.6,
        promote_prob: float = 0.6,
        move_min_seconds: float = 8.0,
        flow_speed: float = 0.0004,
        flow_ease: float = 0.03,
        flow_kick: float = 0.003,
        dimming_floor: float = 0.2,
        blackout_seconds: float = 0.35,
        blackout_floor: float = 0.03,
        flash_enabled: bool = True,
        punch_intensity: float = 0.6,
        punch_beats: float = 0.25,
        micro_black_seconds: float = 0.09,
        micro_black_gap_seconds: float = 2.0,
        breakdown_enabled: bool = True,
        breakdown_ratio: float = 0.5,
        breakdown_seconds: float = 0.35,
        breakdown_voice_min: float = 0.15,
        breakdown_floor: float = 0.15,
        mode: str = "auto",
        groove_tau_seconds: float = 1.0,
        intensity_tau_seconds: float = 0.5,
        surge_cooldown_seconds: float = 3.0,
        tuning: Tuning | None = None,
        improviser: Improviser | None = None,
    ):
        self.tuning = tuning or Tuning()
        self._frame_rate = frame_rate
        # rango adaptativo, nivel, envolvente y detección de sección → EnergyChannel
        self._section_cooldown_frames = int(frame_rate * section_cooldown_seconds)
        self._step_intensity = step_intensity
        self._no_beat_frames = int(frame_rate * no_beat_fallback_seconds)
        self._lookahead = latency_compensation_seconds * frame_rate
        self._beats_per_measure = max(1, beats_per_measure)
        self._shadow_dim = shadow_dim
        self._shadow_blend = shadow_blend
        self._shadow_kwargs = {
            "play_prob": play_prob_fast,  # se recalcula por tempo al crear
            "min_beats": max(1, state_min_beats),
            "max_beats": max(1, state_max_beats),
            "swap_prob": measure_change_prob,
        }
        self._play_prob_fast = play_prob_fast
        self._play_prob_slow = play_prob_slow
        self._bpm_fast = bpm_fast
        self._bpm_slow = bpm_slow
        self._fade_frames = max(1, int(frame_rate * fade_seconds))
        self._accent_intensity = accent_intensity
        self._accent_min_measures = max(1, accent_min_measures)
        self._glow_gain = glow_gain
        self._glow_alpha = 1.0 / (frame_rate * glow_tau_seconds)
        self._figure_min_measures = max(1, figure_min_measures)
        self._figure_max_measures = max(self._figure_min_measures, figure_max_measures)
        self._pitch_gain = pitch_follow_gain
        self._promote_prob = promote_prob
        self._move_min_frames = int(frame_rate * move_min_seconds)
        self._flow_speed = flow_speed
        self._flow_ease = flow_ease
        self._flow_kick = flow_kick
        self._blackout_frames = max(1, int(frame_rate * blackout_seconds))
        self._blackout_floor = blackout_floor
        self._flash_enabled = flash_enabled
        self._punch_intensity = punch_intensity
        self._punch_beats = punch_beats
        self._micro_black_frames = max(1, int(frame_rate * micro_black_seconds))
        self._micro_black_gap_frames = int(frame_rate * micro_black_gap_seconds)
        self._breakdown_enabled = breakdown_enabled
        self._breakdown_ratio = breakdown_ratio
        self._breakdown_frames = max(1, int(frame_rate * breakdown_seconds))
        self._breakdown_voice_min = breakdown_voice_min
        self._breakdown_floor = breakdown_floor
        self._surge_cooldown_frames = int(frame_rate * surge_cooldown_seconds)

        self.beat_channel = BeatChannel(frame_rate)
        self.tempo = self.beat_channel.tempo  # alias: los 20+ usos siguen igual
        self.harmony_channel = HarmonyChannel(frame_rate)
        self.grammar = ColorGrammar()
        self.deck = ColorDeck(self.grammar)
        self.dyn = Dynamics(
            frame_rate,
            groove_tau_seconds=groove_tau_seconds,
            intensity_tau_seconds=intensity_tau_seconds,
            mode=mode,
        )
        self.improviser = improviser or Improviser(frame_rate)
        self.melody_channel = MelodyChannel(frame_rate)
        self.energy_channel = EnergyChannel(
            frame_rate,
            history_seconds=history_seconds,
            recalc_seconds=threshold_recalc_seconds,
            section_window_seconds=section_window_seconds,
            section_delta=section_delta,
            dimming_floor=dimming_floor,
        )
        self.conductor = Conductor(frame_rate)
        self.anomalies = AnomalyLog(frame_rate)
        self._reset_state()

    def _reset_state(self) -> None:
        self.energy_channel.reset()
        self._frame = 0
        self.beat_channel.reset()
        self.harmony_channel.reset()
        self._last_onset_frame = 0   # espejo del BeatChannel
        self._section_cooldown = 0
        self._flash_cooldown = 0
        self._energy_ema = 0.0        # espejo del EnergyChannel (breakdown/improviser)
        self._energy_envelope = 0.2   # espejo de la envolvente de brillo (render)
        self._wobble_phase = 0.0
        self._wobble_speed = 2 * math.pi / (self._frame_rate * 10.0)
        self.glow = 0.0
        self.centroid = 0.5
        # Melodía: la percibe MelodyChannel. Estos son ESPEJOS del último reporte
        # (los consumen el render y el debug). El contorno relativo sigue la
        # FORMA de la melodía sin pegarse a un extremo, sea grave o aguda.
        self.melody_channel.reset()
        self.melody = 0.5
        self._melody_slow = 0.5  # versión lenta (contorno) para el BRILLO — no vibra
        self._melody_bright_c = 0.5  # contorno con AGC (swing garantizado)
        self._melody_mid = 0.5   # media (~0.35s) para el COLOR — sigue el contorno, no cada nota
        self.melody_conf = 0.0   # confianza de melodía (tonalness) — para el conductor
        self.melody_act = 0.0    # actividad del contorno (0 = nota sostenida/estática)
        self._swell = 0.0        # build de brillo en nota sostenida a todo pulmón
        self._temperature = 0.5  # timbre lento (frío↔cálido) → la CLAVE de color del mood
        self.valence = 0.5       # modo mayor/menor (alegre↔triste) del chroma
        # ARBITRAJE: lo decide el Conductor (focus 0=melodía, 1=beat). Estos son
        # ESPEJOS del último Mix. El presupuesto de actividad (_effect_heat) es del
        # director: sube al disparar efectos, suprime nuevos si hay demasiados.
        self.conductor.reset()
        self.focus = 0.5
        self._lead = 0.5         # líder COMPROMETIDO (histéresis) — no titubea en el borde
        self._fallback = False   # nadie confiable → calma (no gestos punchy)
        self._effect_heat = 0.0

        self.move = "FLOW"
        self._move_started = 0
        self.color = self.deck.principals[0]
        self._partner = self.deck.incoming
        self._triad_color = self.deck.principals[1]
        self._flow_partner = self.deck.incoming
        # FLOW con inercia (Fase 3 recuperada): hue integrado + velocidad
        self._flow_hue = self.grammar.hue(self.color)
        self._flow_vel = 0.0
        self._flow_arrivals = 0  # ping-pong entre 2 colores antes de saltar a uno nuevo
        self._riff_side = 0      # lado del color-por-NOTA en modo RIFF

        # Corredor de figuras (conteo de beats RELATIVO: el índice absoluto
        # del PLL salta cuando el periodo se re-estima)
        self.state = "-"
        self._figure = None
        self._figure_start_beat = 0
        self._figure_start_frame = 0
        self._last_beat_idx = -1
        self._last_beat_frame = 0
        self._beat_count = 0

        # Bus de acentos unificado: UN color de golpe a la vez, con prioridad
        # (motif > punch > stab/guitarra). Reemplaza los 4 mecanismos sueltos
        # que se pisaban entre sí.
        self._accent_hit_color: str | None = None
        self._accent_last_color: str | None = None
        self._accent_hit_until = 0
        self._accent_hit_prio = 0
        self._accent_hit_boost = 0.0
        self._accent_block_until = 0   # cooldown del riff de guitarra
        self._punch_cooldown = 0       # cooldown del golpe de tambor
        self._motif_color: str | None = None  # color recordado del motivo
        # Acento rítmico: un golpe de color que se REPITE en patrón de 4/8 tiempos
        self._beat_accent_color: str | None = None
        self._beat_accent_left = 0

        # Crossfade genérico
        self._fade_left = 0
        self._fade_from = 0.0

        # Blackout
        self._blackout_until = 0
        self._blackout_reseed: str | None = None

        # Capa 3: micro-apagón de puntuación al cambiar de base
        self._micro_black_until = 0
        self._micro_black_cooldown = 0

        # Capa 4: breakdown / respiro (voz sola, música se calla)
        self.breakdown = False
        self._breakdown_count = 0

        # Flash con envelope propio (decae al ritmo, hacia el siguiente beat)
        self._flash_env = 0.0
        self._flash_step = 0.0

        # Fatiga de color: si un color se sostiene demasiado, refrescar
        # (salto al complemento) — el ojo lo "dessatura" y se siente muerto
        self._fatigue_frames = 0
        self._fatigue_color = self.color
        self._last_promote_frame = 0  # rotación de fondo del pool de colores
        self._last_veda_frame = 0     # veda de colores (descanso forzado)

        # Métele/cálmate (cambio brusco de intensidad)
        self._surge_cooldown = 0

        # Transición: referencia lenta del centroide (para detectar saltos de
        # registro = cambio de frase) y color pendiente de aplicar AL BEAT.
        self._centroid_ref = 0.5
        self._pending_color: str | None = None

        # Ola R: ritmo en eje oscuro + ráfaga color-por-beat
        self._dark_pulse_until = 0
        self._burst_idx = 0
        self._burst_color: str | None = None

        # Ola T: cola del acento (regreso difuminado) + alto en seco
        self._accent_release_left = 0
        self._accent_release_total = 1
        self._accent_release_hue = 0.0
        self._dry_stop = False
        self._dry_count = 0

        # Ola S: reentrada escalonada tras un dip
        self._was_dip = False

        # Auto-bitácora: contadores de invariantes sospechosos
        self._anom_prev_color = self.color
        self._anom_color_since = 0
        self._anom_partner_eq = 0
        self._pending_set_frame = 0
        self._fallback_start = -1
        self._focus_crossings: list[int] = []
        self._lead_side = 0
        self._low_dim_frames = 0
        self._dry_bad_frames = 0

        self.dyn.reset()

        self._last_hue = self.grammar.hue(self.color)

    # ------------------------------------------------------------ carácter

    def _onset_density(self) -> float:
        return self.beat_channel.onset_density(self._frame)

    def _brusque(self) -> bool:
        return self._onset_density() >= 1.5 or self.energy_channel.level_of(
            self._energy_ema
        ) in ("high", "peak")

    def _character(self) -> str:
        # Los dos ejes deciden el carácter: ritmo marcado → GROOVE (figuras);
        # intenso pero sin ritmo claro → MONO (drama por brillo: clásica, muro
        # de rock); si no, FLOW (melódico, deriva orgánica).
        has_recent_beat = self._frame - self._last_onset_frame <= self._no_beat_frames
        if has_recent_beat and self.dyn.groove >= 0.45:
            return "GROOVE"
        if has_recent_beat and self.dyn.intensity >= 0.55:
            return "MONO"
        return "FLOW"

    def _eff_level(self) -> str:
        """Nivel efectivo para elegir figuras: derivado de la INTENSIDAD
        (suavizada y sesgada por modo), no de la energía cruda por-frame."""
        lvls = ("quiet", "low", "medium", "high", "peak")
        return lvls[min(4, int(self.dyn.intensity * 5))]

    def _select_move(self, new_colors: bool) -> bool:
        move = self._character()
        if move == self.move and not new_colors:
            self._move_started = self._frame
            if move == "FLOW":
                # La audición concluyó: el entrante se ganó su lugar
                self.color = self._flow_partner
                if self._flow_partner == self.deck.incoming:
                    self.deck.promote()
                self._flow_partner = self._flow_target()
                return True
            return False

        if move == "FLOW":
            self._flow_partner = self._flow_target()
            self._flow_hue = self._last_hue  # continúa desde donde iba
            self._flow_vel = 0.0
        elif move == "MONO":
            self.color = self.grammar.nearest_mono(self.color)
        elif move == "GROOVE" and new_colors:
            self.color = self.deck.pick(self.color, brusque=True)

        self.move = move
        self._move_started = self._frame
        self._figure = None
        self._last_beat_idx = -1
        self._pending_color = None  # una transición pendiente de otro move ya es rancia
        return True

    def _start_fade(self) -> None:
        # FLOW = fundido lento; GROOVE = fundido corto EN BEATS (~¾ de beat:
        # a canción rápida transición rápida, a lenta más untada — "que
        # encajen", no segundos fijos); MONO = seco.
        if self.move == "MONO":
            self._fade_left = 0
            return
        self._fade_from = self._last_hue
        if self.move == "FLOW":
            self._fade_left = self._fade_frames
        else:
            # ¾ de beat CON TOPE de 0.35s: escala con el tempo en rápidas pero
            # no se unta en lentas (sesión real a ~100bpm: 0.45-0.51s se sintió
            # raro — el corte fresco vive por debajo de ~0.35s)
            self._fade_left = max(
                int(0.12 * self._frame_rate),
                min(int(0.35 * self._frame_rate), int(0.75 * self.tempo.period)),
            )


    @staticmethod
    def _jit(frames: int) -> int:
        """Jitter ±~25% en cooldowns: sembrados juntos expiraban juntos y los
        efectos caían en RÁFAGA tras el silencio — desincronizarlos la reparte."""
        return max(1, int(frames * random.uniform(0.75, 1.3)))



    def _mood_contrast(self, color: str) -> str:
        """Contraste PARA CORTES FRECUENTES (fatiga, staccato): el color más
        lejano en hue de entre los que el MOOD tolera (deck + candidatos con
        peso decente). El complemento ciego (cut_from) inyectaba ámbar/rojo
        como base en moods fríos cada ~10s — queda solo para drama raro
        (blackout de sección, surge)."""
        pool = [c for c in set(self.deck.principals + [self.deck.incoming]) if c != color]
        if not pool:
            return self.grammar.cut_from(color)
        far = sorted(pool, key=lambda c: -self.grammar._dist(color, c))[:2]
        return self.deck.choose(far)

    def _flow_target(self) -> str:
        """Destino de la deriva FLOW: el entrante del deck, salvo que SEA el
        color actual (deriva hacia sí mismo = color pegado) → socio fundible."""
        incoming = self.deck.incoming
        return incoming if incoming != self.color else self._pick_partner()

    def _pick_partner(self) -> str:
        """Socio de figura: fundible con el color base, del deck si se puede,
        y NUNCA el mismo color — un par A→A no tiene a dónde degradar y se ve
        como color pegado vibrando (log: EMBER red→red con textura)."""
        partners = [
            p
            for p in self.grammar.fade_partners(self.color)
            if (p in self.deck.principals or p == self.deck.incoming)
            and p != self.color
        ]
        if not partners:
            partners = [
                p for p in self.grammar.fade_partners(self.color) if p != self.color
            ]
        if not partners:
            partners = [c for c in self.deck.principals if c != self.color]
        # ponderado por mood+calor: el socio también respeta la clave de color
        return self.deck.choose(partners) if partners else self.color





    # ------------------------------------------------------------- proceso

    def process(
        self,
        low: float,
        mid: float,
        high: float,
        energy: float,
        onset: bool,
        onset_intensity: float,
        lead_onset: bool = False,
        lead_intensity: float = 0.0,
        centroid: float = 0.5,
        valence: float = 0.5,
        tonalness: float = 0.0,
    ) -> ColorDecision:
        self.centroid = centroid
        self.valence = valence
        # Canal de melodía: percibe el contorno (3 escalas) + la confianza.
        # Espejeamos a los atributos que ya consumen el render y el debug.
        rep = self.melody_channel.update(centroid, tonalness)
        self.melody = rep.contour
        self._melody_mid = rep.contour_mid
        self._melody_slow = rep.contour_slow
        self._melody_bright_c = rep.contour_bright  # con AGC: swing garantizado
        self.melody_conf = rep.confidence
        self.melody_act = rep.activity
        self._frame += 1
        # Calibración en vivo: refresca lo derivado de segundos y el modo
        tn = self.tuning
        self._lookahead = self._frame_rate * tn.latency_seconds
        self._fade_frames = max(1, int(self._frame_rate * tn.fade_seconds))
        self.dyn.mode = tn.vibe if tn.vibe in MODE_BIAS else "auto"
        # Canal de energía: nivel, envolvente de brillo y cambio de sección (crudo).
        rep_e = self.energy_channel.update(energy, tn.brightness_ceiling)
        self._energy_ema = rep_e.ema
        self._energy_envelope = rep_e.envelope
        self.glow += (mid - self.glow) * self._glow_alpha
        update_breakdown(self, energy, mid)
        # Fatiga: cuántos frames lleva el MISMO color base (para refrescarlo)
        if self.color == self._fatigue_color:
            self._fatigue_frames += 1
        else:
            self._fatigue_color = self.color
            self._fatigue_frames = 0
        if self._section_cooldown > 0:
            self._section_cooldown -= 1
        if self._flash_cooldown > 0:
            self._flash_cooldown -= 1

        strong_onset = onset and onset_intensity >= self._step_intensity
        self.beat_channel.update(self._frame, strong_onset)
        self._last_onset_frame = self.beat_channel.last_onset_frame

        level = rep_e.level
        # Intensidad = energía absoluta (loudness, ya 0-1) + un toque de posición
        # relativa (drama dentro de la canción). El EMA la mantiene estable → el
        # trend (métele/cálmate) no tiembla por beat.
        intensity_raw = 0.7 * energy + 0.3 * rep_e.norm_energy
        self.dyn.update(
            self.tempo.confidence,
            self.tempo.regularity,
            self._onset_density(),
            intensity_raw,
        )
        if self._surge_cooldown > 0:
            self._surge_cooldown -= 1

        # MOOD → la CLAVE de color que siembra el deck. Temperatura = timbre
        # lento (~6s); profundidad y amplitud = intensidad del momento (movida
        # = clave ancha y brillante; tranquila = cerrada y profunda).
        temp_eff = self.harmony_channel.update(
            self.centroid, self.valence, self.tuning.valence_strength
        )
        self._temperature = self.harmony_channel.temperature  # espejo
        # profundidad: intensidad + contorno de la melodía → grave jala a tonos
        # PROFUNDOS (azul/morado/rojo oscuro), agudo a brillantes (espejo del plateau)
        depth = 0.5 * self.dyn.intensity + 0.5 * self._melody_slow
        # amplitud: el drop (surge de ritmo) ENSANCHA la clave → más colores de golpe
        surge = self.dyn.trend > self.tuning.surge_threshold
        breadth = _clamp01(self.dyn.intensity + (0.4 if surge else 0.0))
        self.deck.mood_weights = self.grammar.mood_weights(
            temp_eff, depth, breadth, self.tuning.mood_strength
        )
        palette_policies(self)
        building = (
            self._lead < 0.35 and self.melody_act > 0.35 and self.melody_conf > 0.35
        )

        # ARBITRAJE (Conductor): decide quién lidera el gesto (melodía↔beat) por
        # sus CONFIANZAS reales — tonalness vs tempo lock — con histéresis, y
        # marca FALLBACK si nadie está claro. Espejeamos focus/_lead/_fallback.
        # La confianza EFECTIVA exige MOVIMIENTO: una nota sostenida es muy tonal
        # pero estática — no tiene nada que traducir, no debe robar el mando
        # (la banda sigue atrás: que el beat conserve el gesto).
        mid_prom = mid / (low + mid + high + 1e-6)
        mel_conf_eff = self.melody_conf * (0.35 + 0.65 * self.melody_act)
        mix = self.conductor.update(
            melody_conf=mel_conf_eff,
            beat_conf=self.tempo.confidence,
            groove=self.dyn.groove,
            mid_prom=mid_prom,
            lead_bias=tn.melody_lead_bias,
        )
        # NOTA SOSTENIDA A TODO PULMÓN: tonal + estática + con presencia → gesto
        # DELIBERADO de LD: el brillo CRECE sostenido mientras dura la nota
        # (build), y se suelta rápido al soltarla. Ni freeze ni acentos random.
        sustained_note = (
            self.melody_conf > 0.45 and self.melody_act < 0.25 and mid_prom > 0.3
        )
        if sustained_note:
            self._swell += (1.0 - self._swell) * (1.0 / (self._frame_rate * 2.5))
        else:
            self._swell += (0.0 - self._swell) * (1.0 / (self._frame_rate * 0.4))

        dry_stop_update(self, energy, mid)
        self.focus = mix.focus
        self._lead = mix.lead
        self._fallback = mix.fallback
        # presupuesto de actividad: enfría cada frame (media vida ~0.7s)
        self._effect_heat *= 0.9985

        if self._frame < self._blackout_until:
            return ColorDecision(
                hue=self._last_hue,
                dimming=self._blackout_floor,
                flash=0.0,
                level=level,
                stepped=False,
                section_change=False,
                # oscuridad TOTAL en el blackout de sección (raro, dramático); el
                # destello de arranque del firmware sale poquísimo y es apagable
                blackout=self.tuning.blackout_total,
            )
        if self._frame == self._blackout_until and self._blackout_reseed:
            self.deck.reseed(self._blackout_reseed)
            self.color = self._blackout_reseed
            self._blackout_reseed = None
            self._motif_color = None  # sección nueva, motivo nuevo
            self._figure = None
            self._effect_heat = max(self._effect_heat, 1.2)  # reentrada escalonada

        beat_locked = self.move == "GROOVE"
        phase = self.tempo.phase(self._frame + self._lookahead)  # predictivo, para render
        phase_now = self.tempo.phase(self._frame)  # REAL, para clasificar on/off-beat
        improv = self.improviser.process(
            energy, self._energy_ema, strong_onset, onset_intensity,
            phase_now, beat_locked, self.tempo.confidence,
        )
        fire_gestures(self, improv, strong_onset, onset_intensity, lead_onset, lead_intensity)

        # el canal detecta el cambio crudo; el director aplica el cooldown (política)
        section_change = self._section_cooldown == 0 and rep_e.section_shift
        stepped = False

        # CAMBIO SONORO: el centroide melódico saltó de registro respecto a su
        # referencia lenta → fin/cambio de frase, aunque la energía no cambie
        # (lalala→tururun). Dispara transición aunque no haya crescendo de energía.
        self._centroid_ref += (self.centroid - self._centroid_ref) * (
            1.0 / (self._frame_rate * 0.6)
        )
        sonic_change = abs(self.centroid - self._centroid_ref) > (
            0.30 - 0.16 * self.tuning.transition_sensitivity
        )

        # El breakdown se dispara con la MISMA caída de energía que una sección;
        # si hay respiro en curso, el hush manda — no metemos blackout/snap encima.
        if section_change and not self.breakdown:
            self._section_cooldown = self._section_cooldown_frames
            self._motif_color = None
            recent_beat = (
                self._frame - self._last_onset_frame
                <= self._beats_per_measure * self.tempo.period
            )
            if level in ("high", "peak") and recent_beat:
                trigger_blackout(self)
            elif self._select_move(new_colors=True):
                if level in ("high", "peak"):
                    self._fade_left = 0  # sección con energía: corte seco, no fundido
                    trigger_micro_black(self)
                else:
                    self._start_fade()
            stepped = True
        elif (
            self.tuning.dynamics_strength > 0.15
            and (self.dyn.trend > self.tuning.surge_threshold or sonic_change)
            and self._surge_cooldown == 0
        ):
            # TRANSICIÓN cuantizada al beat. El color depende del PORQUÉ:
            # surge de energía real (drop/coro) → complemento (drama);
            # solo cambio de frase → color del deck EN el mood (no desentona —
            # el complemento ciego al final de una frase rompía la inmersión).
            if self.dyn.trend > self.tuning.surge_threshold:
                nxt = self.grammar.cut_from(self.color)
            else:
                nxt = self.deck.pick(self.color, brusque=True)
            if self.move == "GROOVE":
                self._pending_color = nxt
                self._pending_set_frame = self._frame
            else:
                self.color = nxt
                self._start_fade()
            self.conductor.bias_beat(0.3)
            self._surge_cooldown = self._jit(self._surge_cooldown_frames)
            stepped = True
        elif (
            self.tuning.dynamics_strength > 0.15
            and self.dyn.trend < -self.tuning.surge_threshold
            and self._surge_cooldown == 0
        ):
            # CÁLMATE: caída brusca → suelta a figura calmada de una
            self._figure = None
            self._surge_cooldown = self._jit(self._surge_cooldown_frames)
            stepped = True
        elif improv.replan and self._frame - self._move_started > self._frame_rate * 3:
            if self._select_move(new_colors=False):
                self._start_fade()
                stepped = True
        elif self._frame - self._move_started >= self._move_min_frames:
            if self._select_move(new_colors=False):
                self._start_fade()
                stepped = True
        elif self._fatigue_frames > int(
            self._frame_rate * self.tuning.fatigue_seconds
        ) and (
            not building
            or self._fatigue_frames > 2 * int(self._frame_rate * self.tuning.fatigue_seconds)
        ):
            # el color lleva demasiado y el ojo lo "dessatura" (se siente muerto).
            # Aplica en TODOS los modos — MONO no tenía NINGUNA salida de color
            # propia y se clavaba hasta 12s en el muro de rock. Con MOMENTUM: no
            # interrumpe un build melódico salvo que ya lleve el doble.
            if self.move == "GROOVE":
                # refresco al contraste DEL MOOD con OFF→ON: vibra sin desentonar
                self.color = self._mood_contrast(self.color)
                trigger_micro_black(self)
                self._figure = None
            elif self.move == "MONO":
                # muro sostenido: renueva a otro MONO del deck, corte seco (drama)
                nxt = self.grammar.nearest_mono(self.deck.pick(self.color, brusque=False))
                if nxt == self.color:  # el mono más cercano era el mismo → contraste
                    nxt = self.grammar.nearest_mono(self._mood_contrast(self.color))
                self.color = nxt
            else:  # FLOW: empuja la deriva hacia un socio nuevo (suave)
                self._flow_partner = self.deck.pick(self.color, brusque=False)
            self._fatigue_frames = 0
            stepped = True

        hue, dimming, changed = render_move(self, level, phase)
        stepped = stepped or changed

        hue, dimming = overlay_gestures(self, hue, dimming, improv)

        if self._fade_left > 0:
            t = 1.0 - self._fade_left / self._fade_frames
            eased = 0.5 - 0.5 * math.cos(math.pi * t)
            hue = _lerp_hue(self._fade_from, hue, eased)
            self._fade_left -= 1

        # Puntuación: BAJÓN de brillo profundo (NO apaga el foco → el firmware
        # ya no destella blanco al re-encender). El color nuevo aparece en lo
        # oscuro y sube — corte casi seco, sin flash blanco de arranque.
        in_dip = self._frame < self._micro_black_until
        if in_dip:
            dimming = self._blackout_floor
        elif self._dry_stop:  # alto en seco: corta YA, sostiene el color a oscuras
            dimming = 0.05
        elif self.breakdown:  # breakdown: hush mientras dura el respiro
            dimming = min(dimming, self._breakdown_floor)
        # REENTRADA ESCALONADA: al salir de un dip, sube el presupuesto de
        # actividad → los efectos acumulados no caen todos en chinga encima.
        if self._was_dip and not in_dip:
            self._effect_heat = max(self._effect_heat, 1.2)
        self._was_dip = in_dip

        flash = update_flash(self, onset, onset_intensity, level, in_dip)

        # Textura de gamma: micro-saltos de brillo (mismo color) — sobre figuras
        # sostenidas Y sobre FLOW (el "juego" en los fades de guitarra que pidió).
        # Off en oscuro/respiro. Pasos gruesos (mapper) para verse a 30Hz.
        texture = 0.0
        sustained = (
            self.move == "FLOW"
            or (self.move == "GROOVE" and self.state in ("PULSE", "BREATHE", "SHADOW", "EMBER"))
        )
        if (
            sustained
            and level in ("low", "medium", "high")
            and not in_dip
            and not self.breakdown
            and not self._dry_stop
        ):
            texture = self.tuning.gamma_texture

        check_anomalies(self, hue, dimming, in_dip, energy, mid, stepped)
        self._last_hue = hue
        # anti-repetición: alimenta el 'calor' con el color realmente MOSTRADO
        # (incluye el morado de tránsito de los fades) → se penaliza en la selección
        self.deck.tick(self.grammar.nearest_anchor(hue))
        return ColorDecision(
            hue=hue,
            dimming=dimming,
            flash=flash,
            level=level,
            stepped=stepped,
            section_change=section_change,
            texture=texture,
        )

    # -------------------------------------------------------- render moves



    def _next_figure(self) -> bool:
        """Figura nueva: colores del deck, duración 2-4 compases. En finales
        tranquilos el entrante se promueve (la paleta rota)."""
        changed = False
        if self._figure is not None:  # no es la primera
            brusque = self._brusque()
            # a más INTENSIDAD, repite menos el color → más cambios (carne al asador);
            # a baja intensidad repite más → juega entre 2-3, no se aloca.
            # dynamics_strength escala cuánto empuja la intensidad (0 = fijo).
            keep = self.tuning.keep_color_prob * (
                1.0 - 0.7 * self.dyn.intensity * self.tuning.dynamics_strength
            )
            if random.random() < keep:
                pass  # REPITE el mismo color
            elif not brusque and random.random() < self._promote_prob:
                self.color = self.deck.promote()
                self._start_fade()
            elif brusque and random.random() < self.tuning.cut_prob:
                # staccato (batería/guitarra): corte de golpe al contraste DEL
                # MOOD con OFF→ON (probado: la única forma de corte seco aquí)
                self.color = self._mood_contrast(self.color)
                self._fade_left = 0
                trigger_micro_black(self)
            else:
                self.color = self.deck.pick(self.color, brusque=brusque)
                if not brusque:
                    self._start_fade()  # cambio tranquilo → desvanece (no seco)
            changed = True

        self._partner = self._pick_partner()

        # Tercer color del triángulo: funde con AMBOS (el 'impar que combina'),
        # elegido POR MOOD — el acento uniforme metía ámbar en moods fríos
        # (medido: 21% de ámbar en frío-oscuro venía de la tríada de acentos).
        candidates = self.grammar.accent_candidates(self.color, self._partner)
        if not candidates:
            candidates = [
                c for c in self.deck.principals if c not in (self.color, self._partner)
            ]
        # el acento ROTA: no repetir el de la figura anterior (mood+contraste
        # solos re-elegían purple una y otra vez en moods fríos — medido 84%)
        if len(candidates) > 1 and self._triad_color in candidates:
            candidates = [c for c in candidates if c != self._triad_color]
        self._triad_color = (
            self.deck.choose(candidates, contrast_from=self.color)
            if candidates
            else self._partner
        )

        bpm = self.tempo.bpm
        speed_t = _clamp01((bpm - self._bpm_slow) / max(1.0, self._bpm_fast - self._bpm_slow))
        self._shadow_kwargs["play_prob"] = self._play_prob_slow + speed_t * (
            self._play_prob_fast - self._play_prob_slow
        )
        # a intensidad alta las figuras viven MENOS → los colores rotan al ritmo
        # de la energía ("más color"), sin subir el brillo
        if self.dyn.intensity > 0.7:
            measures = self._figure_min_measures
        else:
            measures = random.randint(self._figure_min_measures, self._figure_max_measures)
        current = self._figure.name if self._figure else None
        # GATE (apagado rítmico) solo con tempo CONFIABLE — fuera de fase se ve
        # horrible. Ciclo por tempo: rápido → cada 2 beats (≤3 transiciones/s,
        # el tope del SafetyLimiter anti-estrobo).
        gate_ok = self.tempo.confidence >= 0.6 and self.tempo.precision >= 0.6
        gate_cycle = 1 if self.tempo.period >= self._frame_rate * 0.66 else 2
        # con el ritmo GRITANDO (condiciones de ráfaga), EMBER ni se considera
        # — regla general del censo: figura íntima + ritmo a tope no combinan
        rhythm_screams = (
            self.dyn.groove > self.tuning.burst_drive and self._lead > 0.65
        )
        self._figure = pick_figure(
            self._eff_level(), current, measures, self._beats_per_measure,
            self._shadow_kwargs,
            ember_weight=0.0 if rhythm_screams else self.tuning.ember_weight,
            gate_cycle=gate_cycle if gate_ok else None,
        )
        # EMBER = oscuro puro: el color base se ancla a un MONO (rojo/azul/
        # morado/verde puro), que es lo que da el juego en lo tenue.
        if self._figure.name == "DUET":
            # pareja de CONTRASTE (cut-partners): rojo↔azul y compañía —
            # alternados en seco por la figura, nunca fundidos (el fundido
            # rojo-azul pasa por todo el morado, por eso estaba prohibido;
            # la alternancia discreta lo vuelve legal y precioso)
            contrast = [
                c for c in self.grammar.cut_partners(self.color) if c != self.color
            ]
            if contrast:
                self._partner = self.deck.choose(contrast)
        if self._figure.name == "EMBER":
            mono = self.grammar.nearest_mono(self.color)
            if mono != self.color:
                self.color = mono
                self._start_fade()  # el ancla no debe dar salto seco de hue
            # el ancla MONO cambió el color DESPUÉS de elegir socio → re-elegir
            # (la colisión A→A venía de aquí: partner elegido para el color viejo)
            self._partner = self._pick_partner()
        self._figure_start_beat = self._beat_count
        self._figure_start_frame = self._frame
        return changed

    # ----------------------------------------------------------- internos

    def reset(self) -> None:
        self.improviser.reset()
        self.deck.reseed()
        self._reset_state()
