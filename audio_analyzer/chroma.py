"""¿La música suena MAYOR (alegre) o MENOR (triste)?

Estima el modo desde el audio vía CHROMA (12 clases de tono) + perfiles de
Krumhansl-Schmuckler. Salida: `valence` 0-1 (0 = menor/triste, 1 = mayor/alegre),
muy suavizada. CRUDO — 'aparentar' la emoción, no precisión de conservatorio.

Usa su propio buffer de 4096 muestras (bins ~12Hz: la ventana 1024 del STFT
tenía bins de 47Hz, muy gruesos para distinguir semitonos en los graves).
"""

import numpy as np

# Perfiles de tonalidad Krumhansl-Schmuckler (peso de cada grado de la escala)
_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


def _unit(v: np.ndarray) -> np.ndarray:
    v = v - v.mean()
    n = np.linalg.norm(v)
    return v / n if n > 1e-9 else v


class RollingChroma:
    def __init__(
        self,
        sample_rate: int = 48000,
        window: int = 4096,
        frame_rate: float = 375.0,
        every: int = 4,               # calcula el FFT cada N frames (barato; el modo es lento)
        chroma_tau_seconds: float = 1.5,
        valence_tau_seconds: float = 5.0,
        fmin: float = 110.0,
        fmax: float = 2000.0,
    ):
        self._window = window
        self._buf = np.zeros(window, dtype=np.float32)
        self._hann = np.hanning(window).astype(np.float32)
        self._every = max(1, every)
        freqs = np.fft.rfftfreq(window, 1.0 / sample_rate)
        with np.errstate(divide="ignore", invalid="ignore"):
            midi = 69.0 + 12.0 * np.log2(np.where(freqs > 0, freqs, 1.0) / 440.0)
        pc = np.round(midi).astype(int) % 12
        self._mask = (freqs > fmin) & (freqs < fmax)
        self._pc = pc[self._mask]
        self._chroma = np.zeros(12)
        rate = frame_rate / self._every  # tasa efectiva de actualización
        self._chroma_alpha = 1.0 / (rate * chroma_tau_seconds)
        self._valence_alpha = 1.0 / (rate * valence_tau_seconds)
        self.valence = 0.5
        # expuestos para el observatorio (Fase O): vector chroma unitario,
        # tónica estimada y cuántos frames lleva ESTABLE (la tensión armónica
        # solo vale con tónica firme)
        self.chroma = np.zeros(12)       # centrado+unitario (correlación/huellas)
        self.chroma_dist = np.zeros(12)  # distribución NO-negativa (tensión)
        self.tonic = -1
        self.tonic_frames = 0
        self._maj = np.array([_unit(np.roll(_MAJOR, k)) for k in range(12)])
        self._min = np.array([_unit(np.roll(_MINOR, k)) for k in range(12)])
        self._counter = 0

    def process(self, chunk: np.ndarray) -> float:
        n = len(chunk)
        if n >= self._window:
            self._buf[:] = chunk[-self._window:]
        else:
            self._buf[:-n] = self._buf[n:]
            self._buf[-n:] = chunk

        self._counter += 1
        if self._counter % self._every != 0:
            return self.valence

        spectrum = np.abs(np.fft.rfft(self._buf * self._hann))
        frame = np.zeros(12)
        np.add.at(frame, self._pc, spectrum[self._mask])
        total = frame.sum()
        if total > 1e-6:
            self._chroma += (frame / total - self._chroma) * self._chroma_alpha
        c = _unit(self._chroma)
        maj_corr = self._maj.dot(c)
        min_corr = self._min.dot(c)
        tonic = int(np.argmax(np.maximum(maj_corr, min_corr)))  # tónica más probable
        self.chroma = c
        self.chroma_dist = self._chroma / (self._chroma.sum() + 1e-9)
        if tonic == self.tonic:
            self.tonic_frames += self._every
        else:
            self.tonic = tonic
            self.tonic_frames = 0
        raw = 0.5 + 0.5 * float(np.tanh((maj_corr[tonic] - min_corr[tonic]) * 3.0))
        self.valence += (raw - self.valence) * self._valence_alpha
        return self.valence

    def reset(self) -> None:
        self._buf[:] = 0.0
        self._chroma[:] = 0.0
        self.valence = 0.5
        self._counter = 0
        self.chroma = np.zeros(12)
        self.chroma_dist = np.zeros(12)
        self.tonic = -1
        self.tonic_frames = 0
