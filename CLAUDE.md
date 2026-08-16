# F.R.I.D.A.Y — contexto del repo

Copiloto de escritorio con voz local, acceso al sistema y salida a la red.
Python 3.12, asyncio + Qt/QML + QtQuick3D. Corre local. **No es una app web.**

## Reglas de este repo

1. **La memoria es markdown y nada más.** Nunca propongas SQLite, Chroma ni un
   índice persistente. Lo que necesite ser rápido se cachea en RAM y se
   reconstruye leyendo archivos.
2. **El audio no sale del equipo.** No agregues clientes HTTP a `voice/`.
   `core/privacy.py` bloquea sockets no-loopback durante el pipeline de audio.
   La red vive en `system/net.py`, y solo ahí.
3. **El motor es intercambiable.** Nada fuera de `core/engine.py` puede asumir
   que el backend es Claude. El catálogo de modelos es **datos del toml**
   (`[[engine.roster]]`), no código. Un prompt debe funcionar con un 8B local.
4. **Los archivos los escribe Python, no el motor.** El motor razona y devuelve
   texto/JSON; `memory/vault.py` y `system/files.py` son los únicos que escriben.
5. **Nadie importa a nadie.** La comunicación entre capas va por `core/bus.py`.
6. **Nada con efecto pasa sin política.** Toda acción sobre el sistema consulta
   `core/policy.py`. Si añades una capacidad que escribe, lanza, borra **o sale
   a internet**, tiene que pasar por ahí. Sin excepciones.
7. **Las skills dependen de `system/ports.py`, nunca de `system/win32/`.**
   Si escribes `import win32gui` fuera de `system/win32/`, está mal.

## Cableado

```
voice/ptt.py --(hilo)--> voice/stt.py --> friday.py::handle
                                              |
                          core/router.py <----+
                                |
              skills/*.py --> memory/vault.py      (markdown)
                          --> system/ports.py      (Protocol)
                          --> core/engine.py       (EngineSwitch)
                                |                       |
                          core/policy.py    system/win32/ · files.py · net.py
                                |                       |
                          core/bus.py --> desktop/bridge.py --> QML --> View3D
```

`friday.py` es el único que conoce a todos. Es a propósito.

## El motor: un conmutador, no un motor

`build_engine()` devuelve un **`EngineSwitch`**, no un adaptador. Router y
skills sostienen esa fachada, así que «cambia a Sonnet» a media conversación
no invalida ninguna referencia: solo cambia a quién delega. Los adaptadores se
construyen perezosamente y se cachean.

- **Adaptadores**: `claude_code` · `anthropic_api` · `ollama` · `openai_compat`.
  `openai_compat` cubre también OpenAI, Groq, OpenRouter, DeepSeek y la capa
  compatible de Gemini: es `base_url` + `api_key_env`, no un adaptador nuevo.
- **Roster**: cada entrada trae `key`, `backend`, `model` y `say` (los alias
  hablados). `resolve_model()` gana con el **alias más largo**.
- **`skills/motor.py`** sobrescribe `matches()` a propósito: «cambia a X» solo
  es suyo si X está en el roster. Si no, devuelve 0 y le deja la ventana a
  `sistema`. Competir ahí le robaría a `sistema` cada «cambia a Chrome».

## Contratos

- **Skill**: hereda `skills/base.py::Skill`. Define `name`, `description`,
  `triggers` (regex), `needs` (puertos requeridos) y `async run(ctx) -> SkillResult`.
  Registrar en `skills/__init__.py::ALL_SKILLS` y en `skills.enabled` del toml.
- **Puerto nuevo**: `Protocol` en `system/ports.py`, campo en `SystemAccess`,
  implementación en `system/win32/` o `system/`, cableado en `system/factory.py`.
  **Separa lectura de escritura** — es interface segregation, no burocracia.
  Los puertos de red (`NewsPort`, `PageReaderPort`) son `async`; los locales no.
- **Acción que necesita permiso**: devuelve `SkillResult(pending=PendingAction(...))`.
  El router la guarda y la ejecuta cuando el usuario dice "sí".
- **Engine**: hereda `core/engine.py::Engine`. Registrar en `ENGINES` y añadir
  una entrada al roster del toml.
- **Prompts**: cada llamada declara su propio formato. `config/persona.md` define
  el **tono**, nunca la estructura — si metes un contrato JSON ahí, pelea con el
  de cada skill y todo cae al fallback.

## El control del ordenador: catálogo, no guiones

`skills/ordenador.py` no elige la acción con regex. Sus `triggers` solo llevan
**a la skill**; cuál de las nueve acciones es, y con qué argumentos, lo decide
el motor contra `CATALOGO`, una tupla de `Accion` declarada como datos.

Es deliberado y acotado: «bájale», «esto suena altísimo» y «ponlo a la mitad»
son la misma familia con cero palabras en común, y una regex por variante es
una carrera que se pierde. El resto de skills siguen con regex porque «abre
Spotify» sí significa siempre lo mismo, y resolverlo en 0 ms es una virtud.

**El motor propone, no dispone.** Lo que devuelve se valida contra el catálogo
(lista blanca — un `formatear_disco` alucinado no existe), contra el puerto
disponible y contra `policy.can_control()`. Añadir una capacidad es una entrada
en la tupla más su rama en `_aplicar`; hay una prueba que fija que no se pueda
declarar una sin implementar.

## El HUD

`desktop/qml/HoloCore.qml` elige implementación según `[desktop.core] mode`:

- **`quick3d`** — `core3d/Holo3D.qml`. Escena 3D real: `View3D`, cámara en
  perspectiva, `ExtendedSceneEnvironment` con bloom y profundidad de campo.
  La geometría (armazón, radios, arcos) se genera en **Python**
  (`desktop/geometry.py`, `QQuick3DGeometry`, primitiva `Lines`); los nodos son
  partículas, porque tienen que reaccionar y un buffer estático no reacciona.
- **`projected`** — `core2d/HoloProjected.qml`, el orbe 2.5D de siempre.

Se carga con `Loader`, no con `import`: si QtQuick3D falta o el driver se
atraganta, cae al plan B en vez de dejar el acompañante sin cara.

## Trampas conocidas (ya nos mordieron)

### Motor y sistema
- **Windows + npm shim**: pasar prompts largos por argv a `claude.CMD` los
  corrompe. Van por **stdin**.
- **Claude Code como motor** necesita `--tools ""` y `--system-prompt`; si no,
  se comporta como agente de código: intenta escribir archivos y responde en
  prosa en vez del JSON pedido.
- **`privacy.sealed()` es thread-local.** Va **dentro** del hilo que trabaja,
  no alrededor de `asyncio.to_thread(...)`.
- **Python 3.14 no sirve**: `faster-whisper` no tiene wheels. El venv es 3.12.

### Red
- **El User-Agent necesita un contacto.** Wikimedia devuelve **403 a todo**
  —API REST, action API, todo— si el UA no lleva una forma de contacto entre
  paréntesis. Y fingir ser Chrome está explícitamente bloqueado: la opción que
  parecía más segura es la que menos funciona. Ver `system/net.py::user_agent`
  y `[system] contact`.
- **Un feed de portada pasa del megabyte.** El tope de descarga lo parte, el
  XML llega inválido y se perdían cien titulares por culpa del último. Ver
  `system/news.py::_repair`.
- **No ordenes la mezcla de titulares por fecha.** El medio que publica cada
  diez minutos copa el briefing. Se intercala por rondas (`_interleave`).
- **No raspes páginas de resultados de buscadores.** Cambian el HTML cada pocas
  semanas y muchos lo bloquean. Para temas se usa una API estable.

### Voz
- **SAPI5 es COM con afinidad de apartamento.** Construirlo en un hilo y
  usarlo en otro no da error: cuelga `runAndWait()` para siempre y FRIDAY se
  queda muda el resto de la sesión. Todo lo que toca COM vive en el hilo
  `tts`; `load()` solo detecta y `shutup()` levanta un evento en vez de
  purgar desde fuera. Ver la cabecera de `voice/tts.py`.
- **`pyttsx3` cachea el motor en un dict global del módulo** y su
  `runAndWait()` vuelve antes de que acabe el audio, así que cada frase corta
  a la anterior. Por eso se usa `comtypes` directo.
- **El teclado repite `on_press` mientras la tecla sigue abajo.** En modo
  `toggle` eso abre y cierra el micrófono decenas de veces por pulsación. Hay
  que recordar el flanco (`_held`). La máquina de estados está separada del
  listener (`key_down` / `key_up`) justo para poder probarla sin teclado.

### Interfaz
- **QML `pixelSize` es entero.** `13.5` revienta la carga entera del componente.
- **`setPosition()` va después de `show()`**, o el gestor de ventanas reubica.
- **Sin `@Slot`, QML no ve un método** como función invocable.
- **`Behavior on X` exige que X sea escribible.** Un `readonly property` con
  Behavior no compila y tumba el QML entero — y el `Loader` lo silencia
  cayendo al plan B, así que parece que «no hay 3D» cuando hay una errata.
- **`blendMode: Screen` sobre fondo transparente lo lava todo a blanco.** El
  aspecto aditivo lo da el post-proceso de brillo, que sabe qué es fondo; el
  material solo dibuja con su alfa.
- **Las partículas se miden en unidades de escena, no en píxeles.** Un
  `particleScale` de 3 con un sprite de 64 px tapa media esfera.
- **Puntaje de triggers = especificidad, no cobertura.** Si mides cobertura,
  "recuerda que <párrafo>" se diluye y pierde. Ver `skills/base.py::matches`.
- **Ventana translúcida sin blur = texto ilegible.** Qt no desenfoca lo que hay
  detrás; eso lo hace el compositor (`desktop/backdrop.py`, opcional).

## Verificar cambios

```powershell
.\.venv\Scripts\python scripts\smoke_test.py     # 46 · memoria, skills, enrutado, privacidad
.\.venv\Scripts\python scripts\system_test.py    # 64 · política, puertos, red, motor, PTT
.\.venv\Scripts\python friday.py --check         # dependencias, roster y capacidades
.\.venv\Scripts\python scripts\ui_preview.py     # solo la interfaz, iteración rápida
```

Las pruebas usan directorios temporales, motor simulado y feeds sintéticos: no
tocan el vault real, no mueven archivos del usuario, no gastan llamadas y **no
dependen de la red**. Si tocas `memory/`, `skills/`, `core/` o `system/`,
córrelas.

**El HUD no se valida leyendo QML.** Una escena con partículas y post-proceso
hay que mirarla:

```powershell
.\.venv\Scripts\python scripts\ui_preview.py thinking --shot nucleo.png
.\.venv\Scripts\python scripts\ui_preview.py idle --projected --shot planb.png
```
