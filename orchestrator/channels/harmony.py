def _clamp01(x: float) -> float:
    return min(1.0, max(0.0, x))


class HarmonyChannel:
    """Sensor de armonía/timbre: temperatura lenta (~6s, frío↔cálido del
    centroide) + valence (mayor/menor del chroma) → la temperatura EFECTIVA
    que gobierna la clave de color del mood. Percepción pura.
    """

    def __init__(self, frame_rate: float):
        self._fr = frame_rate
        self.temperature = 0.5
        self.valence = 0.5
        self.temp_eff = 0.5

    def update(self, centroid: float, valence: float, valence_strength: float) -> float:
        self.temperature += (centroid - self.temperature) * (1.0 / (self._fr * 6.0))
        self.valence = valence
        # temperatura = timbre + EMPUJÓN emocional del modo (mayor→cálido/alegre,
        # menor→frío/triste). El chroma es crudo → peso ajustable en vivo.
        self.temp_eff = _clamp01(
            self.temperature + (valence - 0.5) * valence_strength
        )
        return self.temp_eff

    def reset(self) -> None:
        self.temperature = 0.5
        self.valence = 0.5
        self.temp_eff = 0.5
