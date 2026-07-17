import colorsys
import math
import random
import time

from config.nivel import leer_nivel


class AmbientMode:
    """Luz ambiental PARA VER, pero con sabor: base circadiana (blanco
    cálido/neutro según la hora, estilo f.lux) + una CAPA DE COLOR siempre
    presente que recorre toda la rueda despacio. Aquí sí se juega con todos
    los colores — no hay música que respetar ni gato que cuidar.

    - lavado de color continuo: hue da la vuelta completa en ~4 min
      (de día pinta un 30%, de noche un 50% — de noche manda el color)
    - BRISAS: cada 40-100s el color toma el mando (hasta ~85%) por 20-40s
    - respiración de brillo, deriva del punto de blanco
    - NIVEL GLOBAL en vivo (config.nivel): j/k del TUI o el MCP
    """

    # hora → (rgb aproximando kelvin, brillo 0-1); interpola entre puntos
    KEYFRAMES = [
        (0.0,  (255, 147, 41),  0.45),   # madrugada: vela 2200K
        (6.0,  (255, 169, 87),  0.55),   # amanecer: 2700K subiendo
        (9.0,  (255, 219, 186), 0.95),   # día: neutro 4500K a tope
        (17.0, (255, 219, 186), 0.95),   # tarde: sigue neutro
        (20.0, (255, 180, 107), 0.85),   # atardecer: 3000K cálido
        (23.0, (255, 147, 41),  0.50),   # noche: vela otra vez
        (24.0, (255, 147, 41),  0.45),   # cierra el ciclo con las 0h
    ]
    T_WASH = 240.0        # s por vuelta completa a la rueda de color

    def __init__(self, breathe_period: float = 11.0, breathe_depth: float = 0.06):
        self._breathe_period = breathe_period
        self._breathe_depth = breathe_depth
        self._start = time.monotonic()
        self.brightness = 128  # 0-255, lo lee el pipeline para el dimming
        self._brisa_at = time.monotonic() + random.uniform(15.0, 40.0)
        self._brisa_dur = 0.0

    def _daylight(self, hour: float) -> tuple[tuple[int, int, int], float]:
        kf = self.KEYFRAMES
        for i in range(len(kf) - 1):
            h0, rgb0, d0 = kf[i]
            h1, rgb1, d1 = kf[i + 1]
            if h0 <= hour <= h1:
                t = (hour - h0) / (h1 - h0)
                s = t * t * (3 - 2 * t)  # smoothstep: sin codos entre tramos
                rgb = tuple(round(a + (b - a) * s) for a, b in zip(rgb0, rgb1))
                return rgb, d0 + (d1 - d0) * s
        return kf[-1][1], kf[-1][2]

    def _brisa(self, now: float) -> float:
        """Fuerza 0-1 en campana sin(π·u): el color toma el mando y lo suelta
        sin escalón. Al terminar, agenda la siguiente."""
        elapsed = now - self._brisa_at
        if elapsed < 0:
            return 0.0
        if elapsed >= self._brisa_dur:
            self._brisa_at = now + random.uniform(40.0, 100.0)
            self._brisa_dur = random.uniform(20.0, 40.0)
            return 0.0
        return math.sin(math.pi * elapsed / self._brisa_dur)

    def process(self) -> tuple[int, int, int]:
        lt = time.localtime()
        hour = lt.tm_hour + lt.tm_min / 60.0 + lt.tm_sec / 3600.0
        (r, g, b), dim = self._daylight(hour)
        now = time.monotonic()
        t = now - self._start

        # lavado de color: hue recorre la rueda con un vaivén encima para
        # que no sea un carrusel parejo (a veces se entretiene, a veces corre)
        hue = (t / self.T_WASH + 0.06 * math.sin(2 * math.pi * t / 31.0)) % 1.0
        cr, cg, cb = (c * 255 for c in colorsys.hsv_to_rgb(hue, 1.0, 1.0))

        # peso del color: de día acompaña, de noche manda; la brisa lo dispara
        daytime = 8.0 <= hour < 19.0
        w = (0.30 if daytime else 0.50) + 0.35 * self._brisa(now)
        r += (cr - r) * w
        g += (cg - g) * w
        b += (cb - b) * w

        # respiración + nivel en vivo (j/k del TUI); la brisa levanta tantito
        dim *= 1 + self._breathe_depth * math.sin(2 * math.pi * t / self._breathe_period)
        dim *= (1 + 0.10 * (w - 0.3)) * leer_nivel()
        self.brightness = max(26, min(255, round(dim * 255)))
        return (
            max(0, min(255, round(r))),
            max(0, min(255, round(g))),
            max(0, min(255, round(b))),
        )
