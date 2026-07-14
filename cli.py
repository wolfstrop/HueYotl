"""HueYotl TUI — panel de control del foco en la terminal (estilo yazi).

    .venv/bin/python cli.py

Teclas: [o] on/off · [j/k] brillo ∓ · [↑↓ + enter] lanzar modo · [q] salir.
Con un modo corriendo, el pipeline es dueño del foco (los controles directos
se bloquean para no pelear por el UDP). Al salir, el modo se detiene.
"""

import asyncio
import os
import signal
import subprocess
import sys

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, Label, ListItem, ListView, Static

from config import Settings
from wiz_controller.protocol import WizProtocol

MODES = [
    ("♪ Reactivo — audio del sistema", ["-m", "orchestrator.main"], {}),
    ("🎤 Reactivo — MICRÓFONO (tele/bocinas)", ["-m", "orchestrator.main"], {"HUEYOTL_INPUT": "mic"}),
    ("🌙 Ambiente — colores suaves sin música", ["-m", "orchestrator.main", "--mode", "ambient"], {}),
    ("■ Detener modo", None, {}),
]


class HueYotlTUI(App):
    TITLE = "HueYotl 🐺"
    CSS = """
    #status { padding: 1 2; background: $boost; border: round $accent; margin: 1 2; }
    ListView { margin: 0 2; border: round $primary; height: auto; }
    ListItem { padding: 0 1; }
    """
    BINDINGS = [
        Binding("o", "toggle", "On/Off"),
        Binding("j", "dim_down", "Brillo −"),
        Binding("k", "dim_up", "Brillo +"),
        Binding("q", "quit", "Salir"),
    ]

    def __init__(self) -> None:
        super().__init__()
        settings = Settings()
        self.wiz = WizProtocol(settings.wiz.ip, settings.wiz.port)
        self.proc: subprocess.Popen | None = None
        self.mode_name = ""
        self._dim = 60  # 0-255, se sincroniza con el estado real al refrescar

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("conectando con el foco…", id="status")
        yield ListView(*(ListItem(Label(name)) for name, _, _ in MODES))
        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(3.0, self.refresh_status)
        self.call_later(self.refresh_status)

    # ------------------------------------------------------------- estado

    async def refresh_status(self) -> None:
        status = self.query_one("#status", Static)
        if self.proc is not None:
            if self.proc.poll() is None:
                status.update(f"[b]MODO ACTIVO:[/b] {self.mode_name}\n"
                              f"el pipeline es dueño del foco — [dim]controles directos bloqueados[/dim]")
                return
            self.proc = None  # el modo murió solo
        try:
            st = await self.wiz.get_state()
            on = "[green]● ON[/green]" if st["on"] else "[red]○ OFF[/red]"
            rgb = st.get("rgb") or ("-", "-", "-")
            self._dim = int((st.get("brightness") or self._dim))
            status.update(f"Foco: {on}   rgb{tuple(rgb)}   brillo {round(self._dim/255*100)}%")
        except Exception:
            status.update("[yellow]⚠ el foco no responde (¿WiFi/IP?)[/yellow]")

    def _blocked(self) -> bool:
        if self.proc is not None and self.proc.poll() is None:
            self.notify("Modo activo: detenlo primero (■)", severity="warning")
            return True
        return False

    # ----------------------------------------------------------- acciones

    async def action_toggle(self) -> None:
        if self._blocked():
            return
        try:
            st = await self.wiz.get_state()
            if st["on"]:
                await self.wiz.turn_off()
            else:
                await self.wiz.turn_on(brightness=self._dim)
        except Exception as e:
            self.notify(f"sin respuesta del foco: {e}", severity="error")
        await self.refresh_status()

    async def _set_dim(self, delta: int) -> None:
        if self._blocked():
            return
        self._dim = max(10, min(255, self._dim + delta))
        try:
            await self.wiz.send_brightness(self._dim)
        except Exception as e:
            self.notify(f"sin respuesta del foco: {e}", severity="error")
        await self.refresh_status()

    async def action_dim_down(self) -> None:
        await self._set_dim(-25)

    async def action_dim_up(self) -> None:
        await self._set_dim(+25)

    # -------------------------------------------------------------- modos

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        name, args, extra_env = MODES[event.list_view.index or 0]
        await self._stop_mode()
        if args is None:
            await self.refresh_status()
            return
        self.wiz.close()  # soltar nuestro socket UDP: el pipeline toma el foco
        env = {**os.environ, **extra_env}
        self.proc = subprocess.Popen(
            [sys.executable, *args],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.mode_name = name
        self.notify(f"lanzado: {name}")
        await self.refresh_status()

    async def _stop_mode(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.send_signal(signal.SIGINT)  # clean shutdown del pipeline
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None, self.proc.wait, 5
                )
            except Exception:
                self.proc.kill()
            self.notify("modo detenido")
        self.proc = None
        self.mode_name = ""

    async def action_quit(self) -> None:
        await self._stop_mode()
        self.exit()


if __name__ == "__main__":
    HueYotlTUI().run()
