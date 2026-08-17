<div align="center">

# 🟠 F.R.I.D.A.Y

**F**emale **R**eplacement **I**ntelligent **D**igital **A**ssistant **Y**outh

### Tu copiloto de escritorio — no un chatbot con altavoz

<p>
  <img src="https://img.shields.io/badge/Python-3.12-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.12">
  <img src="https://img.shields.io/badge/Qt6-PySide6-41CD52?style=for-the-badge&logo=qt&logoColor=white" alt="Qt6 / PySide6">
  <img src="https://img.shields.io/badge/Windows-11-0078D6?style=for-the-badge&logo=windows11&logoColor=white" alt="Windows 11">
  <img src="https://img.shields.io/badge/Motor-Claude-CC785C?style=for-the-badge&logo=anthropic&logoColor=white" alt="Claude">
  <img src="https://img.shields.io/badge/Voz-100%25_local-2EA043?style=for-the-badge&logo=shieldsdotio&logoColor=white" alt="Voz 100% local">
</p>

</div>

---

Copiloto de escritorio con voz local, memoria en markdown enlazado y acceso
real a la computadora. **No es una aplicación web.** Es una ventana del sistema
—sin marco, flotando sobre tu escritorio— que abre programas, busca archivos,
lee las noticias, investiga en internet y recuerda.

```
tu voz ─▶ F9 ─▶ STT local ─▶ Router ─▶ Skill ─┬─▶ vault/*.md   memoria
                                    │         ├─▶ sistema      apps · ventanas · web
                                    │         ├─▶ archivos     buscar · ordenar · renombrar
                                    │         ├─▶ ordenador    volumen · medios · portapapeles
                                    │         ├─▶ noticias     RSS · resumen · briefing
                                    │         ├─▶ web          investigar · leer páginas
                                    │         ├─▶ pantalla     contexto de lo que ves
                                    │         └─▶ motor        cambiar de modelo hablando
                                    │
                              Política ─── nada con efecto pasa sin permiso
                                    │
                         Acompañante (QtQuick3D) ─▶ TTS local
```

### ✨ Por qué existe

La mayoría de "asistentes de IA" son un chat con micrófono. FRIDAY es otra
cosa: vive en tu escritorio, actúa sobre tu sistema de verdad, y todo lo que
oye se queda en tu equipo.

|  |  |
|---|---|
| 🎙️ **Voz de punta a punta, sin nube** | STT y TTS corren en tu CPU. Un candado a nivel de socket revienta cualquier conexión no-loopback mientras escucha. |
| 🖥️ **Manos reales sobre Windows** | Abre programas, cambia de ventana, organiza carpetas, lee tu pantalla — con una política de permisos delante de cada acción con efecto. |
| 🔀 **Cambia de cerebro hablando** | *"Cambia a Sonnet"* conmuta el modelo en caliente. Claude, un endpoint local, o cualquier proveedor compatible con OpenAI. |
| 🌐 **Sale al mundo, con cuidado** | Lee noticias por RSS y responde con lo que investigó — nunca raspa un buscador ni finge ser otro. |
| 🗂️ **Memoria que no depende de FRIDAY** | Todo es markdown plano en tu disco. Bórrala mañana y tus notas siguen ahí, legibles con cualquier editor. |
| 💠 **Un HUD que reacciona, no decora** | Holograma 3D real cuyos nodos hierven al pensar y respiran con tu voz al escuchar. |
| 🎛️ **Entiende, no reconoce frases** | *"esto suena altísimo"* baja el volumen más que *"bájale"*. La acción la decide el motor contra un catálogo, no una regex por variante. |

---

## 🚀 Arranque

```powershell
.\scripts\setup.ps1              # venv + dependencias + modelo de voz (una vez)
.\scripts\run.ps1                # acompañante + voz
```

**Pulsa F9, habla, pulsa F9 otra vez.** El núcleo aparece en la esquina, el
icono queda en la bandeja del sistema.

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

## 🎭 Quién es

No es un mayordomo. Es una **copiloto**: alta empatía situacional, eficiencia
ejecutiva y lealtad jerárquica. Te llama **Jefe**, habla con modismos casuales
y expresa preocupación, urgencia o alivio abiertamente — porque la mitad del
trabajo de un copiloto es que no estés solo dentro de la armadura.

Donde J.A.R.V.I.S. diría *«Señor, me temo que los niveles son preocupantes»*,
ella dice *«Jefe, esto se está cayendo. Dos opciones y le doy la buena
primero.»*

Bajo estrés no se desordena: acelera. El tono está en
[`config/persona.md`](config/persona.md) y es texto plano — reescríbelo y
cambia quién es, sin tocar código.

---

## 💠 El acompañante

Un **holograma 3D de verdad**, no un círculo con anillos. Escena `View3D` con
cámara en perspectiva: los meridianos del fondo pasan por detrás del núcleo,
los nodos cercanos son mayores que los lejanos, y el brillo se derrama sobre
lo que tiene alrededor. Oro y ámbar sobre fondo profundo, con desenfoque de
campo que ancla el objeto en el espacio.

Cuatro capas, de dentro afuera: **núcleo** incandescente · **radios** que salen
de él · **armazón** de meridianos y paralelos · **nodos**, la nube de puntos.

Y los nodos **reaccionan**. No cambian de color: al pensar se agitan de verdad,
se separan de su posición de reposo y hierven; escuchar los hace respirar con
tu voz; un error los vira a rojo. Es la diferencia entre un adorno y un
indicador.

```toml
[desktop.core]
mode        = "quick3d"   # quick3d | projected
nodes       = 1400        # 600 en equipos justos
bloom       = true
depth_field = true
```

Si QtQuick3D falta o el driver se atraganta, cae solo al núcleo 2.5D. Nunca te
quedas sin cara.

Arrástralo desde el núcleo. Clic derecho para el menú, doble clic para escribir.

---

## 🧠 Las 12 skills

FRIDAY enruta sola. No hay que invocarlas por nombre.

### 🖥️ Sobre la computadora

| Skill | Ejemplos |
|---|---|
| **sistema** | *"abre Spotify"* · *"abre YouTube"* · *"qué tengo abierto"* · *"busca gatos en google"* |
| **archivos** | *"organiza mis descargas"* · *"busca el archivo presupuesto"* · *"renombra …"* |
| **pantalla** | *"qué estoy viendo"* · *"explícame esto"* |
| **ordenador** | *"no te oigo"* · *"ponlo a la mitad"* · *"sáltate esta canción"* · *"qué tengo copiado"* |

### 🌐 Sobre el mundo

| Skill | Ejemplos |
|---|---|
| **noticias** | *"ponme al día con las noticias"* · *"dame los titulares de tecnología"* |
| **web** | *"investiga quién fue Ada Lovelace"* · *"resume esta página https://…"* |

### 🗂️ Sobre tu memoria

| Skill | Ejemplos |
|---|---|
| **vault** | *"recuerda que …"* · *"qué sabes de …"* |
| **agenda** | *"qué tengo hoy"* · *"agéndame … el viernes"* |
| **plan** | *"arma el plan"* · *"por dónde empiezo"* |
| **inbox** | *"buenos días"* · *"ponme al día"* |
| **metricas** | *"dame las métricas"* |

### 🔀 Sobre sí misma

| Skill | Ejemplos |
|---|---|
| **motor** | *"cambia a Sonnet"* · *"qué modelo estás usando"* · *"ponme en local"* |

El enrutado tiene dos caminos: **rápido** (regex, 0 ms, sin motor) y **pensado**
(el motor clasifica). El puntaje pesa la *especificidad* del disparador, no su
cobertura — por eso *"ponme al día con las noticias"* va a `noticias` y
*"ponme al día"* a solas va a `inbox`, aunque ambas reconozcan la frase.

Lo mismo con *"cambia a"*: **`cambia a Sonnet`** es un modelo, **`cambia a
Chrome`** es una ventana. Lo que decide no es el verbo, es el objeto.

---

## 🔀 Cambiar de modelo hablando

El motor no es un ajuste de arranque: es un conmutador. Di el nombre y cambia
en caliente, sin reiniciar nada.

```
› cambia a sonnet
  Listo, Jefe. Pensando con Sonnet 5.
› qué modelo estás usando
  Sonnet 5.
```

El catálogo vive en el toml, con los alias que puedes decir — incluidas las
variantes que suele producir el reconocedor de voz:

```toml
[[engine.roster]]
key     = "sonnet"
label   = "Sonnet 5"
backend = "claude_code"
model   = "claude-sonnet-5"
say     = ["sonnet", "soneto", "sonet", "el equilibrado"]
```

| Adaptador | Para qué |
|---|---|
| `claude_code` | Claude vía el binario `claude`. Sin API key: usa tu suscripción. |
| `anthropic_api` | **El mismo Claude, más rápido.** HTTP directo, sin levantar Node ni cruzar el shim de npm: 1-2 s menos por turno. Necesita `ANTHROPIC_API_KEY` y factura por token. |
| `ollama` | Modelos locales. Nada sale del equipo. |
| `openai_compat` | Cualquier endpoint `/chat/completions`: llama.cpp, LM Studio, vLLM… y también OpenAI, Groq, OpenRouter, DeepSeek o Gemini por su capa compatible. Cambiar de proveedor es `base_url` + `api_key_env`. |

**Recomendación para uso diario con Claude:** `anthropic_api`. En un asistente
de voz el arranque de un proceso de Node se nota en cada turno, más que
cualquier diferencia de tokens por segundo. `claude_code` sigue siendo el
arranque por defecto porque funciona sin configurar nada.

Añadir un proveedor nuevo es una clase que herede de `Engine` y una entrada en
el roster. Nada fuera de `core/engine.py` sabe que Claude existe.

---

## 🎛️ Control del ordenador: entender, no reconocer

Volumen, reproducción, portapapeles, bloqueo de sesión y ventanas. Lo que hace
distinta a esta skill es **cómo decide**.

El resto enruta con expresiones regulares, y está bien: *"abre Spotify"*
siempre significa lo mismo y resolverlo en 0 ms sin gastar una llamada es una
virtud. Pero el control del escritorio no se comporta así:

```
› no te oigo                 → sube el volumen 20 puntos
› esto suena altísimo, bájale → lo baja 30   ← más, porque «altísimo»
› ponlo a la mitad            → nivel absoluto 50
› sáltate esta canción        → siguiente pista
› cópiame el correo de soporte arroba ejemplo punto com
                              → escribe «soporte@ejemplo.com»
```

Son la misma familia de intención con cero palabras en común, y cada una lleva
un argumento distinto dentro. Escribir una regex por variante es una carrera
que se pierde. Aquí la regex solo sirve para llegar **a la skill**; qué acción
concreta es, y con qué argumentos, lo decide el motor contra un catálogo
declarado como datos. Añadir una capacidad es añadir una entrada a esa tupla.

**Que el motor elija no significa que el motor mande.** Lo que devuelve es una
propuesta: antes de tocar nada se comprueba que la acción existe en el
catálogo, que el puerto está disponible y que la política la permite. Un
modelo que alucine `formatear_disco` se estrella contra una lista blanca que
no lo contiene — y hay una prueba que lo fija.

```
› bloquea el equipo que me voy
  No puedo. El control de session está deshabilitado.
  → activa `policy.allow_session` en config/friday.toml

  (con el permiso puesto)
  Voy a bloquear. ¿Confirmas?
› sí
  Hasta ahora, Jefe.
```

---

## 🛡️ La política: por qué es seguro

El STT se equivoca. *"Organiza mis descargas"* mal reconocido no puede
convertirse en un desastre. Por eso **toda acción con efecto pasa por un
guardia** que devuelve uno de tres veredictos: permitir, confirmar o denegar.

```toml
[policy]
allow_launch       = true
allow_file_write   = true
allow_shell        = false        # apagado por defecto
allow_web          = true         # abrir búsquedas en TU navegador
allow_web_fetch    = true         # que FRIDAY salga a la red por su cuenta
allow_media        = true         # volumen y reproducción
allow_clipboard    = true         # leer y escribir el portapapeles
allow_session      = false        # bloquear/suspender: apagado por defecto
confirm_over_files = 5            # sobre esto, pide confirmación hablada
write_roots  = ["~/Documents", "~/Downloads", "~/Desktop", "~/Pictures"]
blocked_apps = ["regedit*", "diskpart*", "cmd.exe", "powershell*"]
```

`allow_web` y `allow_web_fetch` son permisos distintos a propósito: uno entrega
una URL a tu navegador —la petición la hace Chrome, con tu sesión—, el otro
autoriza que FRIDAY salga a internet ella misma. El segundo es más fuerte y
tiene su propio interruptor.

Además hay un suelo **no configurable**: `C:\Windows`, `Program Files`,
`ProgramData`, las extensiones críticas (`.sys`, `.dll`, `.msi`…) y **toda la
red local** (`127.*`, `192.168.*`, `10.*`, `.local`) están bloqueados aunque
aflojes la config. Que una URL dictada por voz alcance tu router no es una
función, es un accidente.

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

## 📰 Noticias e investigación

**Noticias.** Lee los feeds RSS que declares, los deduplica, los intercala para
que ningún medio copie el briefing, dice dos frases y deja el resumen completo
en `vault/outputs/`.

```toml
[[news.sources]]
name  = "Xataka"
topic = "tecnologia"
url   = "https://www.xataka.com/feedburner.xml"
```

No raspa portadas: lee exactamente los feeds que le des. Un raspador se rompe
cada vez que el medio cambia el HTML.

**Investigación.** *"Investiga X"* consulta una API estable y te responde
citando la fuente. *"Resume esta página `<url>`"* descarga esa página y la lee.

Lo que **no** hace es raspar la página de resultados de un buscador: ese HTML
cambia constantemente, muchos buscadores lo bloquean, y un asistente que se
apoya en eso empieza a mentir en cuanto se rompe. Si quieres resultados de
búsqueda, *"busca X en google"* te los abre en tu navegador.

> **Pon tu contacto en `[system] contact`.** Viaja en el User-Agent. No es
> cortesía: Wikimedia responde **403 a todo** si no hay una forma de contacto,
> y bloquea explícitamente a quien finge ser Chrome.

---

## 🗂️ La memoria: solo archivos

Sin base de datos. Sin índice que se corrompa. Si borras FRIDAY, tus notas
siguen ahí y las abre cualquier editor de texto.

```
vault/
├── raw/        captura cruda — nota diaria, transcripciones de voz
├── wiki/       notas atómicas enlazadas con [[wikilinks]] → el grafo
└── outputs/    lo que FRIDAY produce — Briefing, Plan, Noticias, resúmenes
```

**Obsidian:** *Open folder as vault* → elige `vault/`. El grafo aparece solo,
sin plugins. Ya viene configurado con acento ámbar y colores por zona.

Di **"reparar grafo"** y crea stubs para todo enlace roto: la memoria se cierra
sola.

---

## 🎙️ Voz: por qué es privada de verdad

- **STT** — `faster-whisper` en tu CPU/GPU. El modelo se baja **una vez**; de ahí, offline.
- **TTS** — Piper (ONNX local) o las voces SAPI5 de Windows.
- **PTT** — F9 global; el audio vive en RAM y se descarta al transcribir.

Y no te pedimos que confíes en la palabra: mientras el pipeline de audio corre,
`core/privacy.py` intercepta `socket.connect` y **revienta cualquier conexión
que no sea loopback**. Si una dependencia intentara mandar tu voz a algún lado,
lo ves como error. Las pruebas lo verifican, incluso entre hilos.

Ese candado es del audio, no de todo el proceso: leer noticias sí sale a la
red, y pasa por `[policy] allow_web_fetch`.

```toml
[voice.ptt]
key  = "f9"
mode = "toggle"      # pulsa para abrir, pulsa para cerrar
                     # "hold" = mantén pulsado mientras hablas
```

Primera vez, para permitir la descarga del modelo:

```powershell
.\.venv\Scripts\python friday.py --allow-model-download
```

---

## 🏗️ Arquitectura

Bajo acoplamiento por construcción, no por disciplina.

```
friday.py              orquestador — el único que conoce a todos
config/                friday.toml (todo) · persona.md (tono)
core/
  bus.py               pub/sub asíncrono: nadie importa a nadie
  engine.py            adaptadores + roster + ⭐ EngineSwitch
  router.py            confirmación → rápido → pensado
  policy.py            el guardia de permisos
  privacy.py           candado de red del audio
memory/                vault.py (markdown) · graph.py (enlaces)
system/
  ports.py             ⭐ los Protocol: la inversión de dependencias
  factory.py           lo único que sabe en qué SO corre
  net.py               ⭐ la única salida HTTP del proyecto
  files.py · web.py · news.py · pages.py
  win32/               implementaciones de Windows (apps, ventanas, escritorio)
skills/                las 12 manos
voice/                 ptt · stt · tts
desktop/
  app.py               ventana nativa + bandeja
  bridge.py            única frontera Python ↔ QML
  geometry.py          malla del holograma (QQuick3DGeometry)
  sprites.py           texturas del núcleo, pintadas en memoria
  qml/                 HoloCore · core3d/ · core2d/ · Companion
```

**`system/ports.py` es la pieza clave.** Las skills dependen de `Protocol`
abstractos, nunca de `win32/`. Y las interfaces están segregadas: `FileIndex`
solo lee — una skill que busca archivos es *incapaz* de borrarlos, no por
disciplina sino por tipo.

**`core/engine.py::EngineSwitch` es la segunda.** Todos sostienen la fachada,
nadie sostiene un motor concreto. Por eso cambiar de modelo a media
conversación no deja ninguna referencia colgando.

### Agregar una skill

1. `skills/mi_skill.py` heredando de `Skill` (`name`, `description`,
   `triggers`, `needs`, `async run(ctx)`).
2. Regístrala en `ALL_SKILLS` de `skills/__init__.py`.
3. Añádela a `skills.enabled` del toml.

`ctx` trae `vault`, `graph`, `engine`, `system`, `policy` y `text`. Nada global.

### 🧰 Stack tecnológico

<p>
  <img src="https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/asyncio-event_loop-3776AB?style=flat-square&logo=python&logoColor=white" alt="asyncio">
  <img src="https://img.shields.io/badge/PySide6-Qt6-41CD52?style=flat-square&logo=qt&logoColor=white" alt="PySide6">
  <img src="https://img.shields.io/badge/QtQuick3D-View3D-41CD52?style=flat-square&logo=qt&logoColor=white" alt="QtQuick3D">
  <img src="https://img.shields.io/badge/QML-UI_declarativa-41CD52?style=flat-square&logo=qt&logoColor=white" alt="QML">
  <img src="https://img.shields.io/badge/pywin32-Windows_API-0078D6?style=flat-square&logo=windows11&logoColor=white" alt="pywin32">
  <br>
  <img src="https://img.shields.io/badge/Claude-Anthropic-CC785C?style=flat-square&logo=anthropic&logoColor=white" alt="Claude">
  <img src="https://img.shields.io/badge/Ollama-modelos_locales-000000?style=flat-square&logo=ollama&logoColor=white" alt="Ollama">
  <img src="https://img.shields.io/badge/OpenAI_compat-llama.cpp_·_vLLM_·_LM_Studio-412991?style=flat-square&logo=openai&logoColor=white" alt="OpenAI compatible">
  <br>
  <img src="https://img.shields.io/badge/faster--whisper-STT_local-9146FF?style=flat-square" alt="faster-whisper">
  <img src="https://img.shields.io/badge/Piper-TTS_neuronal-FFB300?style=flat-square" alt="Piper TTS">
  <img src="https://img.shields.io/badge/SAPI5-TTS_de_Windows-0078D6?style=flat-square&logo=windows11&logoColor=white" alt="SAPI5">
  <img src="https://img.shields.io/badge/pynput-push--to--talk-FFB300?style=flat-square" alt="pynput">
  <br>
  <img src="https://img.shields.io/badge/aiohttp-cliente_HTTP-2C5BB4?style=flat-square&logo=aiohttp&logoColor=white" alt="aiohttp">
  <img src="https://img.shields.io/badge/RSS_%2F_Atom-noticias-FFA500?style=flat-square&logo=rss&logoColor=white" alt="RSS/Atom">
  <img src="https://img.shields.io/badge/Wikipedia_API-investigación-000000?style=flat-square&logo=wikipedia&logoColor=white" alt="Wikipedia API">
  <br>
  <img src="https://img.shields.io/badge/TOML-configuración-9C4221?style=flat-square&logo=toml&logoColor=white" alt="TOML">
  <img src="https://img.shields.io/badge/Markdown-memoria_%28vault%29-000000?style=flat-square&logo=markdown&logoColor=white" alt="Markdown">
  <img src="https://img.shields.io/badge/Obsidian-grafo_de_notas-7C3AED?style=flat-square&logo=obsidian&logoColor=white" alt="Obsidian">
</p>

---

## 🧪 Pruebas

```powershell
.\.venv\Scripts\python scripts\smoke_test.py     # 46 · memoria, skills, enrutado, privacidad
.\.venv\Scripts\python scripts\system_test.py    # 64 · política, puertos, red, motor, PTT
```

Sobre directorios temporales, motor simulado y feeds sintéticos: no tocan tu
vault real, no mueven tus archivos, no gastan llamadas al motor y **no
dependen de la red**.

El HUD se revisa mirándolo, no leyéndolo:

```powershell
.\.venv\Scripts\python scripts\ui_preview.py thinking --shot nucleo.png
```

---

## 🩹 Problemas comunes

| Síntoma | Causa |
|---|---|
| `faster-whisper` no instala | Python 3.14 aún no tiene wheels. Usa 3.12. |
| El PTT no responde | `pynput` necesita foco de escritorio; con apps como admin, corre FRIDAY como admin. |
| No transcribe | Micrófono virtual (Voicemod, VB-Cable) como entrada por defecto. Cámbialo en Windows. |
| STT dice "modelo no descargado" | El candado bloqueó la descarga. Usa `--allow-model-download`. |
| "Fuera de las carpetas donde puedo escribir" | La política funcionando. Añade la ruta a `write_roots`. |
| No puedo enfocar una ventana | Windows bloquea `SetForegroundWindow` desde procesos sin foco. FRIDAY la marca en la barra. |
| El núcleo se ve plano, sin 3D | Cayó al plan B. Mira la consola: falta QtQuick3D o el QML tiene un error. |
| El núcleo va a tirones | Baja `[desktop.core] nodes` a 600 y apaga `depth_field`. |
| Las noticias no llegan | Revisa `[policy] allow_web_fetch` y `[system] contact`. El panel dice qué feed falló. |
| "Investiga" no encuentra nada | Sin contacto en el User-Agent la fuente responde 403. Pon `[system] contact`. |
| El panel se ve translúcido de más | Activa `[desktop] backdrop = "acrylic"` para desenfoque real de Windows 11. |

---

## 🧭 Qué falta

Lo pendiente, lo decidido a conciencia y lo de algún día está en
**[ROADMAP.md](ROADMAP.md)**. Lo más inmediato:

- **Encargarle trabajo a Claude Code por voz** — *"métete en mi-proyecto y
  revisa por qué fallan los tests"*. El modo agéntico del motor ya existe;
  falta quien lo llame, y las barreras para que un STT que se equivoca no
  suelte un agente con permiso de escritura en el sitio equivocado.
- **Juegos de Steam y apps de Microsoft Store** — Brave y el cliente de Steam
  ya se abren; los juegos y las apps empaquetadas no aparecen en el catálogo.
- **Bluetooth, wifi y brillo**, y que cuando no sepa hacer algo lo diga por su
  nombre en vez de un genérico *"no me quedó claro"*.

---

<div align="center">

**F.R.I.D.A.Y no vive en un servidor de otro. Vive en tu escritorio.**

</div>
