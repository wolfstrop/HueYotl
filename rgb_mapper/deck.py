import random

from .grammar import ColorGrammar


class ColorDeck:
    """Set rodante de 5 colores: 3 PRINCIPALES + 1 ENTRANTE + 1 SALIENTE.

    - Cambios bruscos: se juega entre los principales (y a veces el
      saliente se asoma — memoria de la paleta anterior)
    - Momentos tranquilos: el entrante se deja ver (audición del color
      que va a entrar a la paleta)
    - promote(): el entrante sube a principal, el principal más viejo
      pasa a saliente, y entra un candidato nuevo compatible por gramática
    """

    def __init__(self, grammar: ColorGrammar, seed_color: str | None = None):
        self.grammar = grammar
        # Pesos del mood (la 'clave' de color). None = uniforme (deck de siempre).
        self.mood_weights: dict[str, float] | None = None
        # Anti-repetición: 'calor' por color — sube cuando se muestra, decae con
        # el tiempo. Penaliza los colores usados recién → rotan, no dominan.
        self.heat: dict[str, float] = {c: 0.0 for c in grammar.all_colors()}
        self.reseed(seed_color)

    def tick(self, current: str) -> None:
        """El director lo llama cada frame con el color mostrado: sube su calor,
        enfría los demás (media vida ~4s)."""
        for c in self.heat:
            self.heat[c] *= 0.99975
        if current in self.heat:
            self.heat[current] += 0.004

    def _w(self, color: str) -> float:
        """Peso del mood × penalización por repetición (calor)."""
        mood = 1.0 if self.mood_weights is None else max(0.01, self.mood_weights.get(color, 1.0))
        return mood / (1.0 + 0.18 * self.heat.get(color, 0.0))

    def _pick(self, pool: list[str]) -> str:
        """Elige de `pool` ponderado por el mood (la clave)."""
        if not pool:
            return self.grammar.random_color()
        return random.choices(pool, weights=[self._w(c) for c in pool])[0]

    def reseed(self, seed_color: str | None = None) -> None:
        """Paleta nueva: siembra desde la CLAVE del mood, caminando fundibles
        para coherencia. El mood decide QUÉ colores; la gramática, que combinen."""
        first = seed_color or self._pick(self.grammar.all_colors())
        deck = [first]
        while len(deck) < 4:
            partners = [
                p
                for c in deck
                for p in self.grammar.fade_partners(c)
                if p not in deck
            ]
            if not partners:
                partners = [c for c in self.grammar.all_colors() if c not in deck]
            deck.append(self._pick(partners))
        self.principals: list[str] = deck[:3]
        self.incoming: str = deck[3]
        rest = [c for c in self.grammar.all_colors() if c not in deck]
        self.outgoing: str = self._pick(rest) if rest else first

    def pick(self, current: str, brusque: bool) -> str:
        """Siguiente color. Brusco = principales (+saliente raro);
        tranquilo = el entrante tiene más chance de audicionarse."""
        if not brusque and random.random() < 0.4:
            return self.incoming
        pool = [c for c in self.principals if c != current] or list(self.principals)
        if brusque and random.random() < 0.15 and self.outgoing != current:
            return self.outgoing
        # sesgo de dominancia: el cálido tiende a llevar el ritmo como base
        weights = [self.grammar.dominance(c) for c in pool]
        return random.choices(pool, weights=weights)[0]

    def promote(self) -> str:
        """El entrante entra a principales. El nuevo entrante lo elige el mood
        Y el auto-balance: prefiere un color DISTINTO de los principales (para
        que no se concentre en un tono) pero que combine — 'ya hay mucho de
        esto, metamos otro que mezcle con lo que la música indica'."""
        promoted = self.incoming
        self.outgoing = self.principals.pop(0)
        self.principals.append(promoted)
        candidates = [
            p
            for c in self.principals
            for p in self.grammar.fade_partners(c)
            if p not in self.principals and p != self.outgoing
        ]
        if candidates:
            weights = [
                self._w(c)
                * (0.3 + min(self.grammar._dist(c, p) for p in self.principals))
                for c in candidates
            ]
            self.incoming = random.choices(candidates, weights=weights)[0]
        else:
            self.incoming = self._pick(self.grammar.all_colors())
        return promoted
