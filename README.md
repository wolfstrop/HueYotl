# WiZ Music Sync

Sistema modular para controlar focos WiZ RGB con audio en tiempo real.

## Arquitectura

```
┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ Audio Capture│→ │Audio Analyzer│→ │  RGB Mapper  │→ │WiZ Controller│
│  (capture)   │  │  (fft/bands) │  │ (hue+mood)   │  │   (bulb)     │
└──────────────┘  └──────┬───────┘  └──────▲───────┘  └──────────────┘
                         │   ┌──────────┐  │
                         └──→│ Director │──┘
                             │ (mood)   │
                             └──────────┘
```

Módulos desacoplados. El WiZ Controller es independiente y reutilizable.

El **Music Director** es el cerebro. Elige UNA jugada según el carácter
musical (TempoTracker: PLL que predice beat, BPM, confianza y regularidad)
y la sostiene mínimo `move_min_seconds`:

| Jugada | Cuándo | Qué hace |
|--------|--------|----------|
| `FLOW` | suave, melódico, sin beat confiable | deriva orgánica con INERCIA por caminos de la gramática; el pitch acelera/frena, el onset da una patada |
| `GROOVE` | beat confiable o denso (rock) | corredor de FIGURAS (abajo) |
| `MONO` | fuerte pero caótico | un color puro profundo respirando |
| `BLACKOUT` | cambio de sección con energía | oscuridad breve → estallido con color de contraste |
| `FLASH` | golpes fuertes en partes altas | pulso blanco deliberado |

**Tres capas** (la figura es la base; encima van acentos y puntuación):

1. **Base (figura)**: 2 colores limpios + ritmo de brillo. SHADOW
   (color↔sombra azulada), BREATHE (respiración), BOUNCE (A↔B con dip de
   oscuridad en el cruce), STEPS (degradado en saltos discretos), PULSE
   (color fijo + golpe al beat). Corren 2-3 compases y rotan. Cambios
   discretos SOLO en beats (cuantización por construcción). El fundido
   entre pares SOLO vive en FLOW; en GROOVE los cambios de base **cortan
   en seco** (`cut_from`, sin untar el salto).
2. **Acentos (golpe de color)**: un onset fuerte en el beat (kick/tambor)
   trae el **tercer color** (`grammar.accent_for` — el que funde con ambos,
   el verde-naranja-**morado**) por un instante y regresa en seco. Con
   cooldown: es un puñetazo, no una rotación.
3. **Puntuación (corte OFF→ON)**: el foco WiZ FUNDE el RGB internamente
   (firmware, no se apaga por parámetro — probado), así que un "snap" por
   RGB directo se ve suave. El corte seco de verdad se logra **apagando el
   foco (`state:off`) y encendiéndolo ya en el color nuevo** — rompe el
   fade del firmware. Se usa en cambios de base y en el estallido tras una
   sección. Con reja de tiempo — muchos seguidos marean.

> **Hardware:** se manda a 30 Hz (cola last-wins). El director corre a
> 375 fps → el foco solo ve ~30 frames/seg. Todo efecto debe durar
> ≥~130 ms para sobrevivir esa decimación (la textura de gamma usa pasos
> de ~140 ms por eso). No subir el rate: inundar de UDP cuelga el firmware.

**Breakdown / respiro**: cuando la energía cae fuerte pero sigue habiendo
voz (medios) — el cantante solo, la música se calla — el brillo baja a un
hush dramático; al volver la energía, florece.

**Textura de gamma**: en figuras sostenidas de energía media, micro-saltos
discretos de gamma en el mapper = shimmer de brillo sin tocar el color.

**Bus de acentos unificado**: los cuatro golpes de color (MOTIVO, PUNCH,
STAB, ACCENT de guitarra) pasan por UN bus con prioridad —un color de golpe
a la vez, el motivo (doble-golpe = siempre el mismo color) no lo pisa nadie.
Precedencia global: micro-apagón > BLACKOUT > crossfade > bus de acentos >
figura. El flash se calla durante el micro-apagón (si no, lo anularía).

La **gramática de color** (`rgb_mapper/grammar.py`) define qué combina:
colores ancla con nombre, pares fundibles, pares de corte y colores MONO.
Son datos editables — calibrar viendo el foco.

El **ColorDeck** (`rgb_mapper/deck.py`) es la paleta viva: 3 principales +
1 entrante + 1 saliente. Lo brusco juega entre principales (repetir el
mismo color con sombra también vale), lo tranquilo audiciona al entrante,
y en fronteras de frase tranquilas el entrante se promueve — la paleta
rota caminando el grafo de la gramática.

El **Improviser** (`orchestrator/improviser.py`) responde a lo que el plan
no vio: picos de energía (bump de brillo), síncopas/fills fuera de la fase
predicha (stab de color breve) y predicción cayéndose (replan). Todo con
cooldowns — improvisar no es alocarse.

El **RGB Mapper** solo renderiza: saturación siempre 1.0 (LEDs blancos del
foco apagados salvo flash) y brillo via dimming, nunca horneado en el RGB.
El **WiZ Controller** es independiente: un CLI o app móvil puede usarlo
directo sin nada del pipeline de audio.

## Instalación

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Uso

```bash
# Modo reactive (audio en tiempo real, default)
.venv/bin/python -m orchestrator.main

# Modo ambient (colores suaves)
.venv/bin/python -m orchestrator.main --mode ambient

# Visualización de bandas en terminal
.venv/bin/python -m orchestrator.main --debug
```

## Configuración

Editar `config/settings.py`:

- `wiz.ip`: IP del bulbo WiZ
- `wiz.update_hz`: Frecuencia de actualización (default: 30)
- `audio.idle_timeout`: Segundos sin audio antes de entrar en idle (default: 5)
- `director.shadow_dim`: Qué tan oscuro es el estado sombra (default: 0.18)
- `director.play_prob_fast/slow`: Cuánto juega la sombra según tempo
- `director.fade_seconds`: Duración de los crossfades entre pares (default: 1.5)
- `director.step_intensity`: Qué tan fuerte debe ser un beat para contar (default: 0.35)
- `director.section_delta`: Sensibilidad de detección de secciones (default: 0.35)
- `director.flash_enabled`: Flash blanco en golpes fuertes (default: True)

## Módulos

| Módulo | Descripción |
|--------|-------------|
| `wiz_controller` | Servicio de control del bulbo (independiente) |
| `audio_capture` | Captura de audio via PulseAudio/PipeWire, con auto-restart |
| `audio_analyzer` | FFT, bandas de frecuencia, onset por spectral flux |
| `rgb_mapper` | Renderista puro: ColorDecision → RGB + dimming |
| `orchestrator` | Pipeline, Music Director (cerebro del color), modos |

## Resiliencia

- Si el stream de audio muere (reproductor cerrado, device desaparece), el
  pipeline entra en modo idle (luz tenue) y reintenta el stream cada 2s.
- Al volver el audio, retoma el modo reactive automáticamente.
- Ctrl+C hace clean shutdown de audio y controller.

## Requisitos

- Python 3.11+
- PulseAudio o PipeWire
- Foco WiZ configurado en la misma red
