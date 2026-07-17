"""MCP HueYotl — el foco y el tuning como herramientas para agentes (Lorika).

EL MCP MANDA: si un modo está corriendo (reactivo/gato/ambiente) y llega un
apagar_todo() o poner_color(), el modo se detiene con SIGINT limpio y el MCP
toma el foco. El TUI ya sabe detectar que "el modo murió solo".

Correr (stdio):
    .venv/bin/python mcp_server.py

Registrar en un agente (Claude Code):
    claude mcp add hueyotl -- <ruta>/.venv/bin/python <ruta>/mcp_server.py

PARA EXTENDER: agrega una función con @mcp.tool() y docstring en la sección
"AGREGA AQUÍ" — eso es todo, FastMCP arma el schema desde la firma.
"""

import asyncio
import colorsys
import os
import re
import signal
import subprocess

from mcp.server.fastmcp import FastMCP

from config import Settings
from config.nivel import escribir_nivel, leer_nivel
from notificar import COLOR_ALIAS, PRESETS_PATH, validar_spec
from rgb_mapper.grammar import ANCHORS
from wiz_controller.protocol import WizProtocol

ROOT = os.path.dirname(os.path.abspath(__file__))
TUNING_TOML = os.path.join(ROOT, "config", "tuning.toml")
# procesos que son dueños del foco (los que este MCP puede desalojar)
MODE_PATTERN = r"orchestrator\.main|modo_gato\.py|notificar\.py"

# knobs de tuning.toml expuestos: nombre → (min, max, descripción).
# Los bool/enum van aparte. El watcher del pipeline los relee en <1s → EN VIVO.
KNOBS: dict[str, tuple[float, float, str]] = {
    "dynamics_strength": (0.0, 1.0, "perilla maestra de dinámica (0 = fijo)"),
    "surge_threshold": (0.05, 0.6, "sensibilidad de métele/cálmate (↓ = más sensible)"),
    "mood_strength": (0.0, 1.0, "cuánto manda el mood la clave de color"),
    "melody_lead_bias": (0.0, 1.0, "cuánto lidera la melodía vs el ritmo"),
    "gesture_brightness": (0.0, 1.0, "cuánto destellan los golpes (0 = solo color)"),
    "valence_strength": (0.0, 1.0, "empuje mayor/menor → cálido/frío"),
    "keep_color_prob": (0.0, 1.0, "↑ repite más el mismo color"),
    "fatigue_seconds": (2.0, 30.0, "color pegado más de esto → refresco"),
    "palette_rotate_seconds": (4.0, 60.0, "cada cuánto entra color nuevo al pool"),
    "figure_max_seconds": (1.0, 10.0, "duración máxima de una figura"),
    "cut_prob": (0.0, 1.0, "prob de corte seco OFF→ON en staccato"),
    "punch_cooldown_seconds": (0.2, 5.0, "↓ = golpes de color más densos"),
    "ember_weight": (0.0, 5.0, "peso de EMBER (oscuros puros, el oro)"),
    "brightness_ceiling": (0.2, 1.0, "techo de brillo (↓ = show más oscuro)"),
    "brightness_dynamics": (0.0, 1.0, "cuánto respira el brillo con la dinámica"),
    "transition_sensitivity": (0.0, 1.0, "qué tan fácil cambia color al beat"),
    "swell_strength": (0.0, 1.0, "crecida en nota sostenida a todo pulmón"),
    "rhythm_dark": (0.0, 1.0, "pulsos de oscuridad cuando la melodía lidera"),
    "burst_drive": (0.0, 1.0, "umbral de ráfaga color-por-beat (1 = off)"),
    "luminance_comp": (0.0, 1.0, "iguala brillo percibido entre colores"),
    "veda_seconds": (0.0, 120.0, "cada cuánto se vetan colores (0 = off)"),
    "veda_duration": (5.0, 60.0, "duración de la veda"),
    "flash_intensity": (0.5, 1.0, "umbral del flash blanco (↑ = más raro)"),
    "flash_cooldown_seconds": (1.0, 15.0, "cooldown del flash"),
    "fade_seconds": (0.3, 3.0, "largo del fade lento en FLOW"),
    "latency_seconds": (0.0, 0.3, "lookahead predictivo de la luz"),
}
VIBES = ("auto", "fiesta", "chill", "rock", "hyperpop", "classical")

mcp = FastMCP("hueyotl")
_settings = Settings()
_proto: WizProtocol | None = None


def _bulb() -> WizProtocol:
    """Perezoso: pywizlight exige un event loop vivo al construirse."""
    global _proto
    if _proto is None:
        _proto = WizProtocol(_settings.wiz.ip, _settings.wiz.port)
    return _proto


def _find_modes() -> list[tuple[int, list[str]]]:
    """(pid, argv) de los procesos dueños del foco. El argv completo permite
    RESTAURAR el modo tal cual tras una notificación suave.

    pgrep -f solo filtra candidatos; se confirma leyendo /proc/<pid>/cmdline
    que sea UN PYTHON corriendo el modo — sin eso, cualquier shell cuyo
    cmdline mencione 'modo_gato.py' recibiría el SIGINT (pasó en pruebas:
    apagar_todo mató al propio harness de test)."""
    try:
        out = subprocess.run(
            ["pgrep", "-f", MODE_PATTERN], capture_output=True, text=True
        ).stdout
    except OSError:
        return []
    procs = []
    for pid_s in out.split():
        if not pid_s.isdigit() or int(pid_s) == os.getpid():
            continue
        pid = int(pid_s)
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as fh:
                args = [a for a in fh.read().decode(errors="replace").split("\0") if a]
        except OSError:
            continue
        if not args or "python" not in os.path.basename(args[0]):
            continue
        rest = args[1:]
        is_mode = any(a.endswith(("modo_gato.py", "notificar.py")) for a in rest) or (
            "orchestrator.main" in rest and "-m" in rest
        )
        if is_mode:
            procs.append((pid, args))
    return procs


def _describe(argv: list[str]) -> str:
    return " ".join(argv)


def _gone(pid: int) -> bool:
    """Muerto O zombie (ya salió, su padre no ha hecho wait — p.ej. el TUI
    tarda hasta 3s en revisar). os.kill(pid, 0) responde ok en zombies."""
    try:
        with open(f"/proc/{pid}/stat") as fh:
            return fh.read().split(") ", 1)[1][0] == "Z"
    except (OSError, IndexError):
        return True


async def _stop_modes() -> list[list[str]]:
    """SIGINT limpio a cada modo (apagan el foco al morir); SIGKILL si no.
    Devuelve los argv detenidos (para reportar o RESTAURAR)."""
    stopped = []
    for pid, argv in _find_modes():
        try:
            os.kill(pid, signal.SIGINT)
        except ProcessLookupError:
            continue
        for _ in range(25):  # hasta 5s de gracia
            await asyncio.sleep(0.2)
            if _gone(pid):
                break
        else:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        stopped.append(argv)
    return stopped


def _parse_color(color: str) -> tuple[int, int, int]:
    c = color.strip().lower()
    name = COLOR_ALIAS.get(c, c)
    if name in ANCHORS:
        r, g, b = colorsys.hsv_to_rgb(ANCHORS[name], 1.0, 1.0)
        return round(r * 255), round(g * 255), round(b * 255)
    if m := re.fullmatch(r"#?([0-9a-f]{6})", c):
        v = int(m.group(1), 16)
        return v >> 16, (v >> 8) & 255, v & 255
    if m := re.fullmatch(r"(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})", c):
        r, g, b = (min(255, int(x)) for x in m.groups())
        return r, g, b
    raise ValueError(
        f"color '{color}' no reconocido — usa un nombre ({', '.join(sorted(COLOR_ALIAS))}), "
        f"hex (#ff3700) o r,g,b (255,55,0)"
    )


# ------------------------------------------------------------------- FOCO

@mcp.tool()
async def apagar_todo() -> str:
    """PÁNICO/BUENAS NOCHES: detiene cualquier modo corriendo (reactivo,
    gato, ambiente) y apaga el foco. Siempre gana, aunque haya música."""
    stopped = await _stop_modes()
    try:
        await _bulb().turn_off()
    except Exception:
        await asyncio.sleep(0.5)          # reintento: UDP es UDP
        await _bulb().turn_off()
    msg = "foco apagado"
    if stopped:
        msg += " · modos detenidos: " + "; ".join(map(_describe, stopped))
    return msg


@mcp.tool()
async def poner_color(color: str, brillo: int = 60) -> str:
    """Pone el foco en un color específico. Si un modo está corriendo, lo
    detiene primero (el MCP manda). `color`: nombre en español o inglés
    (rojo, teal…), hex (#ff3700) o "r,g,b". `brillo`: 10-100 (%)."""
    r, g, b = _parse_color(color)
    brillo = max(10, min(100, brillo))
    stopped = await _stop_modes()
    bulb = _bulb()
    await bulb.send_rgb(r, g, b, brightness=round(brillo / 100 * 255))
    await asyncio.sleep(0.15)
    await bulb.send_rgb(r, g, b, brightness=round(brillo / 100 * 255))  # UDP x2
    msg = f"foco en rgb({r},{g},{b}) al {brillo}%"
    if stopped:
        msg += " · modo detenido antes: " + "; ".join(map(_describe, stopped))
    return msg


@mcp.tool()
async def prender(brillo: int = 60) -> str:
    """Prende el foco en blanco cálido. `brillo`: 10-100 (%)."""
    brillo = max(10, min(100, brillo))
    await _bulb().turn_on(brightness=round(brillo / 100 * 255), kelvin=2700)
    return f"foco prendido al {brillo}%"


@mcp.tool()
async def estado() -> str:
    """Estado real del foco (on/off, rgb, brillo) y qué modo corre."""
    modes = _find_modes()
    modo = "; ".join(_describe(a) for _, a in modes) if modes else "ninguno"
    try:
        st = await _bulb().get_state()
    except Exception as e:
        return f"el foco no responde ({e}) · modo corriendo: {modo}"
    on = "ON" if st["on"] else "OFF"
    dim = round((st.get("brightness") or 0) / 255 * 100)
    return f"foco {on} · rgb{tuple(st.get('rgb') or ())} · brillo {dim}% · modo corriendo: {modo}"


@mcp.tool()
async def detener_modo() -> str:
    """Detiene el modo que esté corriendo (sin apagar el foco)."""
    stopped = await _stop_modes()
    return ("detenido: " + "; ".join(map(_describe, stopped))) if stopped else "no había ningún modo corriendo"


@mcp.tool()
def listar_colores() -> str:
    """Colores con nombre disponibles (gramática del proyecto + alias)."""
    lines = [f"- {en} (hue {h:.2f})" for en, h in sorted(ANCHORS.items(), key=lambda kv: kv[1])]
    alias = ", ".join(f"{es}→{en}" for es, en in sorted(COLOR_ALIAS.items()))
    return "Colores:\n" + "\n".join(lines) + f"\nAlias en español: {alias}\nTambién: hex (#ff3700) o 'r,g,b'."


# ----------------------------------------------------------------- TUNING

@mcp.tool()
def listar_knobs() -> str:
    """Knobs de calibración del show (tuning.toml) con valor actual, rango
    y descripción. Los cambios aplican EN VIVO (<1s) si el show corre."""
    import tomllib
    with open(TUNING_TOML, "rb") as fh:
        data = tomllib.load(fh)
    flat: dict = {}
    for k, v in data.items():
        flat.update(v) if isinstance(v, dict) else flat.__setitem__(k, v)
    lines = []
    for name, (lo, hi, desc) in sorted(KNOBS.items()):
        cur = flat.get(name, "?")
        lines.append(f"- {name} = {cur}  [{lo}–{hi}]  {desc}")
    lines.append(f"- vibe = {flat.get('vibe', '?')}  [{'/'.join(VIBES)}]  ambiente musical forzado")
    lines.append(f"- blackout_total = {flat.get('blackout_total', '?')}  [true/false]  blackout apaga todo")
    return "\n".join(lines)


@mcp.tool()
def ajustar_knob(nombre: str, valor: str) -> str:
    """Ajusta un knob de tuning.toml (ver listar_knobs). Clampea al rango
    seguro. Aplica EN VIVO si el show está corriendo. `valor` como texto:
    "0.5", "true", "fiesta"."""
    if nombre == "vibe":
        if valor not in VIBES:
            return f"vibe inválido — opciones: {', '.join(VIBES)}"
        new = f'"{valor}"'
    elif nombre == "blackout_total":
        if valor.lower() not in ("true", "false"):
            return "blackout_total debe ser true o false"
        new = valor.lower()
    elif nombre in KNOBS:
        lo, hi, _ = KNOBS[nombre]
        try:
            v = float(valor)
        except ValueError:
            return f"'{valor}' no es un número"
        clamped = min(hi, max(lo, v))
        new = f"{clamped:g}"
        if clamped != v:
            new_note = f" (pediste {v:g}, clampeado al rango {lo}–{hi})"
        else:
            new_note = ""
    else:
        return f"knob '{nombre}' no existe o no está expuesto — usa listar_knobs"

    with open(TUNING_TOML) as fh:
        text = fh.read()
    pattern = rf"(?m)^({re.escape(nombre)}\s*=\s*)[^#\n]*"
    if re.search(pattern, text):
        text = re.sub(pattern, rf"\g<1>{new} ", text, count=1)
    else:
        text = text.rstrip() + f"\n{nombre} = {new}\n"
    with open(TUNING_TOML, "w") as fh:
        fh.write(text)
    note = new_note if nombre in KNOBS else ""
    return f"{nombre} = {new}{note} — aplica en <1s si el show corre"


# ------------------------------------------------------------------ MODOS

VENV_PY = os.path.join(ROOT, ".venv", "bin", "python")
MODOS = {
    "gato": ([VENV_PY, "modo_gato.py"], {}),
    "reactivo": ([VENV_PY, "-m", "orchestrator.main"], {}),
    "reactivo_mic": ([VENV_PY, "-m", "orchestrator.main"], {"HUEYOTL_INPUT": "mic"}),
    "ambiente": ([VENV_PY, "-m", "orchestrator.main", "--mode", "ambient"], {}),
}


@mcp.tool()
async def lanzar_modo(modo: str, nivel: int | None = None) -> str:
    """Lanza un modo de luz: "gato" (penumbra nocturna marea+vela),
    "reactivo" (sigue la música del sistema), "reactivo_mic" (micrófono,
    para tele/bocinas) o "ambiente" (luz para ver según la hora, con color).
    Detiene el modo anterior primero. `nivel`: iluminación global 10-160 (%),
    opcional — si no lo pasas, respeta el nivel vigente."""
    if modo not in MODOS:
        return f"modo '{modo}' no existe — opciones: {', '.join(MODOS)}"
    stopped = await _stop_modes()
    if nivel is not None:
        escribir_nivel(nivel / 100)
    args, extra_env = MODOS[modo]
    subprocess.Popen(
        args, cwd=ROOT, env={**os.environ, **extra_env},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,  # sobrevive si el MCP muere
    )
    msg = f"modo {modo} lanzado"
    if nivel is not None:
        msg += f" al {round(leer_nivel() * 100)}% de nivel global"
    if stopped:
        msg += " · detenido antes: " + "; ".join(map(_describe, stopped))
    return msg


@mcp.tool()
def nivel_global(porcentaje: int) -> str:
    """Iluminación GLOBAL en vivo (10-160%): todos los modos la respetan
    en <2s sin reiniciarse (gato, ambiente y reactivo escalan su brillo).
    100 = neutro. No aplica a colores fijos (ahí usa el brillo de poner_color)."""
    efectivo = escribir_nivel(porcentaje / 100)
    modes = _find_modes()
    vivo = f" — {len(modes)} modo(s) lo toman en <2s" if modes else " — sin modo corriendo, aplica al próximo"
    return f"nivel global: {round(efectivo * 100)}%{vivo}"


# ---------------------------------------------------------- NOTIFICACIONES

def _load_presets() -> dict:
    import json
    try:
        with open(PRESETS_PATH) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _mode_env(pid: int) -> dict:
    """Env relevante del modo (HUEYOTL_INPUT no viene en el cmdline y sin
    él un reactivo_mic restaurado volvería como reactivo normal)."""
    try:
        with open(f"/proc/{pid}/environ", "rb") as fh:
            pairs = fh.read().decode(errors="replace").split("\0")
    except OSError:
        return {}
    env = dict(p.split("=", 1) for p in pairs if "=" in p)
    return {k: env[k] for k in ("HUEYOTL_INPUT",) if k in env}


@mcp.tool()
async def notificar(nombre: str) -> str:
    """Avisa por el FOCO (ver listar_notificaciones): 'suave' pausa el modo
    actual, toca el efecto y LO RESTAURA tal cual; 'toma' desaloja el modo y
    SE QUEDA hasta que la paren (detener_modo/apagar_todo/otro modo).
    Presets: info, pendiente, alerta, despertador, cleo_comida…"""
    presets = _load_presets()
    if nombre not in presets:
        return f"notificación '{nombre}' no existe — hay: {', '.join(presets) or 'ninguna'}"
    try:
        spec = validar_spec(presets[nombre])
    except ValueError as e:
        return f"preset '{nombre}' inválido: {e}"

    if spec["prioridad"] == "toma":
        await _stop_modes()
        subprocess.Popen(
            [VENV_PY, "notificar.py", nombre], cwd=ROOT,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return (f"'{nombre}' tomó el foco y se queda hasta que la paren "
                f"(detener_modo, apagar_todo u otro modo)")

    # suave: capturar qué corre (argv + env) → parar → tocar → restaurar
    prev = [(argv, _mode_env(pid)) for pid, argv in _find_modes()]
    prev_state = None
    if not prev:
        try:
            prev_state = await _bulb().get_state()
        except Exception:
            prev_state = None
    await _stop_modes()
    proc = await asyncio.create_subprocess_exec(
        VENV_PY, "notificar.py", nombre, cwd=ROOT,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        await asyncio.wait_for(proc.wait(), timeout=120)
    except asyncio.TimeoutError:
        proc.terminate()

    if prev:
        for argv, env in prev:
            subprocess.Popen(
                argv, cwd=ROOT, env={**os.environ, **env},
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        return f"'{nombre}' tocada · restaurado: " + "; ".join(_describe(a) for a, _ in prev)
    if prev_state and prev_state.get("on") and prev_state.get("rgb"):
        r, g, b = (prev_state["rgb"] + (0, 0, 0))[:3] if isinstance(prev_state["rgb"], tuple) else prev_state["rgb"][:3]
        bright = prev_state.get("brightness") or 128
        await _bulb().send_rgb(int(r or 0), int(g or 0), int(b or 0), brightness=int(bright))
        return f"'{nombre}' tocada · foco devuelto a como estaba"
    try:
        await _bulb().turn_off()
    except Exception:
        pass
    return f"'{nombre}' tocada · foco apagado (así estaba)"


@mcp.tool()
def definir_notificacion(nombre: str, spec: str) -> str:
    """Crea o modifica un preset de notificación (¡dale forma, Lorika!).
    `spec` es JSON: {"patron": respiracion|latido|alternancia|amanecer,
    "colores": [1-2 nombres], "velocidad": lenta|media|rapida, "brillo":
    10-100, "prioridad": suave|toma, "ciclos": 1-20 (suave), "duracion":
    30-1800s (amanecer)}. Validado: no se puede crear un strobe."""
    import json
    if not re.fullmatch(r"[a-z0-9_]{1,30}", nombre):
        return "nombre inválido: minúsculas/números/guion_bajo, máx 30"
    try:
        parsed = validar_spec(json.loads(spec))
    except (ValueError, json.JSONDecodeError) as e:
        return f"spec inválida: {e}"
    presets = _load_presets()
    nuevo = nombre not in presets
    presets[nombre] = parsed
    with open(PRESETS_PATH, "w") as fh:
        json.dump(presets, fh, indent=2, ensure_ascii=False)
    return f"preset '{nombre}' {'creado' if nuevo else 'actualizado'}: {json.dumps(parsed, ensure_ascii=False)}"


@mcp.tool()
def listar_notificaciones() -> str:
    """Presets de notificación disponibles con su spec."""
    import json
    presets = _load_presets()
    if not presets:
        return "no hay presets — crea uno con definir_notificacion"
    return "\n".join(
        f"- {n}: {json.dumps(s, ensure_ascii=False)}" for n, s in presets.items()
    )


# ------------------------------------------------------------ AGREGA AQUÍ
# Nuevas herramientas: una función con @mcp.tool() y docstring. Ejemplo:
#
# @mcp.tool()
# async def lanzar_modo_gato() -> str:
#     """Arranca el modo gato en background."""
#     ...


if __name__ == "__main__":
    mcp.run()
