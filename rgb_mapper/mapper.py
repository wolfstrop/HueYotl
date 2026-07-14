import colorsys
import math
from dataclasses import dataclass

from .smoothing import BrightnessSmoothing


@dataclass(frozen=True)
class ColorDecision:
    """Decisión del director para un frame: el mapper solo la renderiza."""

    hue: float           # hue exacto a pintar (0-1) — sostenido = salto, curva = fundido
    dimming: float       # brillo objetivo (0-1)
    flash: float         # 0 = nada; >0 = flash blanco deliberado (intensidad)
    level: str
    stepped: bool        # hubo cambio de color en este beat
    section_change: bool
    texture: float = 0.0  # 0 = nada; >0 = shimmer de gamma (mismo color, micro-saltos de brillo)
    blackout: bool = False  # True = apagar de verdad (oscuridad TOTAL) — solo blackout de sección (raro)


class RGBMapper:
    """Renderista puro: convierte la ColorDecision del director en RGB+dimming.

    - El hue es EXACTAMENTE el que manda el director, frame a frame — este
      renderista no aplica suavizado propio. Si el director sostiene un
      valor constante, se ve como salto (SNAP); si el director calcula una
      curva de cruce, se ve como fundido (FADE). La suavidad es decisión
      del director, no un filtro oculto aquí.
    - Saturación SIEMPRE 1.0 → los LEDs blancos del foco quedan en 0
      (pywizlight manda a los blancos toda componente acromática)
    - Flash blanco: única excepción, envelope corto que baja la saturación
      deliberadamente (sat <0.5 = blancos a tope en el foco)
    - Brillo por dimming del foco, nunca horneado en el RGB
    """

    def __init__(
        self,
        brightness_alpha_up: float = 0.55,
        brightness_alpha_down: float = 0.3,
        flash_saturation: float = 0.15,
        gamma: float = 1.8,
    ):
        self.flash_saturation = flash_saturation
        self.gamma = gamma
        # Compensación de LUMINANCIA PERCIBIDA (el "putazo"): a mismo dimming,
        # el verde se ve ~5× más brillante que el azul (Rec.601). Al saltar de
        # hue el brillo percibido pegaba un salto aunque el dimming no se moviera.
        # 0 = off (como antes); 1 = compensación fuerte. Lo fija el pipeline
        # desde tuning.toml en vivo.
        self.luminance_comp = 0.0

        self._brightness_smooth = BrightnessSmoothing(
            brightness_alpha_up, brightness_alpha_down
        )
        # Textura de gamma: onda SUAVE (seno) — shimmer gentil de brillo sin
        # saltos duros (los pasos escalonados anteriores causaban jitter/mareo).
        self._tex_i = 0
        self._tex_len = 300  # ~0.8s a 375fps: respiración lenta del brillo

    def render(self, decision: ColorDecision) -> tuple[int, int, int, int]:
        """Devuelve (r, g, b, dimming 10-255)."""
        hue = decision.hue

        # El flash lo modela el director (ataque + decaimiento al ritmo); aquí
        # solo se pinta: baja saturación (blancos del foco) y sube brillo.
        saturation = 1.0 - (1.0 - self.flash_saturation) * decision.flash

        brightness = self._brightness_smooth.update(decision.dimming)
        if decision.flash > 0:
            brightness = max(brightness, decision.flash)

        # Gamma con textura: micro-saltos discretos alrededor de la gamma base
        # → shimmer de brillo sin tocar el color. Mismo hue, mismo objetivo.
        gamma_eff = self.gamma
        if decision.texture > 0.0:
            self._tex_i = (self._tex_i + 1) % self._tex_len
            wobble = math.sin(2.0 * math.pi * self._tex_i / self._tex_len)  # -1..1 suave
            gamma_eff = self.gamma + decision.texture * wobble * 0.7
        brightness = pow(max(0.0, min(1.0, brightness)), 1.0 / gamma_eff)

        r, g, b = colorsys.hsv_to_rgb(hue, saturation, 1.0)
        if self.luminance_comp > 0.0:
            # iguala el brillo PERCIBIDO entre hues — v2, sin robar extremos
            # (v1 comprimía el rango: "le falta brillo" + "antes oscurecía más"):
            # · la SUBIDA de hues oscuros se desvanece cuando el momento es
            #   deliberadamente oscuro (EMBER/pozos/pisos siguen profundos)
            # · el RECORTE de hues brillantes se suaviza ×0.6 (los picos ciegan)
            lum = 0.299 * r + 0.587 * g + 0.114 * b
            comp = (0.35 / max(0.08, lum)) ** (0.85 * self.luminance_comp)
            if comp > 1.0:
                dark_intent = max(0.0, min(1.0, decision.dimming / 0.25))
                comp = 1.0 + (comp - 1.0) * dark_intent
            else:
                comp = 1.0 + (comp - 1.0) * 0.6
            brightness = max(0.0, min(1.0, brightness * comp))
        dimming = max(10, int(brightness * 255))
        return int(r * 255), int(g * 255), int(b * 255), dimming

    def reset(self) -> None:
        self._brightness_smooth.reset()
        self._tex_i = 0
