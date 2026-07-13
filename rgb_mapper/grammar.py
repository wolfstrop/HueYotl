"""Gramática de color: qué colores existen, cuáles funden bien y cuáles cortan.

Las reglas son DATOS editables — calibrar viendo el foco, no en teoría:
- FADE_PAIRS: transiciones que se notan Y combinan (barridos/fundidos)
- CUT_PAIRS: contrastes fuertes, válidos solo como cambio dramático
- Pares que no aparecen: prohibidos (vecinos indistinguibles o combos que
  marean, p.ej. rojo-azul fundido pasa por todo el morado y satura)
"""

import random


def _clamp01(x: float) -> float:
    return min(1.0, max(0.0, x))


# Hues ancla (0-1). Ajustados a cómo rinde el foco WiZ, no al círculo ideal.
ANCHORS: dict[str, float] = {
    "red": 0.0,
    "orange": 0.05,
    "amber": 0.11,
    "green": 0.33,
    "teal": 0.47,
    "blue": 0.62,
    "purple": 0.75,
    "magenta": 0.87,
}

FADE_PAIRS: set[frozenset[str]] = {
    frozenset(p)
    for p in [
        ("purple", "green"),     # confirmado en pruebas: funde rico
        ("green", "orange"),     # confirmado: pasa por ámbar
        ("blue", "magenta"),     # pasa por morado, elegante
        ("teal", "purple"),
        ("amber", "teal"),
        ("orange", "magenta"),   # pasa por rojo
        ("blue", "teal"),
        ("green", "teal"),
        ("amber", "magenta"),
        ("teal", "magenta"),   # pasa por azul/morado — cierra el triángulo
                               # azul-teal-magenta para accents
        # --- Fase 20b: balancear el grafo (rojo estaba aislado; cálidos y azul
        # poco conectados → salían poco). Todos son vecinos de hue = funden bien.
        ("red", "orange"),     # cálidos adyacentes, funde limpio
        ("orange", "amber"),   # cierra la cadena cálida rojo-naranja-ámbar
        ("red", "magenta"),    # adyacentes por el otro lado (rojo↔magenta)
        ("blue", "purple"),    # cool adyacente → azul entra más, morado por su lado
    ]
}

CUT_PAIRS: set[frozenset[str]] = {
    frozenset(p)
    for p in [
        ("blue", "red"),         # NUNCA fundir (marea); como corte es dramático
        ("green", "magenta"),
        ("orange", "blue"),
        ("amber", "purple"),
        ("red", "teal"),
    ]
}

# Colores que funcionan como MONO profundo (un solo color puro respirando)
MONO_COLORS: tuple[str, ...] = ("blue", "red", "purple", "green")

# Dominancia (iluminación de escenario): los cálidos dominan a los fríos y
# tienden a llevar el ritmo como color base; los fríos/lavanda son recesivos
# (mejores como acento). Sesga la elección del color base, no la prohíbe.
DOMINANCE: dict[str, float] = {
    "red": 1.0,
    "orange": 1.0,
    "amber": 0.9,
    "magenta": 0.7,
    "green": 0.6,
    "purple": 0.5,
    "teal": 0.45,
    "blue": 0.4,
}

# Mood/tonalidad: cada color tiene una CALIDEZ (0 frío ↔ 1 cálido) y un VALOR
# (0 profundo/oscuro ↔ 1 brillante/claro). El mood (temperatura + profundidad)
# arma una CLAVE de color ponderando estos — como una tonalidad musical: un set
# variado de colores que combinan, no un solo hue. Editables a gusto.
WARMTH: dict[str, float] = {
    "red": 1.0, "orange": 1.0, "amber": 0.95, "magenta": 0.75,
    "purple": 0.55, "green": 0.45, "teal": 0.3, "blue": 0.1,
}
VALUE: dict[str, float] = {
    "amber": 0.85, "orange": 0.7, "magenta": 0.65, "green": 0.6,
    "teal": 0.55, "purple": 0.4, "red": 0.35, "blue": 0.3,
}

# Ancla del estado "oscuro" del ritmo: un tenue azul, no cualquier vecino
SHADOW_HUE = ANCHORS["blue"]


class ColorGrammar:
    def hue(self, name: str) -> float:
        return ANCHORS[name]

    def all_colors(self) -> list[str]:
        return list(ANCHORS)

    def fade_partners(self, name: str) -> list[str]:
        return [other for pair in FADE_PAIRS if name in pair for other in pair if other != name]

    def cut_partners(self, name: str) -> list[str]:
        return [other for pair in CUT_PAIRS if name in pair for other in pair if other != name]

    def random_color(self) -> str:
        return random.choice(list(ANCHORS))

    def random_fade_pair(self, keep: str | None = None) -> tuple[str, str]:
        """Par fundible; si keep tiene socios, el par lo incluye (continuidad)."""
        if keep is not None:
            partners = self.fade_partners(keep)
            if partners:
                return keep, random.choice(partners)
        pair = tuple(random.choice(list(FADE_PAIRS)))
        return pair[0], pair[1]

    def accent_candidates(self, a: str, b: str) -> list[str]:
        """Todos los terceros que funden con AMBOS de la pareja (ordenados:
        el orden de un set depende del hash del proceso → no determinista)."""
        candidates = set(self.fade_partners(a)) & set(self.fade_partners(b))
        candidates -= {a, b}
        return sorted(candidates)

    def accent_for(self, a: str, b: str) -> str | None:
        """Tercer color que funde bien con AMBOS de la pareja actual — el
        'impar que combina' (p.ej. verde-morado-teal forman triángulo).
        None si no existe: no forzar combos que no están en la gramática.
        """
        candidates = self.accent_candidates(a, b)
        return random.choice(candidates) if candidates else None

    def cut_from(self, name: str) -> str:
        partners = self.cut_partners(name)
        if partners:
            return random.choice(partners)
        # sin corte definido: el fundible más lejano sirve de contraste
        return max(
            self.fade_partners(name) or list(ANCHORS),
            key=lambda o: self._dist(name, o),
        )

    def nearest_mono(self, name: str) -> str:
        return min(MONO_COLORS, key=lambda m: self._dist(name, m))

    def nearest_anchor(self, hue: float) -> str:
        """Ancla más cercana a un hue mostrado (para contar qué color se ve)."""
        return min(ANCHORS, key=lambda k: min(abs(ANCHORS[k] - hue), 1 - abs(ANCHORS[k] - hue)))

    def dominance(self, name: str) -> float:
        return DOMINANCE.get(name, 0.6)

    def mood_weights(
        self, temperature: float, depth: float, breadth: float, strength: float = 1.0
    ) -> dict[str, float]:
        """Peso de cada color según el mood = la 'clave' de color de la canción.
        `temperature` (frío↔cálido) y `depth` (profundo↔brillante) centran la
        clave; `breadth` la abre (más variedad en lo movido); `strength` mezcla
        con uniforme (0 = deck de siempre, 1 = mood pleno). Un set VARIADO que
        combina, no un solo tono.
        """
        # exponente agresivo: strength sube la nitidez de la clave; breadth la
        # afloja (movida = más variedad). strength 0 → uniforme (colores de antes).
        exponent = _clamp01(strength) * 4.0 * (1.0 - 0.6 * _clamp01(breadth))
        weights: dict[str, float] = {}
        for name in ANCHORS:
            fit = (1.0 - abs(WARMTH[name] - temperature)) * (1.0 - abs(VALUE[name] - depth))
            weights[name] = max(0.03, fit) ** exponent
        return weights

    def _dist(self, a: str, b: str) -> float:
        d = abs(ANCHORS[a] - ANCHORS[b])
        return min(d, 1 - d)
