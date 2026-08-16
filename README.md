# F.R.I.D.A.Y OS

Asistente por voz con memoria en markdown enlazado, HUD tipo terminal y motor
intercambiable. Corre en tu equipo. El audio no sale de aquí.

```
  tu voz ─▶ PTT ─▶ STT local ─▶ Router ─▶ Skill ─▶ vault/*.md ─▶ TTS local ─▶ bocinas
                                   │                  │                │
                                   └──────────── HUD (websocket) ──────┘
```

---

## Arranque

```powershell
.\scripts\setup.ps1     # venv + dependencias + modelo de voz (una vez)
.\scripts\run.ps1       # voz + HUD
```

El HUD abre solo en `http://127.0.0.1:8787`, en ventana de app sin pestañas.
**Mantén ESPACIO y habla.** Suelta y FRIDAY trabaja.

| Comando | Qué hace |
|---|---|
| `.\scripts\run.ps1` | todo: voz + HUD |
| `.\scripts\run.ps1 -NoVoice` | solo HUD, escribes en vez de hablar |
| `.\scripts\run.ps1 -NoHud` | solo consola |
| `.\scripts\run.ps1 -Check` | diagnóstico de dependencias |
| `.\scripts\run.ps1 -Say "dame las metricas"` | una petición y sale |

---

## Las 5 skills

FRIDAY enruta sola. No hay que invocarlas por nombre.

| Skill | Para qué | Se dispara con |
|---|---|---|
| **metricas** | jala números: CPU/RAM/disco + métricas del vault | *"dame las métricas"*, *"cómo va el equipo"* |
| **inbox** | resumen matutino: qué cayó, qué quedó abierto | *"buenos días"*, *"ponme al día"* |
| **plan** | escribe el top 3 del día y lo fija | *"arma el plan"*, *"por dónde empiezo"* |
| **vault** | lee y escribe memoria | *"recuerda que…"*, *"qué sabes de…"* |
| **agenda** | qué viene en los próximos 7 días | *"qué tengo hoy"*, *"agéndame…"* |

El enrutado tiene dos caminos: **rápido** (regex, 0 ms, sin motor) y **pensado**
(el motor clasifica). Nombrar la skill gana siempre — *"…en la **agenda**"* va a
`agenda` aunque la frase también suene a `inbox`.

### Métricas desde tus notas

Cualquier nota puede aportar números, con frontmatter o en línea:

```markdown
---
metric: 12
---
velocidad:: 12 pts
bugs abiertos:: 7
```

---

## La memoria: solo archivos

Sin base de datos. Sin índice que se corrompa. Sin formato propietario.
Si borras FRIDAY, tus notas siguen ahí y las abre cualquier editor de texto.

```
vault/
├── raw/        captura cruda — nota diaria, transcripciones de voz
├── wiki/       notas atómicas enlazadas con [[wikilinks]] → el grafo
└── outputs/    lo que FRIDAY produce — Briefing, Plan, resúmenes
```

**Abrir en Obsidian:** *Open folder as vault* → elige `FRIDAY-OS/vault`.
El grafo aparece solo, sin plugins. Ya viene con tema oscuro y wikilinks
configurados en `vault/.obsidian/`.

El grafo se construye en memoria al vuelo leyendo los `[[enlaces]]`. Da
backlinks, vecinos, huérfanas y enlaces rotos. Di **"reparar grafo"** y crea
stubs para todo enlace roto: la memoria se cierra sola.

---

## Voz: por qué es privada de verdad

- **STT** — `faster-whisper` en tu CPU/GPU. El modelo se baja **una vez** y de ahí
  es offline.
- **TTS** — Piper (ONNX local) o las voces SAPI5 de Windows. Ninguna llama a nadie.
- **PTT** — hotkey global, el audio vive en RAM y se descarta al transcribir.

Y no te pedimos que confíes en la palabra: mientras el pipeline de audio corre,
`core/privacy.py` intercepta `socket.connect` y **revienta cualquier conexión que
no sea loopback**. Si una dependencia intentara mandar tu voz a algún lado, lo ves
en el HUD como error. La prueba de humo lo verifica, incluso entre hilos.

Primera vez, para permitir la descarga del modelo:

```powershell
.\.venv\Scripts\python friday.py --allow-model-download
```

---

## El motor es intercambiable

Una línea en `config/friday.toml`:

```toml
[engine]
backend = "claude_code"   # claude_code | ollama | openai_compat
```

| Backend | Para qué |
|---|---|
| `claude_code` | Claude Code headless. El más capaz. |
| `ollama` | cualquier modelo local de Ollama |
| `openai_compat` | llama.cpp server, LM Studio, vLLM, text-generation-webui |

Con `claude_code`, FRIDAY lo corre **sin herramientas** (`--tools ""`) y con su
propio system prompt: un LLM puro, entra texto y sale texto. Los archivos los
escribe FRIDAY en Python. Así el motor no puede tocar tu vault por accidente, y
cambiarlo por un modelo local no rompe nada.

> Nota Windows: el prompt viaja por **stdin**, no por argv. El shim `.CMD` de npm
> destroza los argumentos largos con saltos de línea.

---

## El HUD

Una sola pantalla. Sin pestañas. Sin menús.

- **vitales** — CPU / RAM / disco en anillos, uptime, batería, red
- **audio i/o** — nivel en vivo, forma de onda, estado del PTT
- **comandos** — atajos clicables
- **salida** — la respuesta en markdown, con `[[enlaces]]` clicables que consultan el vault
- **transcripción** — lo que dijiste y lo que contestó, con hora
- **agenda** — próximos 7 días, vencidos en rojo
- **vault** — notas, enlaces, tags, palabras y el grafo dibujado
- **skills** — se encienden cuando se usan

Temas: `amber` (default), `cyan`, `ice` en `[hud] theme`.
También puedes escribir en vez de hablar: la barra de abajo acepta texto.

---

## Estructura

```
FRIDAY-OS/
├── friday.py           orquestador
├── config/
│   ├── friday.toml     TODA la configuración
│   └── persona.md      tono de FRIDAY (no formato)
├── core/
│   ├── bus.py          pub/sub asíncrono — nadie importa a nadie
│   ├── config.py       carga del toml
│   ├── engine.py       adaptadores: claude_code | ollama | openai_compat
│   ├── router.py       enrutado rápido + pensado
│   └── privacy.py      candado de red del audio
├── memory/
│   ├── vault.py        markdown, frontmatter, wikilinks, búsqueda
│   └── graph.py        grafo en memoria, backlinks, reparación
├── skills/             las 5 manos
├── voice/              ptt · stt · tts
├── hud/                servidor + La Cara
└── scripts/            setup · run · smoke_test
```

---

## Agregar una skill

Tres pasos, sin tocar el núcleo:

1. `skills/mi_skill.py` con una clase que herede de `Skill` (`name`,
   `description`, `triggers`, `async run(ctx) -> SkillResult`).
2. Regístrala en `ALL_SKILLS` dentro de `skills/__init__.py`.
3. Añádela a `skills.enabled` en el toml.

`ctx` trae `vault`, `graph`, `engine`, `cfg` y `text`. Nada global.

---

## Pruebas

```powershell
.\.venv\Scripts\python scripts\smoke_test.py
```

35 pruebas sobre vault temporal y motor simulado: frontmatter, enlaces, grafo,
búsqueda, escape de rutas, enrutado, las 5 skills, y el candado de privacidad.
No toca tu vault real ni gasta llamadas al motor.

---

## Problemas comunes

| Síntoma | Causa |
|---|---|
| `faster-whisper` no instala | Python 3.14 aún no tiene wheels. Usa 3.12. |
| El PTT no responde | `pynput` necesita foco de escritorio; en apps como admin, corre FRIDAY como admin. |
| Se oye vacío / no transcribe | Micrófono virtual (Voicemod, VB-Cable) como entrada por defecto. Cámbialo en Windows. |
| STT dice "modelo no descargado" | El candado bloqueó la descarga. Corre con `--allow-model-download`. |
| El motor tarda mucho | Baja `engine.timeout_s` o usa `ollama` con un modelo chico. |
