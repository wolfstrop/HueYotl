import asyncio
import json

from pywizlight import PilotBuilder, wizlight


class WizProtocol:
    def __init__(self, ip: str, port: int = 38899):
        self.ip = ip
        self.port = port
        self._bulb = wizlight(ip, port)
        self._timeout = 0.5
        # Transporte UDP propio para el camino de 30Hz (fire-and-forget):
        # esperar la respuesta del foco bloqueaba el loop (~0.5s por timeout),
        # la cola last-wins descartaba lo intermedio y al recuperarse SALTABA
        # al estado más nuevo. A 30Hz no hace falta confirmación: el siguiente
        # frame corrige solo. ON/OFF sí se confirman (pywizlight).
        self._transport: asyncio.DatagramTransport | None = None

    async def _ensure_transport(self) -> asyncio.DatagramTransport:
        if self._transport is None or self._transport.is_closing():
            loop = asyncio.get_running_loop()
            self._transport, _ = await loop.create_datagram_endpoint(
                asyncio.DatagramProtocol, remote_addr=(self.ip, self.port)
            )
        return self._transport

    async def send_rgb(self, r: int, g: int, b: int, brightness: int | None = None) -> None:
        params: dict = {"r": r, "g": g, "b": b}
        if brightness is not None:
            # WiZ setPilot espera dimming 10-100 (pywizlight hacía este mapeo)
            params["dimming"] = max(10, min(100, round(brightness / 255 * 100)))
        transport = await self._ensure_transport()
        transport.sendto(
            json.dumps({"method": "setPilot", "params": params}).encode()
        )

    def close(self) -> None:
        if self._transport is not None and not self._transport.is_closing():
            self._transport.close()
        self._transport = None

    async def send_brightness(self, brightness: int) -> None:
        pilot = PilotBuilder(brightness=brightness)
        await asyncio.wait_for(self._bulb.turn_on(pilot), timeout=self._timeout)

    async def send_scene(self, scene_id: int, speed: int | None = None) -> None:
        pilot = PilotBuilder(scene=scene_id)
        if speed is not None:
            pilot = PilotBuilder(scene=scene_id, speed=speed)
        await asyncio.wait_for(self._bulb.turn_on(pilot), timeout=self._timeout)

    async def turn_on(self, brightness: int | None = None, kelvin: int | None = None) -> None:
        pilot = PilotBuilder()
        if brightness is not None:
            pilot = PilotBuilder(brightness=brightness)
        if kelvin is not None:
            pilot = PilotBuilder(brightness=brightness or 255, colortemp=kelvin)
        await asyncio.wait_for(self._bulb.turn_on(pilot), timeout=self._timeout)

    async def turn_off(self) -> None:
        await asyncio.wait_for(self._bulb.turn_off(), timeout=self._timeout)

    async def get_state(self) -> dict:
        state = await asyncio.wait_for(self._bulb.updateState(), timeout=self._timeout)
        return {
            "on": state.get_state(),
            "brightness": state.get_brightness(),
            "rgb": state.get_rgb(),
            "scene": state.get_scene(),
        }
