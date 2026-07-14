"""FASE O — el Observatorio: instrumentos de teoría musical que SOLO miden.

Tres instrumentos, cero efecto en la luz (eso viene después, con datos):
- TENSIÓN ARMÓNICA: dos señales candidatas (dominante+sensible vs tónica, y
  claridad tonal por el 5º coeficiente de Fourier del chroma). Solo válidas
  con tónica estable ≥2s.
- MEMORIA DE SECCIONES: huella por sección (chroma medio + energía + BPM);
  al cerrar una sección se compara contra las anteriores con distancia
  INVARIANTE AL TONO (12 corrimientos circulares — el truco de Goto para la
  modulación del último coro). "¿Ya viví esta sección?"
- CONTADOR DE FRASE: compás 1 anclado en eventos estructurales, grupos de 4.

Registra en logs/observatorio.jsonl para decidir umbrales con música real.
"""

import json
import os
import time

import numpy as np


class Observatory:
    def __init__(self, frame_rate: float, path: str | None = None):
        self._fr = frame_rate
        if path is None:
            root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            path = os.path.join(root, "logs", "observatorio.jsonl")
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # tensión (dos candidatas, suavizadas ~1s)
        self.tension = 0.0       # dominante+sensible vs tónica
        self.tension_f5 = 0.0    # 1 - claridad del círculo de quintas
        # memoria de secciones
        self._fp_acc = np.zeros(12)
        self._fp_n = 0
        self._fp_energy = 0.0
        self._fp_start = 0
        self._fingerprints: list[dict] = []
        self.section_id = -1     # huella actual (tras el último cierre)
        self.last_match = ""     # etiqueta para el debug: SEC#n(sim)
        # frase
        self._phrase_anchor = 0
        self.phrase_beat = 0
        self._last_log = 0

    # ------------------------------------------------------------- por frame

    def update(
        self,
        frame: int,
        chroma: np.ndarray,
        tonic: int,
        tonic_frames: int,
        energy: float,
        bpm: float,
        beat_count: int,
        section_change: bool,
    ) -> None:
        # B1 — tensión armónica (solo con tónica firme)
        if tonic >= 0 and tonic_frames > self._fr * 2:
            cT = chroma[tonic]
            cV = chroma[(tonic + 7) % 12]
            cL = chroma[(tonic + 11) % 12]
            t_raw = (cV + cL) / (cT + cV + cL + 1e-9)
            F = np.abs(np.fft.rfft(chroma))
            f5_raw = 1.0 - F[5] / (F[1:].sum() + 1e-9)
            a = 1.0 / (self._fr * 1.0)
            self.tension += (float(t_raw) - self.tension) * a
            self.tension_f5 += (float(f5_raw) - self.tension_f5) * a

        # A1 — acumular huella de la sección en curso
        self._fp_acc += chroma
        self._fp_n += 1
        self._fp_energy += energy

        # C1 — frase: compás 1 anclado al último evento estructural
        self.phrase_beat = (beat_count - self._phrase_anchor) % 16

        if section_change:
            self._close_section(frame, bpm)
            self._phrase_anchor = beat_count

        # bitácora periódica (~cada 2s)
        if frame - self._last_log >= self._fr * 2:
            self._last_log = frame
            self._log({
                "t": round(frame / self._fr, 1), "tipo": "estado",
                "tension": round(self.tension, 3),
                "tension_f5": round(self.tension_f5, 3),
                "frase": self.phrase_beat, "sec": self.section_id,
            })

    # ------------------------------------------------------------- secciones

    def _close_section(self, frame: int, bpm: float) -> None:
        dur = (frame - self._fp_start) / self._fr
        acc, n, e = self._fp_acc, self._fp_n, self._fp_energy
        self._fp_acc = np.zeros(12)
        self._fp_n = 0
        self._fp_energy = 0.0
        self._fp_start = frame
        if n < self._fr * 8:  # sección muy corta: no es huella confiable
            return
        vec = acc / n
        norm = np.linalg.norm(vec)
        if norm < 1e-9:
            return
        vec = vec / norm
        fp = {"vec": vec, "energy": e / n, "bpm": bpm, "dur": dur,
              "id": len(self._fingerprints)}
        best_sim, best_id = 0.0, -1
        for old in self._fingerprints:
            # invariante al TONO: máximo coseno sobre los 12 corrimientos
            sim = max(float(np.dot(np.roll(vec, k), old["vec"])) for k in range(12))
            # compuertas suaves de energía y tempo
            if abs(old["energy"] - fp["energy"]) > 0.25:
                sim *= 0.8
            if bpm > 0 and old["bpm"] > 0 and abs(old["bpm"] - bpm) / old["bpm"] > 0.12:
                sim *= 0.8
            if sim > best_sim:
                best_sim, best_id = sim, old["id"]
        self._fingerprints.append(fp)
        if best_sim >= 0.90:
            self.section_id = best_id
            self.last_match = f"SEC#{best_id}({best_sim:.2f})"
        else:
            self.section_id = fp["id"]
            self.last_match = f"sec{fp['id']}nueva"
        self._log({
            "t": round(frame / self._fr, 1), "tipo": "seccion",
            "id": fp["id"], "match": best_id if best_sim >= 0.90 else None,
            "sim": round(best_sim, 3), "dur": round(dur, 1),
            "energia": round(fp["energy"], 3), "bpm": round(bpm, 1),
        })

    def _log(self, entry: dict) -> None:
        try:
            with open(self.path, "a") as fh:
                entry["ts"] = time.strftime("%H:%M:%S")
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def reset(self) -> None:
        self.__init__(self._fr, self.path)
