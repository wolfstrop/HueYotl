# HueYotl

> *La esencia del hue. El dios viejo de la música y la danza, viviendo en un foco.*

por **WOLFSTROP**

**Hue** (el tono de color que este director emite frame a frame) + **-yotl**
(sufijo náhuatl de esencia, como en *mexicayotl*) + un guiño a
**Huehuecóyotl**, el coyote azteca de la música, la danza y el desmadre.

Visualizador musical en tiempo real para focos WiZ RGB. No es un VU-meter:
es un **director de iluminación** — extrae ritmo, melodía, armonía y energía
del audio del sistema y decide *gestos* de luz (figuras, acentos, apagones,
swells) como lo haría un operador de consola en un show en vivo.

Sin APIs externas ni pre-análisis: va ciego, en vivo, contra lo que suene.

## Origen

Compré un foco RGB y el modo "music flow" de la app se veía horrible. Esto es
lo que debió ser. Construido a puro **vibe coding**, calibrado durante días de sesiones reales. 
Jurado calibrador: Enjambre en vivo, Soda Stereo, Los Bunkers, 
Juan Gabriel, salsa, metal, Pink Floyd y la meta fundacional: 
que aguantara a **MUSE**.

## Qué lo hace distinto

Los visualizadores típicos mapean bandas→colores (bass=rojo, treble=azul).
Aquí hay dos capas más arriba:

1. **Canales sensores con confianza** — cada aspecto musical lo percibe un
   módulo que reporta su lectura Y qué tan seguro está:
   - **Melodía**: contorno del centroide melódico (banda media, sin batería)
     en 3 escalas de tiempo + *tonalness* (¿hay melodía real o es ruido?)
     + *actividad* (¿se mueve o es una nota sostenida?)
   - **Beat**: tempo por PLL (BPM, fase, regularidad) + densidad de onsets
   - **Armonía**: tonalidad mayor/menor (chroma + perfiles de Krumhansl)
     → valence; temperatura tímbrica lenta → la *clave de color* del mood
   - **Energía**: rango adaptativo por percentiles, envolvente de brillo,
     detección de secciones
2. **Conductor + Director** — el conductor arbitra **quién lidera el gesto**
   (melodía ↔ beat) por confianzas con histéresis; si nadie está claro,
   *fallback*: respirar en el mood en vez de saturar. El director convierte
   eso en gestos.

## Gestos (lo que se ve)

| Gesto | Cuándo |
|---|---|
| Figuras (SHADOW/BREATHE/BOUNCE/STEPS/PULSE/EMBER) | base del GROOVE, 1-4 compases, cuantizadas al beat |
| Deriva orgánica con inercia (FLOW) | pasajes melódicos; el pitch acelera/frena |
| Ráfaga color-por-beat | el ritmo grita → color seco ciclando la tríada |
| Pulsos de oscuridad | la melodía lidera → el beat golpea en el eje OSCURO (no compiten por brillo) |
| Swell | nota sostenida a todo pulmón → el brillo crece mientras dura |
| Golpe con cola | snap al color de acento + regreso difuminado |
| Alto en seco | la música se corta → la luz corta YA; al volver, reanuda con golpe |
| Blackout de sección | cambio fuerte → oscuridad total → estallido en contraste |
| Breakdown | voz sola, música callada → hush dramático |

**Color**: gramática de anclas con pares fundibles/de corte (datos editables,
calibrados viendo el foco) + un deck vivo de 5 colores sembrado por el mood
(temperatura × profundidad × valence) con anti-repetición. Toda selección de
color pasa por los pesos del mood — medido con histogramas (en un mood
frío-oscuro el ámbar cayó de 26% a 3% del tiempo en pantalla).

**Brillo**: sigue la dinámica musical (intensidad + crescendo), no los
golpes; compensación de **luminancia percibida** entre hues (a mismo dimming
el verde se ve ~5× más brillante que el azul); limitador anti-estroboscópico
de seguridad que no se puede apagar por config.

## Hardware (lecciones del foco WiZ, probadas)

- El firmware **funde el RGB internamente**: un snap de color se ve suave.
  El único corte seco real es OFF→ON (`state:off` → encender ya en el color
  nuevo) — y al encender destella blanco, así que se usa poco y con reja.
- Saturación siempre 1.0: cualquier componente acromática enciende los LEDs
  blancos del foco.
- Se manda a 30 Hz por UDP *fire-and-forget* (cola last-wins; esperar la
  respuesta del foco bloquea y produce saltos). ON/OFF sí se confirman con
  reintento. No subir el rate: inundar de UDP cuelga el firmware.
- El director corre a 375 fps y el foco ve ~30 → todo efecto dura ≥130 ms
  para sobrevivir la decimación.

## Instalación y uso

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# editar config/settings.py → wiz.ip (la IP de tu foco en la LAN)

.venv/bin/python -m orchestrator.main            # reactivo (default)
.venv/bin/python -m orchestrator.main --debug    # + línea de estado en vivo
.venv/bin/python cli.py                          # TUI (lanzar modos, on/off, nivel)
```

Requisitos: Python 3.11+, PulseAudio/PipeWire (captura del monitor del
sistema), foco WiZ en la misma red.

## Modos

| Modo | Qué hace |
|---|---|
| ♪ **Reactivo** | el show completo (audio del sistema; `HUEYOTL_INPUT=mic` para micrófono) |
| 🐈 **Gato** (`modo_gato.py`) | penumbra nocturna sin música: marea+vela, rojo profundo de base (los gatos casi no ven el rojo), deriva lenta con sabor |
| ☀ **Ambiente** | luz circadiana PARA VER (neutro de día, vela de noche) + lavado de color continuo y brisas |
| 🔔 **Notificaciones** (`notificar.py`) | avisos por el foco: `info`, `pendiente`, `alerta`, `despertador` (amanecer 5 min), presets custom |

**Nivel global**: una perilla de iluminación (10-160%) que TODOS los modos
respetan en vivo — `j`/`k` en el TUI o `nivel_global()` por MCP.

## MCP — el foco como herramienta de agentes

`mcp_server.py` (FastMCP, stdio) expone 13 tools: `apagar_todo`,
`poner_color`, `lanzar_modo`, `nivel_global`, `notificar` /
`definir_notificacion` (los agentes crean sus propios avisos, validados —
imposible crear un strobe), y `ajustar_knob` — las 26 perillas de
`tuning.toml` calibrables EN VIVO por un agente mientras suena la música.
Prioridad: el MCP manda — desaloja al modo que corra (SIGINT limpio).
Remoto sin abrir puertos: `ssh servidor "python mcp_server.py"` como
comando stdio del cliente MCP.

## Modo distribuido (snapcast)

HueYotl puede correr en un servidor de la LAN (mejor latencia al foco) con
[snapcast](https://github.com/snapcast/snapcast) como bus de audio:
**librespot** (Spotify Connect) y **shairport-sync** (AirPlay) como fuentes
del snapserver → un snapclient local toca en un sink virtual
(`hueyotl_bus`) → el reactivo captura su monitor. El celular manda play
por Connect, un iPhone 4 de 2010 manda AirPlay, la luz baila en el cuarto y
el audio suena sincronizado en cualquier snapclient (PC, Android, sala).

## Calibración EN VIVO

`config/tuning.toml` se relee cada ~0.5 s mientras corre: edita, guarda y el
foco cambia sin reiniciar. Perillas principales:

| Perilla | Qué mueve |
|---|---|
| `dynamics_strength` | maestra: 0 = fijo, 1 = dinámica completa |
| `mood_strength` / `valence_strength` | cuánto manda la clave de color / el modo mayor-menor |
| `melody_lead_bias` | cuánto deciden las confianzas quién lidera |
| `brightness_ceiling` / `brightness_dynamics` | techo de brillo / cuánto respira con la frase |
| `rhythm_dark` / `gesture_brightness` | pozos de oscuridad del beat / brillo de los golpes |
| `burst_drive` / `swell_strength` | ráfaga color-por-beat / build en nota sostenida |
| `luminance_comp` | igualar brillo percibido entre colores |

## Arquitectura

```
audio_capture → audio_analyzer ─┬→ channels (melodía/beat/armonía/energía)
      (Pulse)   (STFT, onsets,  │        │ lecturas + confianzas
                 chroma, tempo) │        ▼
                                │   conductor (arbitraje + fallback)
                                │        ▼
                                └→  director (gestos) → rgb_mapper → safety → wiz_controller
                                                         (render)    (anti-    (UDP 30Hz)
                                                                      estrobo)
```

`wiz_controller` es independiente: se puede usar directo sin el pipeline.

## Estado

Funcional y en calibración activa contra oídos/ojos reales (rock, salsa,
banda, electrónica; la meta fundacional — aguantar a MUSE — se cumplió).
Sin suite de tests formal — la verificación es simulación sintética por
pieza + prueba de oído. Pendientes conocidos: seguimiento de guitarra a
destiempo, saltos secos de tempo (metal/prog), lookahead leyendo el buffer
del snapserver (luz anticipada al beat), gestos desde el Observatorio
(tensión armónica/secciones/frase), multi-foco por roles.

## Licencia

GPL-3.0 — © 2026 GUAZUX. Úsalo, aprende de él, compártelo; si lo
distribuyes modificado, abre tu código igual.
