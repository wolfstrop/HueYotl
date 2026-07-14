import asyncio
import colorsys
import logging
import sys
import time

import os

from config import Settings
from config.tuning import Tuning, TuningWatcher
from wiz_controller import WizController
from audio_capture import AudioCapture
from audio_analyzer import RollingSTFT, BandAnalyzer
from audio_analyzer.beat import OnsetDetector
from audio_analyzer.chroma import RollingChroma
from rgb_mapper import RGBMapper, ColorDecision

from .director import MusicDirector
from .improviser import Improviser
from .modes import AmbientMode
from .safety import SafetyLimiter

logger = logging.getLogger(__name__)


class Pipeline:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.wiz = WizController(
            ip=settings.wiz.ip,
            port=settings.wiz.port,
            update_hz=settings.wiz.update_hz,
        )
        self.audio = AudioCapture(
            sample_rate=settings.audio.sample_rate,
            chunk_size=settings.audio.chunk_size,
            channels=settings.audio.channels,
            device=settings.audio.device,
        )
        self.stft = RollingSTFT(
            window=1024,
            hop=settings.audio.chunk_size,
            sample_rate=settings.audio.sample_rate,
        )
        self.chroma = RollingChroma(
            sample_rate=settings.audio.sample_rate,
            frame_rate=settings.audio.sample_rate / settings.audio.chunk_size,
        )
        self.bands = BandAnalyzer(
            sample_rate=settings.audio.sample_rate,
            chunk_size=settings.audio.chunk_size,
            low=settings.bands.low,
            mid=settings.bands.mid,
            high=settings.bands.high,
            auto_calibrate=settings.calibration.enabled,
            calibration_window=settings.calibration.window,
            calibration_percentile=settings.calibration.percentile,
        )
        frame_rate = settings.audio.sample_rate / settings.audio.chunk_size
        self.onset = OnsetDetector(
            band_centers=self.stft.band_centers,
            frame_rate=frame_rate,
            flux_threshold=settings.onset.flux_threshold,
            cooldown_ms=settings.onset.cooldown_ms,
            history_size=settings.onset.history_size,
            energy_gate=settings.onset.energy_gate,
            min_intensity=settings.onset.min_intensity,
            whiten_decay_seconds=settings.onset.whiten_decay_seconds,
        )
        # Detector paralelo pesado a medios: rasgueos/riffs de guitarra
        self.lead_onset = OnsetDetector(
            band_centers=self.stft.band_centers,
            frame_rate=frame_rate,
            flux_threshold=settings.onset.flux_threshold,
            cooldown_ms=settings.onset.cooldown_ms,
            history_size=settings.onset.history_size,
            energy_gate=settings.onset.energy_gate,
            min_intensity=settings.onset.min_intensity,
            flux_band="mid",
            whiten_decay_seconds=settings.onset.whiten_decay_seconds,
        )
        imp = settings.improviser
        improviser = Improviser(
            frame_rate=frame_rate,
            bump_gain=imp.bump_gain,
            bump_tau_seconds=imp.bump_tau_seconds,
            spike_ratio=imp.spike_ratio,
            bump_cooldown_seconds=imp.bump_cooldown_seconds,
            stab_intensity=imp.stab_intensity,
            stab_cooldown_seconds=imp.stab_cooldown_seconds,
            replan_drop=imp.replan_drop,
            replan_cooldown_seconds=imp.replan_cooldown_seconds,
            motif_min_ms=imp.motif_min_ms,
            motif_max_ms=imp.motif_max_ms,
            motif_cooldown_seconds=imp.motif_cooldown_seconds,
        )
        d = settings.director
        # Calibración en vivo: Tuning sembrado desde settings, recargado del .toml
        self.tuning = Tuning(
            vibe=d.mode,
            surge_threshold=d.surge_threshold,
            keep_color_prob=d.keep_color_prob,
            fatigue_seconds=d.fatigue_seconds,
            punch_cooldown_seconds=d.punch_cooldown_seconds,
            gamma_texture=d.gamma_texture,
            flash_intensity=d.flash_intensity,
            flash_cooldown_seconds=d.flash_cooldown_seconds,
            flash_beats=d.flash_beats,
            fade_seconds=d.fade_seconds,
            latency_seconds=d.latency_compensation_seconds,
        )
        _toml = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "config", "tuning.toml"
        )
        self.tuning_watcher = TuningWatcher(_toml, self.tuning)
        self.director = MusicDirector(
            frame_rate=frame_rate,
            history_seconds=d.history_seconds,
            threshold_recalc_seconds=d.threshold_recalc_seconds,
            section_window_seconds=d.section_window_seconds,
            section_delta=d.section_delta,
            section_cooldown_seconds=d.section_cooldown_seconds,
            step_intensity=d.step_intensity,
            no_beat_fallback_seconds=d.no_beat_fallback_seconds,
            latency_compensation_seconds=d.latency_compensation_seconds,
            beats_per_measure=d.beats_per_measure,
            shadow_dim=d.shadow_dim,
            shadow_blend=d.shadow_blend,
            state_min_beats=d.state_min_beats,
            state_max_beats=d.state_max_beats,
            play_prob_fast=d.play_prob_fast,
            play_prob_slow=d.play_prob_slow,
            bpm_fast=d.bpm_fast,
            bpm_slow=d.bpm_slow,
            fade_seconds=d.fade_seconds,
            accent_intensity=d.accent_intensity,
            accent_min_measures=d.accent_min_measures,
            glow_gain=d.glow_gain,
            glow_tau_seconds=d.glow_tau_seconds,
            measure_change_prob=d.measure_change_prob,
            figure_min_measures=d.figure_min_measures,
            figure_max_measures=d.figure_max_measures,
            pitch_follow_gain=d.pitch_follow_gain,
            promote_prob=d.promote_prob,
            move_min_seconds=d.move_min_seconds,
            flow_speed=d.flow_speed,
            flow_ease=d.flow_ease,
            flow_kick=d.flow_kick,
            dimming_floor=d.dimming_floor,
            blackout_seconds=d.blackout_seconds,
            blackout_floor=d.blackout_floor,
            flash_enabled=d.flash_enabled,
            punch_intensity=d.punch_intensity,
            punch_beats=d.punch_beats,
            micro_black_seconds=d.micro_black_seconds,
            micro_black_gap_seconds=d.micro_black_gap_seconds,
            breakdown_enabled=d.breakdown_enabled,
            breakdown_ratio=d.breakdown_ratio,
            breakdown_seconds=d.breakdown_seconds,
            breakdown_voice_min=d.breakdown_voice_min,
            breakdown_floor=d.breakdown_floor,
            mode=d.mode,
            groove_tau_seconds=d.groove_tau_seconds,
            intensity_tau_seconds=d.intensity_tau_seconds,
            surge_cooldown_seconds=d.surge_cooldown_seconds,
            tuning=self.tuning,
            improviser=improviser,
        )
        self.mapper = RGBMapper(
            brightness_alpha_up=settings.mapper.brightness_alpha_up,
            brightness_alpha_down=settings.mapper.brightness_alpha_down,
            flash_saturation=settings.mapper.flash_saturation,
            gamma=settings.mapper.color_gamma,
        )
        # Tope de seguridad anti-estroboscópico (independiente del tuning)
        self.safety = SafetyLimiter(frame_rate)
        self.ambient = AmbientMode()
        self._running = False
        self._stopped = False
        self._mode = settings.mode
        self._debug = settings.debug
        self._idle_colors: tuple[str, str] | None = None
        self._idle_idx = 0
        self._idle_changed_at = 0.0
        # Centroide espectral suavizado (~130ms a 375fps)
        self._centroid_ema = 0.5
        self._last_reload = 0.0

    async def start(self) -> None:
        self._stopped = False
        await self.wiz.start()
        if self._mode == "reactive":
            await self.audio.start()
        self._running = True
        logger.info(f"Pipeline started in {self._mode} mode")

    def request_stop(self) -> None:
        self._running = False

    async def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        self._running = False
        await self.audio.stop()
        await self.wiz.stop()
        logger.info("Pipeline stopped")

    async def run(self) -> None:
        await self.start()
        try:
            if self._mode == "reactive":
                await self._run_reactive()
            elif self._mode == "ambient":
                await self._run_ambient()
        finally:
            await self.stop()

    @staticmethod
    def _spark(v: float) -> str:
        blocks = " ▁▂▃▄▅▆▇█"
        return blocks[min(8, max(0, int(v * 8)))]

    def _print_debug(
        self,
        low: float,
        mid: float,
        high: float,
        decision: ColorDecision,
        r: int,
        g: int,
        b: int,
        dimming: int,
    ) -> None:
        dd = self.director
        if dd._frame % 62 != 0:  # throttle ~6Hz (375fps/62) — legible para humanos
            return
        tempo = dd.tempo
        ev = []
        if decision.blackout:
            ev.append("⬛TOTAL")
        elif decision.dimming <= 0.05:
            ev.append("⬛dip")
        if decision.section_change:
            ev.append("SECTION")
        if decision.flash > 0:
            ev.append("⚡FLASH")
        if dd._frame < dd._accent_hit_until and dd._accent_hit_color:
            ev.append({3: "MOTIF", 2: "PUNCH", 1: "HIT"}.get(dd._accent_hit_prio, "HIT"))
        if dd.breakdown:
            ev.append("BREAK")
        if dd._fallback:
            ev.append("~calma")
        if dd._pending_color:
            ev.append("↕TRANS")
        if dd._swell > 0.15:
            ev.append("≈SWELL")
        if dd._burst_color:
            ev.append("🎨BURST")
        if dd._frame < dd._dark_pulse_until:
            ev.append("▼dark")
        if dd._dry_stop:
            ev.append("✋SECO")
        if dd.deck.banned:
            ev.append("🚫" + ",".join(dd.deck.banned))
        if dd.anomalies.last and dd._frame - dd.anomalies.last_frame < 750:
            ev.append("⚠️" + dd.anomalies.last)
        if dd.dyn.trend > dd.tuning.surge_threshold:
            ev.append("↑MÉTELE")
        elif dd.dyn.trend < -dd.tuning.surge_threshold:
            ev.append("↓CALMA")
        if decision.texture > 0:
            ev.append("~tex")
        if dd.improviser.bump > 0.05:
            ev.append("bump")
        # en FLOW el socio real es _flow_partner (el de GROOVE queda rancio y
        # pintaba "orange→orange" fantasma en el debug)
        partner = (
            getattr(dd, "_flow_partner", "")
            if dd.move == "FLOW"
            else getattr(dd, "_partner", "")
        )
        mode = f" [{dd.dyn.mode}]" if dd.dyn.mode != "auto" else ""
        line = (
            f"♪ {dd.move:<6}·{dd.state:<7} {dd.color:>7}→{partner:<7} "
            f"rit{dd.dyn.groove:.2f} int{dd.dyn.intensity:.2f}{mode} "
            f"{tempo.bpm:5.1f}bpm  {decision.level:<6} dim{dimming:3d}  "
            f"L{self._spark(low)} M{self._spark(mid)} H{self._spark(high)}  "
            f"foco{dd.focus:.2f} mel{dd.melody:.2f} ton{self.stft.mid_tonalness:.2f} "
            f"val{dd.valence:.2f}  {' '.join(ev)}"
        )
        sys.stdout.write("\r\033[K" + line)
        sys.stdout.flush()

    async def _run_reactive(self) -> None:
        logger.info("Reactive mode running")
        last_chunk_at = time.monotonic()
        last_restart_at = 0.0
        idle = False

        while self._running:
            try:
                chunk = await asyncio.wait_for(self.audio.get_chunk(), timeout=0.1)
            except asyncio.TimeoutError:
                idle, last_restart_at = await self._handle_no_audio(
                    last_chunk_at, last_restart_at, idle
                )
                continue

            last_chunk_at = time.monotonic()
            if last_chunk_at - self._last_reload > 0.5:
                self._last_reload = last_chunk_at
                if self.tuning_watcher.maybe_reload():
                    logger.info(
                        f"tuning ↻ strength={self.tuning.dynamics_strength} "
                        f"vibe={self.tuning.vibe}"
                    )
            if idle:
                idle = False
                self.director.reset()
                self.mapper.reset()
                self.safety.reset()
                self.chroma.reset()
                logger.info("Audio back — resuming reactive mode")

            try:
                self.stft.process(chunk)
                low, mid, high = self.bands.process(chunk)
                low_n, mid_n, high_n = self.bands.normalize(low, mid, high)
                energy = (low_n + mid_n + high_n) / 3.0
                is_onset, onset_intensity = self.onset.process(self.stft.bands, energy)
                is_lead, lead_intensity = self.lead_onset.process(self.stft.bands, energy)
                # melodía = centroide MELÓDICO (banda media, sin batería) → el
                # seguir-melodía ya no se contamina con la percusión (rock)
                self._centroid_ema += (self.stft.mid_centroid - self._centroid_ema) * 0.02
                valence = self.chroma.process(chunk)  # mayor/menor (alegre/triste)

                decision = self.director.process(
                    low_n, mid_n, high_n, energy, is_onset, onset_intensity,
                    lead_onset=is_lead, lead_intensity=lead_intensity,
                    centroid=self._centroid_ema, valence=valence,
                    tonalness=self.stft.mid_tonalness,
                )
                self.mapper.luminance_comp = self.tuning.luminance_comp
                r, g, b, dimming = self.mapper.render(decision)
                # Capa de seguridad: limita flashes/estroboscopía (no se puede apagar)
                r, g, b, dimming = self.safety.filter(r, g, b, dimming)
                if decision.blackout:
                    self.wiz.turn_off()  # oscuridad TOTAL (solo blackout de sección, raro)
                else:
                    self.wiz.send_rgb(r, g, b, brightness=dimming)

                if self._debug:
                    self._print_debug(low_n, mid_n, high_n, decision, r, g, b, dimming)
            except Exception as e:
                logger.warning(f"Processing error: {e}")
                await asyncio.sleep(0.01)

    async def _handle_no_audio(
        self, last_chunk_at: float, last_restart_at: float, idle: bool
    ) -> tuple[bool, float]:
        """Sin chunks: detectar stream muerto, entrar en idle y reintentar."""
        now = time.monotonic()
        silent_for = now - last_chunk_at
        stream_dead = not self.audio.is_alive

        if not idle and (stream_dead or silent_for > self.settings.audio.idle_timeout):
            idle = True
            logger.warning(
                f"No audio for {silent_for:.1f}s (stream alive: {not stream_dead}) — idle mode"
            )

        if idle:
            self._idle_tick(now)

        if idle and (stream_dead or silent_for > self.settings.audio.idle_timeout):
            if now - last_restart_at > self.settings.audio.restart_interval:
                last_restart_at = now
                try:
                    await self.audio.restart()
                    logger.info("Audio stream restarted")
                except Exception as e:
                    logger.warning(f"Audio restart failed: {e}")

        return idle, last_restart_at

    def _idle_tick(self, now: float) -> None:
        """Sin música: alternar lento entre colores fundibles a brillo bajo."""
        grammar = self.director.grammar
        if self._idle_colors is None:
            self._idle_colors = grammar.random_fade_pair()
        if now - self._idle_changed_at > 4.0:
            self._idle_changed_at = now
            self._idle_idx = 1 - self._idle_idx
            if self._idle_idx == 0:
                # ciclo completo: renovar par manteniendo continuidad
                self._idle_colors = grammar.random_fade_pair(self._idle_colors[1])
            hue = grammar.hue(self._idle_colors[self._idle_idx])
            r, g, b = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
            self.wiz.send_rgb(int(r * 255), int(g * 255), int(b * 255), brightness=25)

    async def _run_ambient(self) -> None:
        logger.info("Ambient mode running")
        while self._running:
            r, g, b = self.ambient.process()
            self.wiz.send_rgb(r, g, b)
            await asyncio.sleep(0.05)

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        logger.info(f"Mode changed to {mode}")
