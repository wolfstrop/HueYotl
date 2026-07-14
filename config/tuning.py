"""Calibración EN VIVO. El director lee de este objeto compartido; un watcher
re-lee `tuning.toml` cada ~0.5s mientras corre el programa, así puedes editar
y guardar y ver el foco cambiar sin reiniciar.

`dynamics_strength` es la perilla maestra: 0 = comportamiento fijo (lo de antes),
1 = dinámica completa (ejes ritmo×intensidad al máximo). Sube de a poco.
"""

import os
import tomllib
from dataclasses import dataclass, fields


@dataclass
class Tuning:
    # --- Dinámica ---
    dynamics_strength: float = 1.0   # 0 = fijo (viejo), 1 = ejes al máximo
    vibe: str = "auto"               # auto | fiesta | chill | rock | hyperpop | classical
    surge_threshold: float = 0.18    # cuán brusco el cambio para métele/cálmate
    # --- Colores ---
    mood_strength: float = 1.0       # 0 = colores como antes; 1 = mood/tonalidad manda la clave
    valence_strength: float = 0.4    # cuánto empuja el modo (mayor/menor) la temperatura (0 = ignora, crudo)
    melody_lead_bias: float = 0.5    # cuánto la confianza (tonalness vs tempo) decide quién lidera; 0 = solo groove (viejo)
    gesture_brightness: float = 0.35 # cuánto los golpes suben el BRILLO; bajo = cambian color sin destellar (0 = solo color)
    brightness_dynamics: float = 0.6 # cuánto el brillo sigue la DINÁMICA (intensidad+crescendo); 0 = envolvente plana, 1 = respira fuerte
    transition_sensitivity: float = 0.5  # qué tan fácil detecta un cambio de frase/crescendo para cambiar color AL BEAT (↑ = más sensible)
    swell_strength: float = 0.7      # cuánto CRECE el brillo en una nota sostenida a todo pulmón (build de LD; 0 = off)
    rhythm_dark: float = 0.6         # ritmo en EJE OSCURO: cuando la melodía lidera, el beat golpea con pulsos de oscuridad (0 = off)
    burst_drive: float = 0.7         # umbral de la RÁFAGA color-por-beat cuando el ritmo grita (↓ = entra más fácil; 1 = off)
    luminance_comp: float = 0.5      # iguala brillo PERCIBIDO entre colores (el verde ciega, el azul apenas se ve); 0 = off (como antes)
    veda_seconds: float = 45.0       # cada cuánto se VETAN 1-2 colores (el sobreusado descansa + sorpresa); 0 = off
    veda_duration: float = 20.0      # cuánto dura la veda
    keep_color_prob: float = 0.4     # ↑ repite más el mismo color (menos alocado)
    fatigue_seconds: float = 10.0    # color sostenido más de esto → refresco
    palette_rotate_seconds: float = 12.0  # cada cuánto entra un color NUEVO al pool (rotación de fondo)
    figure_max_seconds: float = 4.0  # una figura no dura más de esto (anti-congelamiento)
    blackout_total: bool = True      # blackout de sección apaga de verdad (cuarto oscuro total)
    cut_prob: float = 0.25           # prob de corte OFF→ON en staccato
    punch_cooldown_seconds: float = 2.0  # ↓ = golpes de color más densos
    # --- Oscuros ---
    ember_weight: float = 1.0        # multiplicador del peso de EMBER (oscuros puros)
    brightness_ceiling: float = 0.82  # techo de brillo (↓ = más oscuro, cambios más visibles)
    gamma_texture: float = 0.35      # shimmer de brillo en figuras sostenidas
    melody_bright: float = 0.4       # cuánto sigue el brillo el contorno de la melodía (FLOW)
    # --- Flash ---
    flash_intensity: float = 0.82    # umbral (↑ = flash más raro)
    flash_cooldown_seconds: float = 4.5
    flash_beats: float = 0.6         # largo del flash (en beats)
    # --- Transiciones ---
    fade_seconds: float = 1.2        # largo del fade lento (FLOW)
    latency_seconds: float = 0.15    # lookahead predictivo (↑ = adelanta la luz)


class TuningWatcher:
    """Re-lee el .toml cuando cambia su mtime y vuelca los valores al Tuning."""

    def __init__(self, path: str, tuning: Tuning):
        self.path = path
        self.tuning = tuning
        self._mtime = 0.0
        self._names = {f.name for f in fields(Tuning)}

    def maybe_reload(self) -> bool:
        try:
            mtime = os.path.getmtime(self.path)
        except OSError:
            return False
        if mtime == self._mtime:
            return False
        self._mtime = mtime
        try:
            with open(self.path, "rb") as fh:
                data = tomllib.load(fh)
        except Exception:
            return False  # toml a medio guardar / inválido: ignora, reintenta
        flat: dict = {}
        for key, val in data.items():
            if isinstance(val, dict):
                flat.update(val)  # secciones [dinamica], [colores]…
            else:
                flat[key] = val
        for name, val in flat.items():
            if name in self._names:
                setattr(self.tuning, name, val)
        return True
