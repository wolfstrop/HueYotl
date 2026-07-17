"""NIVEL GLOBAL de iluminación: una sola perilla (0.1-1.6×) que TODOS los
modos respetan — gato y ambiente multiplican su brillo, el reactivo escala
su dimming final. Vive en logs/nivel_global; lo escriben el TUI (j/k) y el
MCP (Lorika), lo releen los modos en <2s. Sin archivo = 1.0 (neutro)."""

import os
import time

NIVEL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "logs", "nivel_global",
)
NIVEL_MIN, NIVEL_MAX = 0.1, 1.6

_cache = {"checked": 0.0, "valor": 1.0}


def leer_nivel() -> float:
    """Nivel actual, con caché de 2s (apto para llamarse cada frame)."""
    now = time.monotonic()
    if now - _cache["checked"] > 2.0:
        _cache["checked"] = now
        try:
            with open(NIVEL_PATH) as fh:
                _cache["valor"] = min(NIVEL_MAX, max(NIVEL_MIN, float(fh.read().strip())))
        except (OSError, ValueError):
            _cache["valor"] = 1.0
    return _cache["valor"]


def escribir_nivel(nivel: float) -> float:
    """Clampea, persiste y devuelve el nivel efectivo."""
    nivel = min(NIVEL_MAX, max(NIVEL_MIN, nivel))
    os.makedirs(os.path.dirname(NIVEL_PATH), exist_ok=True)
    with open(NIVEL_PATH, "w") as fh:
        fh.write(f"{nivel:.2f}")
    _cache["checked"] = 0.0  # el propio proceso lo ve al instante
    return nivel
