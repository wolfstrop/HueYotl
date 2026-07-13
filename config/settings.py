from dataclasses import dataclass, field


@dataclass
class WizSettings:
    ip: str = "192.168.100.11"
    port: int = 38899
    update_hz: int = 30
    timeout: float = 5.0


@dataclass
class AudioSettings:
    sample_rate: int = 48000
    chunk_size: int = 128
    channels: int = 1
    device: str | None = None
    idle_timeout: float = 5.0
    restart_interval: float = 2.0


@dataclass
class BandSettings:
    low: tuple[int, int] = (30, 250)
    mid: tuple[int, int] = (250, 4000)
    high: tuple[int, int] = (4000, 16000)


@dataclass
class MapperSettings:
    brightness_alpha_up: float = 0.55
    brightness_alpha_down: float = 0.15
    flash_saturation: float = 0.15
    color_gamma: float = 1.8


@dataclass
class CalibrationSettings:
    enabled: bool = True
    window: int = 1500
    percentile: float = 0.95


@dataclass
class OnsetSettings:
    flux_threshold: float = 0.5
    cooldown_ms: int = 300
    history_size: int = 43
    energy_gate: float = 0.25
    min_intensity: float = 0.3
    whiten_decay_seconds: float = 3.0


@dataclass
class DirectorSettings:
    history_seconds: float = 45.0
    threshold_recalc_seconds: float = 1.0
    section_window_seconds: float = 2.0
    section_delta: float = 0.35
    section_cooldown_seconds: float = 8.0
    step_intensity: float = 0.35
    no_beat_fallback_seconds: float = 4.0
    latency_compensation_seconds: float = 0.15  # lookahead: la luz cae EN el beat (compensa el fade del firmware)
    beats_per_measure: int = 4
    # Máquina de estados rítmica (BRIGHT/SHADOW/ACCENT)
    shadow_dim: float = 0.18
    shadow_blend: float = 0.6
    state_min_beats: int = 1
    state_max_beats: int = 2
    play_prob_fast: float = 0.6
    play_prob_slow: float = 0.2
    bpm_fast: float = 125.0
    bpm_slow: float = 95.0
    fade_seconds: float = 1.2
    accent_intensity: float = 0.55
    accent_min_measures: int = 4
    glow_gain: float = 0.6
    glow_tau_seconds: float = 0.4
    measure_change_prob: float = 0.7
    figure_min_measures: int = 2
    figure_max_measures: int = 3
    pitch_follow_gain: float = 0.6
    promote_prob: float = 0.6
    keep_color_prob: float = 0.4  # prob de repetir el MISMO color al cambiar de figura (juega entre 2-3, no se aloca)
    move_min_seconds: float = 5.0
    fatigue_seconds: float = 10.0  # color sostenido más de esto → refresco al complemento
    # FLOW con inercia (Fase 3 recuperada, dentro de la gramática):
    # velocidad-crucero lenta hacia el socio (~1.7s por transición), con inercia
    flow_speed: float = 0.0004
    flow_ease: float = 0.03
    flow_kick: float = 0.003
    # Textura de gamma: shimmer de brillo en figuras sostenidas (0 = off)
    gamma_texture: float = 0.35
    dimming_floor: float = 0.2
    blackout_seconds: float = 0.35
    blackout_floor: float = 0.03
    flash_enabled: bool = True
    flash_intensity: float = 0.82  # umbral alto → el flash blanco sale poco, no siempre
    flash_cooldown_seconds: float = 4.5
    flash_beats: float = 0.6  # en cuántos beats decae el flash (más corto = menos presente)
    # Capa 2: golpe de color (tercer color como stab seco en el beat).
    # Cooldown alto = 2 colores base + el tercero como INTERRUPCIÓN, no rotación de 3.
    punch_intensity: float = 0.6
    punch_cooldown_seconds: float = 2.0
    punch_beats: float = 0.25
    # Capa 3: micro-apagón = OFF→ON real. ~0.11s para que ≥3 envíos (a 30Hz) aterricen el OFF.
    micro_black_seconds: float = 0.11
    micro_black_gap_seconds: float = 2.0
    # Capa 4: breakdown / respiro (voz sola, música se calla)
    breakdown_enabled: bool = True
    breakdown_ratio: float = 0.5
    breakdown_seconds: float = 0.35
    breakdown_voice_min: float = 0.15
    breakdown_floor: float = 0.15
    # Dinámica: dos ejes (ritmo × intensidad) + modo + métele/cálmate
    mode: str = "auto"  # auto | fiesta | chill | rock | hyperpop | classical
    groove_tau_seconds: float = 1.0
    intensity_tau_seconds: float = 0.5
    surge_threshold: float = 0.18  # diferencia EMA rápida−lenta para métele/cálmate
    surge_cooldown_seconds: float = 3.0


@dataclass
class ImproviserSettings:
    bump_gain: float = 0.35
    bump_tau_seconds: float = 0.15
    spike_ratio: float = 1.6
    bump_cooldown_seconds: float = 2.0
    stab_intensity: float = 0.6
    stab_cooldown_seconds: float = 1.5
    replan_drop: float = 0.25
    replan_cooldown_seconds: float = 6.0
    motif_min_ms: float = 60.0
    motif_max_ms: float = 600.0
    motif_cooldown_seconds: float = 2.5


@dataclass
class Settings:
    wiz: WizSettings = field(default_factory=WizSettings)
    audio: AudioSettings = field(default_factory=AudioSettings)
    bands: BandSettings = field(default_factory=BandSettings)
    mapper: MapperSettings = field(default_factory=MapperSettings)
    calibration: CalibrationSettings = field(default_factory=CalibrationSettings)
    onset: OnsetSettings = field(default_factory=OnsetSettings)
    director: DirectorSettings = field(default_factory=DirectorSettings)
    improviser: ImproviserSettings = field(default_factory=ImproviserSettings)
    mode: str = "reactive"
    debug: bool = False
