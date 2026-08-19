# F.R.I.D.A.Y — contexto del repo

Copiloto de escritorio con voz local, acceso al sistema y salida a la red.
Python 3.12, asyncio + Qt/QML + QtQuick3D. Corre local. **No es una app web.**

## Reglas de este repo

1. **La memoria es markdown y nada más.** Nunca propongas SQLite, Chroma ni un
   índice persistente. Lo que necesite ser rápido se cachea en RAM y se
   reconstruye leyendo archivos. Que no haya índice es lo que hace que el
   **número de archivos** sea el coste dominante de cada lectura, y por eso
   la memoria se consolida sola (ver abajo), y el cache de notas lleva
   techo (LRU) porque un proceso que corre todo el dia no puede crecer sin fin: la respuesta a «esto crece» no
   es una base de datos, es tirar lo que no había que recordar.
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
                           |        |
             core/chat.py <+        +--> skills/*.py --> memory/vault.py   (markdown)
             (hilo, RAM)                            --> system/ports.py   (Protocol)
                                                    --> core/engine.py    (EngineSwitch)
                                                          |          |
                                                  core/policy.py   system/win32/ · files.py · net.py
                                                          |
                          core/bus.py --> desktop/bridge.py --> QML --> View3D
                               ^
                               +-- trabajo de fondo (skills/taller.py) --> core.say --> friday.py
```

`friday.py` es el único que conoce a todos. Es a propósito. También sostiene
el **ama de llaves** (`_memory_keeper`), que consolida el diario viejo cada
tantas horas bajo el mismo candado que un turno.

El trabajo que tarda minutos vuelve por `core.say`, no por el turno: quien lo
emita habla, aunque el turno que lo pidio se cerrara hace rato.

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

## El taller: delegar es otro permiso, no «escribir un archivo»

`skills/taller.py` le pasa un encargo hablado a un motor agentico dentro de un
repo. Cinco invariantes, y ninguna es opcional:

1. **`policy.can_delegate()`**, con `policy.agent_roots` como unica fuente de
   proyectos. **No hereda de `write_roots`** — poder guardar un briefing en
   Documentos no es poder refactorizar ahi. Vacia = capacidad apagada.
2. **El proyecto se reconoce contra el disco.** Gana el nombre mas largo; si
   empatan dos carpetas, no gana ninguna y se pregunta. Una raiz con marca de
   repo (`.git`, `pom.xml`...) **es** el proyecto: no se listan sus hijos, o
   «metete en src» seria ambiguo entre los cuatro `src` que tengas.
3. **Leer no confirma, escribir si.** Y una tarea cuyo verbo no se reconoce
   cuenta como escritura: no entender la intencion no es razon para asumir la
   version inofensiva.
4. **`bypassPermissions` esta clavado a no en `core/engine.py`**, aunque el
   toml lo pida. Y la **caja de herramientas se filtra contra la politica**:
   `read_tools`/`write_tools` salen del toml, asi que sin filtro meter
   `Bash` en la lista de lectura —que corre sin confirmar— era ejecucion
   arbitraria con `allow_shell` en false. Declarar algo en el toml no es
   concederselo (regla 6).
5. **No bloquea el turno.** `_lanzar()` devuelve el acuse y el resultado sale
   por `core.say`. Si esto se rompe, FRIDAY se queda muda los minutos que dure.

La skill pregunta por la **capacidad** (`Engine.agentic_capable`), nunca por la
marca: es lo que mantiene viva la regla 3 en la unica skill que de verdad
necesita un modelo concreto. `EngineSwitch.agentic_spec()` devuelve quien sabe
hacerlo **sin conmutar** el modelo con el que estabas conversando.

## La conversacion: `core/chat.py`

Los ultimos turnos en RAM. **No es memoria** (regla 1): se pierde al cerrar, y
lo que merece recordarse se dice y acaba en el vault.

El paso de **seguimiento** en `router.decide()` va antes del enrutado rapido y
tiene que ganarle: «y eso cuanto cuesta» dispara el `\bcuanto\b` de `metricas`
y sin el te devuelve el uso de CPU. Tres condiciones a la vez — hilo vivo,
anafora (`FOLLOWUP`), y **ningun verbo de accion** (`ACTION`), que es lo que
deja «abre eso» en `sistema`.

`_freeform()` responde en **prosa, sin contrato JSON**, al reves que las
skills. Pedir JSON para conversar encoge las respuestas a una frase de tramite
y con un 8B rompe el formato cada tanto. La voz corta por frases enteras
(`_for_voice`); el panel recibe todo.

## La memoria se poda sola: `memory/consolidate.py`

Cada día hablado deja una nota en `raw/` y casi todas sus líneas caducan al
cumplirse. Sin índice (regla 1), cada archivo que sobra se paga en **todas**
las búsquedas. Cada 12 h, `friday.py::_memory_keeper` funde las diarias de más
de 14 días en `raw/Memoria consolidada.md` y retira los originales.

Cuatro invariantes:

1. **Python clasifica, el motor comprime.** Que un apunte sea rutina es
   cuestión de forma («abre», «sube», «cierra») y lo resuelve una regex. Lo
   que necesita criterio es fundir veinte apuntes en dos frases. Por eso la
   consolidación **funciona con el motor caído**: los esenciales pasan tal
   cual. Peor resumen, pero no es pérdida.
2. **Nada se retira antes de estar escrito.** Se relee el consolidado *del
   disco* y se comprueba que el rango esté. Del otro lado está el único
   ejemplar.
3. **Solo diarias de `raw/`** — tipo `daily` **y** zona `raw`. Ni `wiki/` ni
   `outputs/`: ahí están las notas con nombre propio y las que se citan por
   [[enlace]]. Resumirlas sería reescribirle sus notas al usuario.
4. **Retirar pasa por `policy.can_prune()`**, el único permiso que *quita*
   algo. No mira `write_roots` —el vault no está ahí— sino la frontera del
   vault. Y no borra: mueve a `vault/.trash/`, que `Vault.files()` ya no
   recorre, así que sale de búsquedas el mismo día y del disco a los 30.
   Sin política, se resume pero no se retira.

5. **Solo se retira lo que no cambio desde que se leyo.** `plan` corre
   fuera del candado y `commit` dentro, con minutos de motor en medio.
   Lo que el usuario escriba en esa ventana no esta en el resumen, asi
   que retirarlo seria perderlo. `Plan.huellas` guarda `(mtime, size)`
   de cada fuente y `commit` las revalida.

Las tres fases —`plan`, `summarize`, `commit`— están separadas y **no es
estética**: las dos primeras son consultas lentas sin efecto y la tercera es
el único comando. El ciclo autónomo toma `_busy` solo para `commit`. Envolver
las tres en el candado dejó a FRIDAY sin responder, con el HUD clavado en
«pensando», durante toda la llamada al motor (ver trampas).

El keeper habla por `core.info`, **nunca** por `core.say`: una asistente que
te interrumpe para contarte que ha ordenado sus propios archivos es una
asistente que interrumpe.

## Latencia: dónde se va el tiempo

Un turno hablado por `claude_code` cuesta ~4 s **por llamada**, casi todo
arranque de Node e ida y vuelta a la API. Así que lo que importa no es
optimizar Python, es **no hacer dos llamadas donde basta una**:

- Una conversación gastaba dos — clasificar y responder. El paso `chat-fast`
  del router se queda con la segunda cuando ninguna skill reconoció nada, no
  hay verbo de acción y la frase es corta. Medido: 9,6 s → 5,8 s.
- `Vault.read` cachea la nota parseada con `(mtime, size)` como clave. No es
  un índice (regla 1): vive en RAM y se reconstruye leyendo archivos. Un
  turno recorre el vault varias veces —`search`, `stats`, el grafo— y sin
  esto lo reparsea entero cada vez. **Toda escritura invalida su entrada
  antes de tocar el archivo**, o dos escrituras en el mismo tick del reloj
  devolverían contenido viejo.

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
- **`enum_schema` no exige ningun campo si no se lo dices.** El default era
  «todos obligatorios», que es justo lo que esta medido como malo: un
  campo obligatorio no se piensa, se inventa. Exige solo lo que necesitas
  para actuar.
- **Toda llamada con contrato JSON va por `core/engine.py::ask_json`**, nunca
  por `complete()` + `extract_json()` a mano. Concentra las cuatro cosas que
  hacen que el contrato aguante con un 8B: modo JSON del backend
  (`format: json` en Ollama, `response_format` en el dialecto OpenAI),
  temperatura 0, **sin persona**, y una segunda pasada de rescate. Y **no le
  pases `ctx.cfg.persona()`**: un tono no cabe dentro de un JSON.

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

**Los picos** (`ThoughtSpikes`) son la capa que mide *cuánto* tarda, no *si*
está ocupada: la agitación de los nodos satura en cuanto empieza a pensar.
Cada aguja es un tramo de espera cumplido y el reloj vive en
`desktop/bridge.py`, no en QML — es un `QTimer` y tiene que nacer en el hilo
de Qt. Ese reloj cuenta también el **trabajo de fondo** (`agent.started` →
`agent.done`): un encargo al taller dejaba el estado en reposo y la ventana
diciendo que no pasaba nada durante minutos.

Dos cosas que no son opcionales ahí:

- **La dirección de la aguja `i` no puede depender de cuántas haya.** Con el
  reparto habitual (`i / n`) las ya dibujadas se reacomodan en cada
  aparición, y eso se lee como un fallo, no como crecimiento. Va una
  secuencia de baja discrepancia evaluada en `i`.
- **`effort` se cuantiza a centésimas en el puente.** Alimenta una geometría
  que se reconstruye al cambiar; sin cuantizar serían once reconstrucciones
  por segundo por cambios que nadie ve.

## Trampas conocidas (ya nos mordieron)

### El candado del turno

- **`Bus.emit` espera a los handlers en línea.** No es fire-and-forget: el
  `await` no vuelve hasta que todos los suscriptores terminaron. Un handler
  lento retrasa a quien emitió.
- **Nada que tarde puede sostener `friday.py::_busy`.** Es el candado que
  serializa los turnos: mientras esté tomado, una petición nueva se queda
  esperando **antes** del router, así que no hay `router.decided` ni
  `skill.result` y el HUD se queda en «pensando» sin límite visible. Pasó con
  el ama de llaves: consolidaba dentro del candado y la llamada al motor
  puede irse a los 180 s del timeout. Regla: dentro del candado solo va lo
  que muta; lo lento se prepara fuera y, si hay turno en curso
  (`_busy.locked()`), el mantenimiento se salta el ciclo.
- **El trabajo pesado va en `asyncio.to_thread`.** Recorrer el vault entero
  en el bucle de eventos congela el HUD y retrasa cada evento del bus.

### Nada puede fallar en silencio

- **No uses `print` para reportar un fallo.** Produccion arranca con
  `pythonw.exe`: sin consola `sys.stdout` es None y CPython **descarta el
  `print` sin decir nada**. El rastro se perdia justo en el unico modo en que
  el programa corre siempre, y seis de esos `print` estaban en `voice/tts.py`
  — el fallo mas dificil de diagnosticar era el que menos huella dejaba. Va
  por `Bus.report` (o `on_error`, si el modulo no puede ver el bus).
- **Reportar un fallo no puede reemitirse por el bus.** Si el que fallo estaba
  suscrito al tema del error, emitir ahi lo llama otra vez: bucle.
  `Bus.report` escribe en `_history` y en la bitacora, y no pasa por `emit`.
- **Un `Future` de `run_coroutine_threadsafe` sin `add_done_callback` se traga
  la excepcion.** El hilo que la provoco ya siguio a lo suyo.

### Motor y sistema
- **Windows + npm shim**: pasar prompts largos por argv a `claude.CMD` los
  corrompe. Van por **stdin**.
- **Un campo de metadatos que falta no es una negativa.** `ordenador` trataba
  la ausencia de `confianza` como 0.0, la comparaba contra el umbral y
  contestaba «no me quedó claro» **con la acción ya elegida correctamente**.
  Un modelo pequeño omite campos accesorios todo el rato. El guardia nunca fue
  ese número: es el catálogo (lista blanca) + el puerto + la política.
- **La persona pesa 4 KB y es de tono.** Mandarla como system en una llamada
  que solo tiene que devolver `{"accion": ...}` es pedir dos cosas
  incompatibles: un 8B se pone a hablar en personaje y se pierde el turno.
  Ahí el modelo no falló; falló el prompt.

### Prompts que aguantan un 8B (medido con `llama3.1:8b`)

Lo que sigue no es teoría: son cuatro cosas que se midieron una por una y que
mueven el acierto de 6/12 a 12/12 en la elección de acción del catálogo.

- **La petición del usuario va AL FINAL del prompt**, pegada a la respuesta.
  Este cambio solo: 6/12 → 12/12. Con la frase arriba del catálogo, el modelo
  elegía la primera entrada de la lista casi siempre. Vale para cualquier
  prompt de esta base: contexto primero, petición al final.
- **El hueco que dejas es la respuesta que te dan.** La plantilla del contrato
  decía `"confianza": 0.0` y el modelo devolvía `0.0` literalmente, en todas.
  Pon valores de ejemplo **plausibles**, nunca ceros ni `""`.
- **Los ejemplos llevan el argumento**, no solo la frase: `no te oigo -> +20`,
  no `no te oigo`. La descripción explica el signo en abstracto; el ejemplo lo
  enseña. Sin eso acertaba la acción y erraba la dirección.
- **Un campo obligatorio en el esquema no se piensa: se inventa.** Marcar
  `confianza` como `required` hacía que la rellenara con `0`. Requiere lo que
  necesitas para actuar; deja opcional lo que solo es una señal.
- **El esquema no mejora la precisión, cierra una clase de fallo.** Con y sin
  `enum` el acierto fue el mismo (12/12); lo que cambia es que inventarse un
  nombre pasa a ser imposible en vez de estar mal. Se mantiene por eso.
- **Las palabras vacías envenenan el contexto.** `Vault.search` puntuaba con
  «que» y «los», así que casi cualquier pregunta traía alguna nota — y esa nota
  se inyecta en la conversación libre. Un modelo grande la ignora; uno pequeño
  responde sobre ella.
- **El catalogo de apps no es el Menu Inicio.** Ni los juegos de Steam ni las
  apps empaquetadas dejan `.lnk`. Son cuatro fuentes en `refresh()`: menu,
  `Get-StartApps`, `steamapps/*.acf` y PATH. Y **hay varias bibliotecas de
  Steam** — las rutas estan en `libraryfolders.vdf`, no asumas una sola.
- **`Get-StartApps` entrega ANSI si no fuerzas UTF-8.** PowerShell 5.1 usa la
  pagina de codigos del sistema y cualquier nombre acentuado llega roto. Va
  `[Console]::OutputEncoding=[Text.Encoding]::UTF8;` delante del script.
- **`git status` en un directorio que cuelga de otro repo reporta el padre.**
  Un temporal dentro de un perfil versionado sale «sucio» por cosas que no
  tienen nada que ver. Va acotado con `-- .` (ver `taller._git_sucio`).
- **Todo proceso hijo va con `NO_WINDOW`** (`core/proc.py`). FRIDAY corre sin
  consola, así que Windows le crea una a cada hijo: una ventana negra
  parpadeando en cada turno hablado, en cada refresco del catálogo y en cada
  `git status`. Si añades un `subprocess`, pasa el flag.
- **El arranque del binario `claude` son ~200 ms, no los 3 s del turno.** Un
  turno corto por `claude_code` tarda 3,3-3,7 s; el resto es inicialización
  de Claude Code y la ida y vuelta a la API. Si buscas latencia, el camino es
  `anthropic_api` (HTTP directo), no mantener un proceso vivo.

### Una skill con efecto no puede tener rama por defecto que actúe

El 17/08/2026, con un modelo local, «Descríbete a ti misma en dos palabras»
se enrutó a `sistema` con confianza 0.85 y FRIDAY **abrió el changelog de
WinRAR**: `_open` era el `else` de la skill, así que cualquier error de
enrutado se convertía en un programa lanzado. Y la frase puntuó 0.45 contra
ese acceso directo porque ambas contienen la palabra «en».

El enrutado es probabilístico y siempre lo será. Lo que no puede ser
probabilístico es lo que pasa cuando se equivoca:

- **Reconoce lo tuyo, no te quedes con lo que caiga.** Si ninguna rama de la
  skill reconoce la petición, se dice y no se actúa.
- **Las palabras vacías no emparejan nada**, ni en `apps._score` ni en
  `Vault.search`. Son las que juntan dos frases que no tienen que ver.
- **Claude Code como motor** necesita `--tools ""` y `--system-prompt`; si no,
  se comporta como agente de código: intenta escribir archivos y responde en
  prosa en vez del JSON pedido.
- **`privacy.sealed()` es thread-local.** Va **dentro** del hilo que trabaja,
  no alrededor de `asyncio.to_thread(...)`.
- **Python 3.14 no sirve**: `faster-whisper` no tiene wheels. El venv es 3.12.

### Red
- **No parsees el host de una URL a mano.** `can_fetch` partia la cadena por
  `://`, `/`, `@` y `:`, y con `http://[::1]/x` el ultimo `split` dejaba
  `host = "["`. O sea que el chequeo de `::1` escrito ahi mismo no podia
  dispararse nunca. Entraban ademas `2130706433` y `0x7f000001` (127.0.0.1 en
  decimal y en hex, que Windows resuelve), IPv6 entero, `0.0.0.0` y
  `169.254.169.254`. Va `urlsplit().hostname` + `ipaddress`, y **una sola**
  comprobacion —`is_private`— que ya cubre loopback, RFC1918, enlace local,
  ULA y sin especificar. Escribir los rangos a mano es lo que dejaba IPv6
  fuera.
- **Un nombre publico puede resolver a 127.0.0.1.** La comprobacion literal no
  puede verlo; hace falta DNS. Va en `policy.resolves_to_local`, **aparte** de
  `can_fetch`: uno es puro y decide en microsegundos, el otro bloquea. Los une
  `system/net.py::authorize`, que corre el caro en un hilo.
- **Autorizar un redirect despues de seguirlo no sirve de nada.** Con
  `allow_redirects=True` la peticion a la URL interna **ya se hizo**; tirar la
  respuesta no deshace un GET al router. Los saltos se siguen a mano, con
  tope, autorizando cada uno antes de pedirlo.
- **Una `ClientSession` por peticion es un handshake TLS por peticion.**
  Medido: 247 ms → 73 ms contra `es.wikipedia.org`. La sesion compartida vive
  en `core/http.py` y la cierra `friday.py::shutdown`.
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
- **Contar GPUs no es poder usarlas.** `_has_cuda()` preguntaba
  `get_cuda_device_count() > 0` y veía la tarjeta, pero CTranslate2 carga
  cuBLAS/cuDNN en la **primera transcripción**, no al construir el modelo.
  Con el driver instalado y sin runtime CUDA 12, `load()` anunciaba
  «oidos: small/cuda/float16», el PTT se armaba, y la voz moría justo al
  hablar (`Library cublas64_12.dll is not found`). Verde al arrancar, sorda
  al usarse — y sorda es el peor fallo posible en lo único que no tiene otra
  entrada. `transcribe()` se rescata a CPU y lo cuenta por `on_error`.
- **El runtime CUDA sale de los wheels `nvidia-*-cu12`, y se registra por
  `PATH`.** Las DLL viven en `site-packages/nvidia/*/bin`, que Windows no
  mira. `os.add_dll_directory` **no** sirve: CTranslate2 las carga desde C++
  con `LoadLibrary` a secas, que ignora esos directorios. Va prepuesto a
  `os.environ["PATH"]` en `stt.py::_registrar_dlls_cuda`. Medido con
  `small`: 2615 ms en CPU → 1333 ms en GPU.
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
- **Un disparador corto y comun gana aunque la frase hable de otra cosa.** El
  puntaje no puede arreglarlo: no es un fallo suyo. Por eso el seguimiento de
  conversacion se resuelve **antes** del enrutado rapido, no compitiendo con el.
- **Llamarse como una palabra corriente es un problema de enrutado.** El
  puntaje generico regala 0.35 a la skill cuyo nombre sale en la frase, y
  «memoria» sale tanto en «consolida la memoria» como en «cuanta memoria RAM
  me queda». `skills/memoria.py` sobrescribe `matches()` como ya hacia
  `motor`: exige verbo **y** objeto, y devuelve 0 si huele a RAM. Si añades
  una skill con nombre generico, o le pones otro nombre, o le escribes su
  propio `matches`.
- **Ventana translúcida sin blur = texto ilegible.** Qt no desenfoca lo que hay
  detrás; eso lo hace el compositor (`desktop/backdrop.py`, opcional).

## Verificar cambios

```powershell
.\.venv\Scripts\python scripts\smoke_test.py     # 107 · memoria, consolidación, skills, enrutado
.\.venv\Scripts\python scripts\system_test.py    # 160 · política, puertos, red, motor, taller, PTT
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
.\.venv\Scripts\python scripts\ui_preview.py thinking --picos 14 --shot erizado.png
.\.venv\Scripts\python scripts\ui_preview.py idle --projected --shot planb.png
```

`--picos N` fija cuántas agujas lleva acumuladas: sirve para mirar el extremo
—una espera larguísima— sin esperarla.
