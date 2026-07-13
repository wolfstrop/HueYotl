import asyncio
import logging

import numpy as np
import sounddevice as sd

from .pulse_detect import ensure_monitor_routing, find_monitor_source

logger = logging.getLogger(__name__)


class AudioCapture:
    def __init__(
        self,
        sample_rate: int = 48000,
        chunk_size: int = 256,
        channels: int = 1,
        device: str | None = None,
    ):
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self.channels = channels
        self.device = device or find_monitor_source()
        self._queue: asyncio.Queue[np.ndarray] = asyncio.Queue(maxsize=50)
        self._stream: sd.InputStream | None = None
        self._running = False
        self._stream_alive = False
        self._loop: asyncio.AbstractEventLoop | None = None

    async def start(self) -> None:
        if not self.device:
            self.device = find_monitor_source()
        if not self.device:
            raise RuntimeError(
                "No audio monitor source found. "
                "Make sure PulseAudio/PipeWire is running."
            )

        self._loop = asyncio.get_running_loop()
        self._running = True
        self._stream = sd.InputStream(
            device=self.device,
            samplerate=self.sample_rate,
            blocksize=self.chunk_size,
            channels=self.channels,
            dtype="float32",
            callback=self._audio_callback,
            finished_callback=self._on_stream_finished,
        )
        self._stream.start()
        self._stream_alive = True
        # El stream ya corre: verificar que quedó enchufado al monitor del
        # sistema y no al micrófono (stream-restore/plugin ALSA de PipeWire)
        ensure_monitor_routing()
        logger.info(f"AudioCapture started → {self.device}")

    async def stop(self) -> None:
        self._running = False
        self._stream_alive = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        logger.info("AudioCapture stopped")

    async def restart(self) -> None:
        await self.stop()
        self.device = None
        await self.start()

    @property
    def is_alive(self) -> bool:
        return self._stream_alive and self._stream is not None

    async def get_chunk(self) -> np.ndarray:
        return await self._queue.get()

    def _audio_callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info: object,
        status: sd.CallbackFlags,
    ) -> None:
        # Corre en el hilo de PortAudio: solo puede tocar el loop via
        # call_soon_threadsafe (asyncio.Queue no es thread-safe).
        if not self._running or self._loop is None:
            return

        if status:
            logger.warning(f"Audio stream status: {status}")

        chunk = indata[:, 0].copy() if indata.ndim > 1 else indata.copy()
        try:
            self._loop.call_soon_threadsafe(self._enqueue, chunk)
        except RuntimeError:
            # loop cerrado durante shutdown
            pass

    def _enqueue(self, chunk: np.ndarray) -> None:
        try:
            self._queue.put_nowait(chunk)
        except asyncio.QueueFull:
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(chunk)
            except (asyncio.QueueEmpty, asyncio.QueueFull):
                pass

    def _on_stream_finished(self) -> None:
        # PortAudio la llama cuando el stream muere (device desaparece, xrun fatal).
        self._stream_alive = False
        if self._running:
            logger.warning("Audio stream finished unexpectedly")

    def list_devices(self) -> list[dict]:
        devices = sd.query_devices()
        return [
            {"name": d["name"], "index": i, "channels": d["max_input_channels"]}
            for i, d in enumerate(devices)
            if d["max_input_channels"] > 0
        ]
