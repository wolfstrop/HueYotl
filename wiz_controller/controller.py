import asyncio
import logging
import time

from .models import (
    RGBCommand,
    BrightnessCommand,
    SceneCommand,
    OnCommand,
    OffCommand,
)
from .protocol import WizProtocol

logger = logging.getLogger(__name__)

Command = RGBCommand | BrightnessCommand | SceneCommand | OnCommand | OffCommand


class WizController:
    def __init__(self, ip: str, port: int = 38899, update_hz: int = 20):
        self.protocol = WizProtocol(ip, port)
        self.update_hz = update_hz
        # maxsize=1: última orden gana. Con cola grande el consumidor (update_hz)
        # ejecuta comandos viejos → latencia de cientos de ms en sync musical.
        self._queue: asyncio.Queue[Command] = asyncio.Queue(maxsize=1)
        self._running = False
        self._task: asyncio.Task | None = None
        self._last_send = 0.0
        self._min_interval = 1.0 / update_hz

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._send_loop())
        logger.info(f"WizController started → {self.protocol.ip} @ {self.update_hz}Hz")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self.protocol.close()
        logger.info("WizController stopped")

    def send(self, command: Command) -> None:
        try:
            self._queue.put_nowait(command)
        except asyncio.QueueFull:
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(command)
            except (asyncio.QueueEmpty, asyncio.QueueFull):
                pass

    def send_rgb(self, r: int, g: int, b: int, brightness: int | None = None) -> None:
        self.send(RGBCommand(r=r, g=g, b=b, brightness=brightness))

    def send_brightness(self, brightness: int) -> None:
        self.send(BrightnessCommand(brightness=brightness))

    def send_scene(self, scene_id: int, speed: int | None = None) -> None:
        self.send(SceneCommand(scene_id=scene_id, speed=speed))

    def turn_on(self, brightness: int | None = None, kelvin: int | None = None) -> None:
        self.send(OnCommand(brightness=brightness, kelvin=kelvin))

    def turn_off(self) -> None:
        self.send(OffCommand())

    async def _send_loop(self) -> None:
        while self._running:
            try:
                command = await asyncio.wait_for(self._queue.get(), timeout=0.1)
            except asyncio.TimeoutError:
                continue

            now = time.monotonic()
            elapsed = now - self._last_send
            if elapsed < self._min_interval:
                await asyncio.sleep(self._min_interval - elapsed)

            try:
                await self._execute(command)
                self._last_send = time.monotonic()
            except asyncio.TimeoutError:
                # ON/OFF perdidos dejan el foco en el estado equivocado (apagado
                # tras un blackout, p.ej.) → UN reintento. RGB ya no llega aquí
                # (fire-and-forget) y el siguiente frame corrige solo.
                if isinstance(command, (OnCommand, OffCommand)):
                    try:
                        await self._execute(command)
                        self._last_send = time.monotonic()
                    except (asyncio.TimeoutError, Exception):
                        logger.warning("On/Off command lost (retry failed)")
                else:
                    logger.warning("Command timed out")
            except Exception as e:
                logger.warning(f"Command failed: {e}")

    async def _execute(self, command: Command) -> None:
        match command:
            case RGBCommand(r=r, g=g, b=b, brightness=brightness):
                await self.protocol.send_rgb(r, g, b, brightness)
            case BrightnessCommand(brightness=brightness):
                await self.protocol.send_brightness(brightness)
            case SceneCommand(scene_id=sid, speed=speed):
                await self.protocol.send_scene(sid, speed)
            case OnCommand(brightness=b, kelvin=k):
                await self.protocol.turn_on(b, k)
            case OffCommand():
                await self.protocol.turn_off()
