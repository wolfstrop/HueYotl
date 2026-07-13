import numpy as np


class RollingSTFT:
    """STFT rodante: ventana grande (resolución) avanzando con hop chico
    (reactividad). El FFT de 128 muestras tenía bins de 375Hz — miope para
    onsets musicales y ciego para tono; con ventana 1024 → bins de 47Hz.

    Expone por frame:
    - spectrum: magnitudes crudas (para quien las quiera)
    - bands: ~24 bandas logarítmicas 30Hz-16kHz (estilo Superflux)
    - centroid: centroide espectral normalizado 0-1 en escala log
      (0 = grave, 1 = agudo) — el "tono" de la mezcla
    """

    def __init__(
        self,
        window: int = 1024,
        hop: int = 128,
        sample_rate: int = 48000,
        n_bands: int = 24,
        fmin: float = 30.0,
        fmax: float = 16000.0,
    ):
        self.window = window
        self.hop = hop
        self.sample_rate = sample_rate
        self._buffer = np.zeros(window, dtype=np.float32)
        self._hann = np.hanning(window).astype(np.float32)
        self._freqs = np.fft.rfftfreq(window, 1.0 / sample_rate)

        # Bandas logarítmicas: bordes geométricos, garantizando ≥1 bin por
        # banda (abajo del espectro los bins de 47Hz son más anchos que
        # las bandas ideales)
        edges = np.geomspace(fmin, fmax, n_bands + 1)
        starts = np.searchsorted(self._freqs, edges[:-1])
        ends = np.searchsorted(self._freqs, edges[1:])
        band_slices: list[tuple[int, int]] = []
        prev_end = starts[0]
        for s, e in zip(starts, ends):
            s = max(s, prev_end)
            e = max(e, s + 1)
            band_slices.append((s, e))
            prev_end = e
        self.band_centers = np.array(
            [self._freqs[s:e].mean() for s, e in band_slices]
        )
        # reduceat vectorizado (el loop de slices en Python costaba ~0.8ms)
        self._band_starts = np.array([s for s, _ in band_slices])
        self._band_counts = np.array([e - s for s, e in band_slices], dtype=np.float64)
        self._band_last_end = band_slices[-1][1]

        self.spectrum = np.zeros(len(self._freqs))
        self.bands = np.zeros(len(self._band_starts))
        self.centroid = 0.0
        self._log_fmin = np.log(100.0)
        self._log_span = np.log(8000.0) - self._log_fmin
        # Centroide MELÓDICO: solo la banda media (voz/guitarra ~250Hz-2.5kHz),
        # sin bajos (batería/kick) ni agudos (platillos) → sigue la melodía real,
        # no la percusión. El full-mix se contamina con la batería en rock.
        self._mid_mask = (self._freqs >= 250.0) & (self._freqs <= 2500.0)
        self._mid_freqs = self._freqs[self._mid_mask]
        self._log_mid_lo = np.log(250.0)
        self._log_mid_span = np.log(2500.0) - self._log_mid_lo
        self.mid_centroid = 0.5
        # Tonalness de la banda media = CONFIANZA de que hay melodía real.
        # 1 - planitud espectral: un pico tonal claro (nota/voz) → ~1; ruido,
        # mezcla densa o percusión (espectro plano) → ~0. Distingue melodía de
        # batería/fondo, que es lo que el conductor necesita para dar prioridad.
        self.mid_tonalness = 0.0

    def process(self, chunk: np.ndarray) -> None:
        n = len(chunk)
        if n >= self.window:
            self._buffer[:] = chunk[-self.window:]
        else:
            self._buffer[:-n] = self._buffer[n:]
            self._buffer[-n:] = chunk

        self.spectrum = np.abs(np.fft.rfft(self._buffer * self._hann))
        sums = np.add.reduceat(self.spectrum[: self._band_last_end], self._band_starts)
        self.bands = sums / self._band_counts

        total = float(self.spectrum.sum())
        if total > 1e-9:
            centroid_hz = float((self._freqs * self.spectrum).sum() / total)
            centroid_hz = max(100.0, min(8000.0, centroid_hz))
            self.centroid = float(
                (np.log(centroid_hz) - self._log_fmin) / self._log_span
            )
        # sin señal: conservar el último centroide (evita saltos a 0)

        # centroide melódico (solo banda media)
        mid_spec = self.spectrum[self._mid_mask]
        mid_total = float(mid_spec.sum())
        if mid_total > 1e-9:
            mid_hz = float((self._mid_freqs * mid_spec).sum() / mid_total)
            mid_hz = max(250.0, min(2500.0, mid_hz))
            self.mid_centroid = float(
                (np.log(mid_hz) - self._log_mid_lo) / self._log_mid_span
            )
            # planitud = media geométrica / media aritmética ∈ [0,1] (AM-GM);
            # tonalness = 1 - planitud, suavizado ~0.1s para que sea legible/estable
            eps = 1e-9
            geo = float(np.exp(np.mean(np.log(mid_spec + eps))))
            ari = float(mid_spec.mean()) + eps
            ton_raw = 1.0 - geo / ari
            self.mid_tonalness += (ton_raw - self.mid_tonalness) * 0.03

    def reset(self) -> None:
        self._buffer[:] = 0
        self.spectrum = np.zeros(len(self._freqs))
        self.bands = np.zeros(len(self._band_starts))
        self.centroid = 0.0
        self.mid_centroid = 0.5
        self.mid_tonalness = 0.0
