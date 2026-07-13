"""Auto-bitácora de anomalías: el director conoce sus invariantes ("esto no
debería pasar") y cuando uno se rompe escribe una línea JSONL con el snapshot
de qué estaba haciendo. Para cazar bugs con contexto en vez de adivinar:
"hizo algo raro a la mitad de la rola" → grep del minuto en logs/anomalias.jsonl.
"""

import json
import os
import time


class AnomalyLog:
    def __init__(
        self,
        frame_rate: float,
        path: str | None = None,
        cooldown_seconds: float = 10.0,
        max_bytes: int = 5_000_000,
    ):
        if path is None:
            root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            path = os.path.join(root, "logs", "anomalias.jsonl")
        self.path = path
        self._fr = frame_rate
        self._cooldown = int(frame_rate * cooldown_seconds)
        self._max_bytes = max_bytes
        self._until: dict[str, int] = {}  # tipo → frame hasta el que calla
        self.last: str = ""  # último tipo reportado (para el ⚠️ del debug)
        self.last_frame: int = -(10**9)
        os.makedirs(os.path.dirname(self.path), exist_ok=True)

    def report(self, frame: int, kind: str, snapshot: dict) -> bool:
        """Reporta una anomalía (con cooldown por tipo). True si se escribió."""
        if frame < self._until.get(kind, 0):
            return False
        self._until[kind] = frame + self._cooldown
        self.last = kind
        self.last_frame = frame
        self._rotate_if_big()
        entry = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "tipo": kind, **snapshot}
        try:
            with open(self.path, "a") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass  # la bitácora nunca debe tirar el show
        return True

    def _rotate_if_big(self) -> None:
        try:
            if os.path.getsize(self.path) > self._max_bytes:
                os.replace(self.path, self.path + ".1")  # una generación basta
        except OSError:
            pass

    def reset(self) -> None:
        self._until.clear()
        self.last = ""
