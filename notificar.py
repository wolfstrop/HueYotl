"""Motor de NOTIFICACIONES por el foco — Lorika avisa con luz.

Cuatro patrones básicos; los presets viven en config/notificaciones.json
(editables vía MCP con definir_notificacion). Prioridades:
- "suave": finita (ciclos) — el MCP pausa el modo actual, toca esto y
  RESTAURA el modo. No pierdes tu música por un aviso menor.
- "toma": infinita — desaloja el modo y SE QUEDA hasta que la paren.
  El foco ES la notificación (rojo latiendo = ve a los servidores).

Uso:  notificar.py <preset>          (p.ej. notificar.py alerta)
      notificar.py --spec '<json>'   (spec inline, ya validada)
"""

import asyncio
import colorsys
import json
import math
import os
import sys

from config import Settings
from rgb_mapper.grammar import ANCHORS
from wiz_controller.protocol import WizProtocol

ROOT = os.path.dirname(os.path.abspath(__file__))
PRESETS_PATH = os.path.join(ROOT, "config", "notificaciones.json")
FR = 8  # updates/s (pasos <130ms el firmware WiZ los licúa)

COLOR_ALIAS = {
    "rojo": "red", "naranja": "orange", "ambar": "amber", "ámbar": "amber",
    "verde": "green", "turquesa": "teal", "azul": "blue",
    "morado": "purple", "violeta": "purple", "magenta": "magenta",
    "rosa": "magenta",
}
PATRONES = ("respiracion", "latido", "alternancia", "amanecer")
VEL = {"lenta": 1.5, "media": 1.0, "rapida": 0.7}   # multiplica el periodo


def hue_de(color: str) -> float:
    name = COLOR_ALIAS.get(color.strip().lower(), color.strip().lower())
    if name not in ANCHORS:
        raise ValueError(f"color '{color}' no existe — usa {', '.join(sorted(ANCHORS))}")
    return ANCHORS[name]


def validar_spec(spec: dict) -> dict:
    """Normaliza y acota una spec. Los límites hacen imposible un strobe:
    el periodo mínimo de cualquier patrón es 0.84s (latido rapida)."""
    out = {}
    patron = spec.get("patron")
    if patron not in PATRONES:
        raise ValueError(f"patron debe ser uno de: {', '.join(PATRONES)}")
    out["patron"] = patron
    colores = spec.get("colores") or []
    if not 1 <= len(colores) <= 2:
        raise ValueError("colores: lista de 1 o 2 nombres")
    for c in colores:
        hue_de(c)  # valida
    out["colores"] = colores
    out["velocidad"] = spec.get("velocidad", "media")
    if out["velocidad"] not in VEL:
        raise ValueError(f"velocidad: {', '.join(VEL)}")
    out["brillo"] = min(100, max(10, int(spec.get("brillo", 60))))
    out["prioridad"] = spec.get("prioridad", "suave")
    if out["prioridad"] not in ("suave", "toma"):
        raise ValueError("prioridad: suave | toma")
    if "ciclos" in spec:
        out["ciclos"] = min(20, max(1, int(spec["ciclos"])))
    elif out["prioridad"] == "suave" and patron != "amanecer":
        out["ciclos"] = 3  # suave sin ciclos no puede ser infinita
    if patron == "amanecer":
        out["duracion"] = min(1800, max(30, int(spec.get("duracion", 300))))
    return out


async def _paint(proto, hue: float, dim: float) -> None:
    r, g, b = colorsys.hsv_to_rgb(hue % 1.0, 1.0, 1.0)
    dim = min(1.0, max(0.04, dim))
    await proto.send_rgb(round(r * 255), round(g * 255), round(b * 255),
                         brightness=round(dim * 255))


def _ciclos(spec) -> range:
    n = spec.get("ciclos")
    return range(n) if n else iter(int, 1)  # sin ciclos = infinito


async def respiracion(proto, spec):
    hue = hue_de(spec["colores"][0])
    peak = spec["brillo"] / 100
    T = 2.8 * VEL[spec["velocidad"]]
    for _ in _ciclos(spec):
        for i in range(int(T * FR)):
            u = i / (T * FR)
            await _paint(proto, hue, 0.06 + (peak - 0.06) * math.sin(math.pi * u) ** 2)
            await asyncio.sleep(1 / FR)


async def latido(proto, spec):
    """Tun-tún sobre fondo oscuro (el latido aprobado de las ondas). Con dos
    colores, alterna el color por ciclo (Cleo: verde, ámbar, verde…)."""
    hues = [hue_de(c) for c in spec["colores"]]
    peak = spec["brillo"] / 100
    floor = 0.07
    T = 1.2 * VEL[spec["velocidad"]]
    k = 0
    for _ in _ciclos(spec):
        hue = hues[k % len(hues)]
        k += 1
        for i in range(int(T * FR)):
            ph = i / (T * FR)
            # dos golpes con caída exponencial; el primero aguanta 2 frames
            # a tope (lección WiZ: los picos cortos los come el firmware)
            g1 = 1.0 if ph < 2 / (T * FR) else math.exp(-9 * ph)
            g2 = 0.55 * math.exp(-9 * max(0.0, ph - 0.30))
            await _paint(proto, hue, floor + (peak - floor) * max(g1, g2))
            await asyncio.sleep(1 / FR)


async def alternancia(proto, spec):
    """Crossfade lento A↔B (pendientes: azul↔naranja). Tranquila, sin prisa."""
    a = hue_de(spec["colores"][0])
    b = hue_de(spec["colores"][-1])
    peak = spec["brillo"] / 100
    T = 11.0 * VEL[spec["velocidad"]]
    i = 0
    for _ in _ciclos(spec):
        for _ in range(int(T * FR)):
            t = i / FR
            i += 1
            d = ((b - a + 0.5) % 1.0) - 0.5   # camino corto en la rueda
            hue = (a + d * (0.5 + 0.5 * math.sin(2 * math.pi * t / T))) % 1.0
            dim = peak * (0.82 + 0.18 * math.sin(2 * math.pi * t / 7.0))
            await _paint(proto, hue, dim)
            await asyncio.sleep(1 / FR)


async def amanecer(proto, spec):
    """Rampa de casi-nada a brillante (despertador) y SE QUEDA respirando
    hasta que la paren — despertar sin sobresalto, luz lista al abrir ojos."""
    a = hue_de(spec["colores"][0])
    b = hue_de(spec["colores"][-1])
    peak = spec["brillo"] / 100
    n = int(spec["duracion"] * FR)
    for i in range(n):
        u = i / n
        s = u * u                              # arranque imperceptible
        d = ((b - a + 0.5) % 1.0) - 0.5
        await _paint(proto, (a + d * s) % 1.0, 0.02 + (peak - 0.02) * s)
        await asyncio.sleep(1 / FR)
    t = 0.0
    while True:                                # ya amaneció: sostiene
        await _paint(proto, b, peak * (1 + 0.05 * math.sin(2 * math.pi * t / 9.0)))
        await asyncio.sleep(0.5)
        t += 0.5


async def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "--spec":
        spec = json.loads(sys.argv[2])
    elif len(sys.argv) == 2:
        with open(PRESETS_PATH) as fh:
            presets = json.load(fh)
        if sys.argv[1] not in presets:
            sys.exit(f"preset '{sys.argv[1]}' no existe")
        spec = presets[sys.argv[1]]
    else:
        sys.exit(__doc__)
    spec = validar_spec(spec)
    s = Settings()
    proto = WizProtocol(s.wiz.ip, s.wiz.port)
    try:
        await {"respiracion": respiracion, "latido": latido,
               "alternancia": alternancia, "amanecer": amanecer}[spec["patron"]](proto, spec)
    except (KeyboardInterrupt, asyncio.CancelledError):
        try:
            await proto.turn_off()   # interrumpida (toma): suelta el foco
        except Exception:
            pass
    finally:
        proto.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
