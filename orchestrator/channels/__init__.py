"""Canales sensores del director-de-orquesta.

Cada canal percibe UN aspecto de la música (melodía, beat, armonía, energía)
y reporta su lectura + una CONFIANZA. El conductor mezcla los reportes. Los
canales no deciden color: solo perciben.
"""

from .beat import BeatChannel
from .energy import EnergyChannel, EnergyReport
from .harmony import HarmonyChannel
from .melody import MelodyChannel, MelodyReport

__all__ = [
    "BeatChannel",
    "EnergyChannel",
    "EnergyReport",
    "HarmonyChannel",
    "MelodyChannel",
    "MelodyReport",
]
