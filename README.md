# F.R.I.D.A.Y

Acompañante de escritorio con voz local, memoria en markdown enlazado y acceso
real a la computadora. **No es una aplicación web.** Es una ventana del sistema
—sin marco, flotando sobre tu escritorio— que abre programas, busca archivos,
lee lo que tienes en pantalla y recuerda.

```
tu voz ─▶ PTT ─▶ STT local ─▶ Router ─▶ Skill ─┬─▶ vault/*.md   memoria
                                     │         ├─▶ sistema      apps · ventanas · web
                                     │         ├─▶ archivos     buscar · ordenar · renombrar
                                     │         └─▶ pantalla     contexto de lo que ves
                                     │
                               Política ─── nada con efecto pasa sin permiso
                                     │
                          Acompañante (Qt/QML) ─▶ TTS local
```

---

## Arranque

```powershell
.\scripts\setup.ps1              # venv + dependencias + modelo de voz (una vez)
.\scripts\run.ps1                # acompañante + voz
```

**Mantén ESPACIO y habla.** El orbe aparece en la esquina, el icono queda en la
bandeja del sistema.

| Comando | Qué hace |
|---|---|
| `.\scripts\run.ps1` | acompañante + voz |
| `.\scripts\run.ps1 -Silent` | sin ventana de consola detrás |
| `.\scripts\run.ps1 -NoVoice` | acompañante sin micrófono, escribes |
| `.\scripts\run.ps1 -Console` | sin ventana, solo terminal |
| `.\scripts\run.ps1 -Preview` | solo la interfaz, con datos de muestra |
| `.\scripts\run.ps1 -Check` | diagnóstico |
| `.\scripts\run.ps1 -Say "abre spotify"` | una petición y sale |

---

## El acompañante

Un orbe holográfico: anillos concéntricos girando en distintos ejes y
velocidades, núcleo incandescente, partículas orbitales. Ámbar sobre fondo
profundo. El panel de cristal se despliega solo cuando hay algo que decir.

El orbe **responde al estado**: escuchar lo abre y aclara al oro, pensar acelera
el giro, hablar lo calma, un error lo vira a rojo. El nivel de tu voz lo hace
respirar en tiempo real.

Cada anillo se dibuja **una sola vez**; después solo se anima su transform. La
rotación vive en el hilo de render, así que el orbe puede girar todo el día sin
castigar la CPU.

Arrástralo desde el orbe. Clic derecho para el menú, doble clic para escribir.

---

## Las 8 skills

FRIDAY enruta sola. No hay que invocarlas por nombre.

### Sobre la computadora

| Skill | Ejemplos |
|---|---|
| **sistema** | *"abre Spotify"* · *"qué tengo abierto"* · *"enfoca Chrome"* · *"busca en YouTube …"* |
| **archivos** | *"organiza mis descargas"* · *"busca el archivo presupuesto"* · *"renombra …"* |
| **pantalla** | *"qué estoy viendo"* · *"explícame esto"* |

### Sobre tu memoria

| Skill | Ejemplos |
|---|---|
| **vault** | *"recuerda que …"* · *"qué sabes de …"* |
| **agenda** | *"qué tengo hoy"* · *"agéndame … el viernes"* |
| **plan** | *"arma el plan"* · *"por dónde empiezo"* |
| **inbox** | *"buenos días"* · *"ponme al día"* |
| **metricas** | *"dame las métricas"* |

El enrutado tiene dos caminos: **rápido** (regex, 0 ms, sin motor) y **pensado**
(el motor clasifica). El puntaje pesa la *especificidad* del disparador, no su
cobertura — por eso *"qué tengo abierto"* va a `sistema` y no a `inbox`, aunque
ambos reconozcan *"qué tengo"*.

---

## La política: por qué es seguro

El STT se equivoca. *"Organiza mis descargas"* mal reconocido no puede
convertirse en un desastre. Por eso **toda acción con efecto pasa por un
guardia** que devuelve uno de tres veredictos: permitir, confirmar o denegar.

```toml
[policy]
allow_launch       = true
allow_file_write   = true
allow_shell        = false        # apagado por defecto
confirm_over_files = 5            # sobre esto, pide confirmación hablada
write_roots  = ["~/Documents", "~/Downloads", "~/Desktop", "~/Pictures"]
blocked_apps = ["regedit*", "diskpart*", "cmd.exe", "powershell*"]
```

Además hay un suelo **no configurable**: `C:\Windows`, `Program Files`,
`ProgramData` y las extensiones críticas (`.sys`, `.dll`, `.msi`…) están
bloqueados aunque aflojes la config.

Y la separación que lo hace funcionar: **planear y aplicar son operaciones
distintas.** FRIDAY primero describe qué va a pasar —cuántos archivos, a dónde,
con una muestra— y solo toca el disco si dices **sí**.

```
› organiza mis descargas
  199 movimientos planeados · Documentos 50 · Comprimidos 41 · Imágenes 30
  ¿Confirmas?
› sí
  Patrón integrado. 199 aplicadas.
```

Nada se sobrescribe nunca: si el destino existe, se añade un sufijo.

---

## La memoria: solo archivos

Sin base de datos. Sin índice que se corrompa. Si borras FRIDAY, tus notas
siguen ahí y las abre cualquier editor de texto.

```
vault/
├── raw/        captura cruda — nota diaria, transcripciones de voz
├── wiki/       notas atómicas enlazadas con [[wikilinks]] → el grafo
└── outputs/    lo que FRIDAY produce — Briefing, Plan, resúmenes
```

**Obsidian:** *Open folder as vault* → elige `vault/`. El grafo aparece solo,
sin plugins. Ya viene configurado con acento ámbar y colores por zona.

Di **"reparar grafo"** y crea stubs para todo enlace roto: la memoria se cierra
sola.

---

## Voz: por qué es privada de verdad

- **STT** — `faster-whisper` en tu CPU/GPU. El modelo se baja **una vez**; de ahí, offline.
- **TTS** — Piper (ONNX local) o las voces SAPI5 de Windows.
- **PTT** — hotkey global; el audio vive en RAM y se descarta al transcribir.

Y no te pedimos que confíes en la palabra: mientras el pipeline de audio corre,
`core/privacy.py` intercepta `socket.connect` y **revienta cualquier conexión
que no sea loopback**. Si una dependencia intentara mandar tu voz a algún lado,
lo ves como error. Las pruebas lo verifican, incluso entre hilos.

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

Con `claude_code`, FRIDAY lo corre **sin herramientas** (`--tools ""`) y con su
propio system prompt: un LLM puro, entra texto y sale texto. Los archivos los
escribe FRIDAY en Python. Así el motor no puede tocar tu disco por accidente, y
cambiarlo por un modelo local de 8B no rompe nada.

---

## Arquitectura

Bajo acoplamiento por construcción, no por disciplina.

```
friday.py              orquestador — el único que conoce a todos
config/                friday.toml (todo) · persona.md (tono)
core/
  bus.py               pub/sub asíncrono: nadie importa a nadie
  engine.py            adaptadores de motor
  router.py            confirmación → rápido → pensado
  policy.py            el guardia de permisos
  privacy.py           candado de red del audio
memory/                vault.py (markdown) · graph.py (enlaces)
system/
  ports.py             ⭐ los Protocol: la inversión de dependencias
  factory.py           lo único que sabe en qué SO corre
  files.py · web.py    implementaciones multiplataforma
  win32/               implementaciones de Windows
skills/                las 8 manos
voice/                 ptt · stt · tts
desktop/
  app.py               ventana nativa + bandeja
  bridge.py            única frontera Python ↔ QML
  qml/                 Orb · Ring · Companion · GlowButton
```

**`system/ports.py` es la pieza clave.** Las skills dependen de `Protocol`
abstractos, nunca de `win32/`. Y las interfaces están segregadas: `FileIndex`
solo lee — una skill que busca archivos es *incapaz* de borrarlos, no por
disciplina sino por tipo.

### Agregar una skill

1. `skills/mi_skill.py` heredando de `Skill` (`name`, `description`,
   `triggers`, `needs`, `async run(ctx)`).
2. Regístrala en `ALL_SKILLS` de `skills/__init__.py`.
3. Añádela a `skills.enabled` del toml.

`ctx` trae `vault`, `graph`, `engine`, `system`, `policy` y `text`. Nada global.

---

## Pruebas

```powershell
.\.venv\Scripts\python scripts\smoke_test.py     # 35 · memoria, skills, privacidad
.\.venv\Scripts\python scripts\system_test.py    # 31 · política, puertos, confirmación
```

Ambas sobre directorios temporales y motor simulado: no tocan tu vault real, no
mueven tus archivos y no gastan llamadas al motor.

---

## Problemas comunes

| Síntoma | Causa |
|---|---|
| `faster-whisper` no instala | Python 3.14 aún no tiene wheels. Usa 3.12. |
| El PTT no responde | `pynput` necesita foco de escritorio; con apps como admin, corre FRIDAY como admin. |
| No transcribe | Micrófono virtual (Voicemod, VB-Cable) como entrada por defecto. Cámbialo en Windows. |
| STT dice "modelo no descargado" | El candado bloqueó la descarga. Usa `--allow-model-download`. |
| "Fuera de las carpetas donde puedo escribir" | La política funcionando. Añade la ruta a `write_roots`. |
| No puedo enfocar una ventana | Windows bloquea `SetForegroundWindow` desde procesos sin foco. FRIDAY la marca en la barra. |
| El panel se ve translúcido de más | Activa `[desktop] backdrop = "acrylic"` para desenfoque real de Windows 11. |
