"""MODO GATO — luz ambiental nocturna, sin música. Marea + vela.

Colores profundos que se mueven como agua: cada color es una MAREA
(doble seno de brillo + ola ancha de hue hacia su color vecino) con un
toque de VELA (pasos aleatorios chicos — el "sabor"). Ritmo medio:
se mueve de verdad, pero más lento que un beat lento. Cada tanto,
fade largo hacia otra familia de color.

Rojo de base: los gatos casi no lo ven — para él es penumbra tranquila,
para ti se ve vivo.

Uso:  python modo_gato.py          (Ctrl+C apaga el foco y sale)
"""

import asyncio
import colorsys
import math
import random
import sys

from config.nivel import leer_nivel
from wiz_controller.protocol import WizProtocol

BULB_IP = "192.168.100.11"

# nombre → (hue 0-1, peso). Todo va saturado a tope (colores profundos).
PALETTE = {
    "rojo":    (0.000, 5.0),
    "naranja": (0.036, 3.0),   # naranja fuerte (255,55,0)
    "azul":    (0.640, 1.0),
    "verde":   (0.375, 1.0),
}
# hacia quién ondula cada color durante su marea (siempre un pariente)
NEIGHBOR = {"rojo": "naranja", "naranja": "rojo", "azul": "verde", "verde": "azul"}

HOLD_RANGE = (20.0, 45.0)   # segundos de marea por color
FADE_RANGE = (9.1, 15.6)    # segundos de transición entre familias
DIM_BASE = (0.18, 0.30)     # brillo medio de la marea (WiZ mínimo real 10%)
FR = 8                      # updates/s (el firmware licúa pasos <130ms)

# marea: dos senos desfasados ("medio rápido, no beat")
T_SWELL, T_CHOP = 4.4, 2.7  # s por ciclo de cada seno de brillo
T_HUE = 10.4                # s por ola completa de color hacia el vecino
SWELL_DEPTH = 0.30          # ±30% de brillo alrededor del medio
# vela: paso aleatorio chico cada ~0.4s (el sabor)
VELA_STEP = 0.05


def _lerp_hue(a: float, b: float, t: float) -> float:
    d = ((b - a + 0.5) % 1.0) - 0.5   # camino corto en el círculo de hue
    return (a + d * t) % 1.0


async def _paint(proto, hue: float, dim: float) -> None:
    r, g, b = colorsys.hsv_to_rgb(hue % 1.0, 1.0, 1.0)
    dim *= leer_nivel()               # nivel GLOBAL (TUI j/k o MCP), en vivo
    dim = min(0.85, max(0.10, dim))   # techo: penumbra por defecto (nivel 1)
    await proto.send_rgb(int(r * 255), int(g * 255), int(b * 255),
                         brightness=round(dim * 255))


def _pick(current: str) -> str:
    # tras un frío (azul/verde) siempre regresa al calor
    if current in ("azul", "verde"):
        return random.choices(["rojo", "naranja"], weights=[5.0, 3.0])[0]
    names = [n for n in PALETTE if n != current]
    return random.choices(names, weights=[PALETTE[n][1] for n in names])[0]


async def _marea(proto, color: str, dim_mid: float, seconds: float) -> tuple[float, float]:
    """El hold vivo: brillo con doble seno, hue oleando hacia el vecino,
    y la vela metiendo pasitos aleatorios encima.

    COSTURAS (medido en simulación: los saltos vivían aquí, no adentro):
    - la ola de hue arranca en fase -π/2 → empieza EXACTO en el color puro,
      donde el fade anterior nos dejó (fase aleatoria brincaba media rueda)
    - el oleaje de brillo entra con rampa de 2s → arranca exacto en dim_mid
    Devuelve (hue, dim) del último frame para que el fade siga desde ahí."""
    hue_a = PALETTE[color][0]
    hue_b = PALETTE[NEIGHBOR[color]][0]
    phase = random.uniform(0, 2 * math.pi)   # solo el brillo varía de arranque
    vela = 0.0
    hue, dim = hue_a, dim_mid
    n = int(seconds * FR)
    for i in range(n):
        t = i / FR
        env = min(1.0, t / 2.0)               # rampa: el oleaje amanece
        s1 = math.sin(2 * math.pi * t / T_SWELL + phase)
        s2 = math.sin(2 * math.pi * t / T_CHOP + phase + 1.3)
        swell = SWELL_DEPTH * (0.55 * s1 + 0.45 * s2)
        if i % int(FR * 0.52 + 0.5) == 0:     # la vela da su pasito
            vela = min(0.10, max(-0.10, vela + random.uniform(-VELA_STEP, VELA_STEP)))
        hue = _lerp_hue(hue_a, hue_b,
                        0.5 + 0.5 * math.sin(2 * math.pi * t / T_HUE - math.pi / 2))
        dim = dim_mid * (1 + (swell + vela) * env)
        await _paint(proto, hue, dim)
        await asyncio.sleep(1 / FR)
    return hue, dim


async def _fade(proto, hue_a, hue_b, dim_a, dim_b, seconds) -> None:
    """Arranca desde el (hue, dim) REAL donde quedó la marea, no del ideal.
    Termina exacto en (hue_b, dim_b): el ripple se desvanece con (1-s)."""
    n = max(1, int(seconds * FR))
    for i in range(1, n + 1):
        t = i / n
        s = t * t * (3 - 2 * t)   # smoothstep
        # VALLE de crossfade: el brillo respira hacia abajo a mitad del viaje
        # — los hues intermedios (que no son de nadie) pasan en penumbra y el
        # color nuevo AMANECE al llegar, en vez de saltos saturados a medio
        # camino. Ripple suave encima para que la marea no muera.
        valley = 1 - 0.35 * math.sin(math.pi * s)
        ripple = 1 + 0.06 * math.sin(2 * math.pi * (i / FR) / T_SWELL) * (1 - s)
        await _paint(proto, _lerp_hue(hue_a, hue_b, s),
                     (dim_a + (dim_b - dim_a) * s) * valley * ripple)
        await asyncio.sleep(1 / FR)


async def main():
    proto = WizProtocol(BULB_IP)
    color = "rojo"
    dim = 0.22
    print("modo gato 🐈 — marea roja, deriva con sabor (Ctrl+C apaga)")
    try:
        while True:
            hue_last, dim_last = await _marea(proto, color, dim,
                                              random.uniform(*HOLD_RANGE))
            nxt = _pick(color)
            nxt_dim = random.uniform(*DIM_BASE)
            print(f"  {color} → {nxt} ({nxt_dim * 100:.0f}%)")
            await _fade(proto, hue_last, PALETTE[nxt][0],
                        dim_last, nxt_dim, random.uniform(*FADE_RANGE))
            color, dim = nxt, nxt_dim
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        try:
            await proto.turn_off()
        except Exception:
            pass
        proto.close()
        print("\nfoco apagado — buenas noches a los dos")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
