import logging
import os

logger = logging.getLogger(__name__)


def _capture_target() -> str | None:
    """Fuente objetivo de la captura: el monitor del sistema, o el MICRÓFONO
    si HUEYOTL_INPUT=mic (música sonando en la tele/bocinas externas)."""
    if os.environ.get("HUEYOTL_INPUT") == "mic":
        return _default_mic_source()
    return _default_sink_monitor()


def find_monitor_source() -> str | None:
    """Apunta la captura a la fuente objetivo (monitor del sistema, o el
    micrófono con HUEYOTL_INPUT=mic).

    sounddevice solo expone el device genérico "pulse"/"pipewire", que enruta
    a la *fuente por defecto* — PULSE_SOURCE fuerza el destino correcto.
    """
    monitor = _capture_target()
    if monitor:
        os.environ["PULSE_SOURCE"] = monitor
        logger.info(f"Capturing audio via {monitor}")

    try:
        import sounddevice as sd

        devices = sd.query_devices()
        # Preferir el device "pulse": su plugin SÍ respeta PULSE_SOURCE.
        # El plugin ALSA de PipeWire ("pipewire") la ignora y encima
        # stream-restore recuerda el ruteo viejo (p.ej. al micrófono).
        for wanted in ("pulse", "pipewire"):
            for d in devices:
                name = d["name"].lower()
                if d["max_input_channels"] > 0 and wanted in name:
                    logger.info(f"Audio source found: {d['name']}")
                    return d["name"]

        default_in = sd.default.device[0]
        if default_in >= 0:
            default_name = sd.query_devices(default_in)["name"]
            logger.info(f"Using default input: {default_name}")
            return default_name

        logger.warning("No input device found")
        return None

    except Exception as e:
        logger.warning(f"Audio detection failed: {e}")
        return None


def _default_sink_monitor() -> str | None:
    try:
        import pulsectl

        with pulsectl.Pulse("wiz-music-sync") as pulse:
            sink = pulse.server_info().default_sink_name
            if sink:
                return f"{sink}.monitor"
    except Exception as e:
        logger.warning(f"Could not resolve default sink monitor: {e}")
    return None


def _default_mic_source() -> str | None:
    """La fuente de entrada por defecto (micrófono), NUNCA un .monitor."""
    try:
        import pulsectl

        with pulsectl.Pulse("wiz-music-sync") as pulse:
            src = pulse.server_info().default_source_name
            if src and not src.endswith(".monitor"):
                return src
            # el default era un monitor: buscar la primera fuente real
            for s in pulse.source_list():
                if not s.name.endswith(".monitor"):
                    return s.name
    except Exception as e:
        logger.warning(f"Could not resolve default mic source: {e}")
    return None


def ensure_monitor_routing() -> bool:
    """Verifica a qué fuente quedó conectada NUESTRA captura y, si no es el
    monitor del sink por defecto, la mueve a la fuerza.

    Necesario porque el plugin ALSA de PipeWire ignora PULSE_SOURCE y
    stream-restore puede re-enchufarnos a otra fuente por historial.
    Respeta HUEYOTL_INPUT=mic (ahí el objetivo ES el micrófono).
    """
    monitor = _capture_target()
    if not monitor:
        return False
    try:
        import os

        import pulsectl

        pid = str(os.getpid())
        with pulsectl.Pulse("wiz-routing-check") as pulse:
            sources = {s.index: s.name for s in pulse.source_list()}
            for so in pulse.source_output_list():
                if so.proplist.get("application.process.id") != pid:
                    continue
                current = sources.get(so.source, "")
                if current == monitor:
                    logger.info(f"Capture routed correctly → {monitor}")
                    return True
                target = next(
                    (s for s in pulse.source_list() if s.name == monitor), None
                )
                if target is None:
                    logger.warning(f"Monitor source {monitor} not found")
                    return False
                pulse.source_output_move(so.index, target.index)
                logger.warning(
                    f"Capture was routed to {current or so.source} — moved to {monitor}"
                )
                return True
        logger.warning("Could not find our capture stream to verify routing")
        return False
    except Exception as e:
        logger.warning(f"Routing check failed: {e}")
        return False
