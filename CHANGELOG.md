# Registro de cambios

Lo que cambió, cuándo y **por qué**. Las cifras que aparecen aquí están
medidas en la máquina de referencia, no estimadas.

---

## 2026-08-18 (noche) — auditoría

Repaso de calidad, seguridad y rendimiento sobre todo el repo. Lo que sigue
son defectos encontrados leyendo y **midiendo**, no reescrituras de gusto.
Las pruebas pasaron de 236 a 267.

### Seguridad

- **`policy.can_fetch` era evadible de siete formas.** El host se sacaba
  partiendo la cadena a mano, y `[::1]` roto por `:` daba `[`, así que el
  propio chequeo de loopback IPv6 escrito ahí no podía dispararse nunca.
  Entraban: `2130706433` (127.0.0.1 en decimal), `0x7f000001` (en hex),
  `[::1]`, `[fd00::1]` y `[fe80::1]` (IPv6 entero, que no estaba cubierto),
  `0.0.0.0`, `usuario@127.0.0.1` y `169.254.169.254` (metadatos de nube).
  Ahora el host sale de `urlsplit`, las tres notaciones se normalizan con
  `ipaddress` y una sola comprobación —`is_private`— cubre loopback, RFC1918,
  enlace local, ULA y sin especificar. Un puerto no numérico también deniega.
- **Un nombre público que resuelve a 127.0.0.1 seguía entrando** (`localtest.me`).
  Se añadió `policy.resolves_to_local`, que consulta el DNS. Va **aparte** de
  `can_fetch` a propósito: `can_fetch` es puro y decide en microsegundos, y
  esto bloquea, así que `system/net.py::authorize` lo corre en un hilo. Los
  dos juntos en un único sitio, para que ninguna skill se quede con la mitad
  barata (regla 6).
- **Los redirects se autorizaban después de haberlos pedido.** Con
  `allow_redirects=True`, aiohttp ya había hecho la petición a la URL interna
  antes de que nadie pudiera mirarla; descartar la respuesta no deshace un GET
  al router. Ahora los saltos se siguen a mano, con tope de 5, autorizando
  cada uno **antes**.
- **El toml podía otorgar permisos que la política no daba.** `skills/taller`
  tomaba `read_tools`/`write_tools` del toml sin filtrarlas: meter `Bash` en
  `read_tools` convertía una tarea de solo lectura —que corre **sin
  confirmar**— en ejecución arbitraria, con `policy.allow_shell` en `false` y
  sin enterarse. Ahora `Bash`, `Task`, `WebFetch` y compañía se filtran contra
  su interruptor, y lo retirado se dice en el panel en vez de desaparecer.

### Corregido

- **Los fallos dentro de un handler del bus no dejaban rastro.** Iban a
  `print`, y producción arranca con `pythonw.exe`: sin consola `sys.stdout` es
  None y CPython se come el `print` en silencio. El rastro se perdía justo en
  el único modo en que el programa corre siempre — y seis de esos `print`
  estaban en `voice/tts.py`, o sea que el fallo más difícil de diagnosticar
  («FRIDAY se queda muda») era el que menos huella dejaba. Ahora hay
  `Bus.report`, que escribe en `_history` y en la bitácora sin reemitir por el
  bus, que sería un bucle. No queda ningún `print` fuera de los scripts.
- **`emit_threadsafe` se tragaba las excepciones** del `Future` y usaba
  `get_event_loop()`, deprecado y capaz de reventar en un hilo sin bucle.
- **El ama de llaves podía retirar una nota modificada mientras resumía.**
  `plan` corre fuera del candado y `commit` dentro, con minutos de motor en
  medio; lo que el usuario escribiera en esa ventana se retiraba sin estar en
  el resumen. `Plan` guarda ahora la huella `(mtime, size)` de cada fuente y
  solo se retira lo que sigue igual. Quinta invariante de la consolidación.
- **`skills/vault` pedía `links` al motor y los tiraba.** El grafo se
  construye leyendo `[[...]]` del cuerpo, no del JSON, así que un modelo que
  rellenaba la lista y dejaba el markdown limpio perdía el enlace.
- **`enum_schema` marcaba todos los campos como obligatorios** cuando no se
  decía nada — justo lo que este repo tiene medido como malo («un campo
  obligatorio no se piensa, se inventa»). La advertencia estaba en el
  docstring y el default hacía lo contrario. Ahora no exige nada por defecto.
- **`OpenAICompatEngine` daba un `KeyError` crudo** ante una respuesta rara,
  donde los otros tres adaptadores devuelven un `RuntimeError` con el motivo.
- **El argumento `timeout` lo ignoraban tres de los cuatro adaptadores.**
- **Las suites reventaban si stdout no era UTF-8** (tubería, redirección, CI):
  `UnicodeEncodeError` a media pasada, que parece un fallo de las pruebas.

### Rendimiento

- **174 ms menos por petición de red.** Se construía una `ClientSession` por
  llamada, o sea un handshake TCP+TLS por llamada, en los cuatro adaptadores
  del motor y en `system/net.py`. Medido contra `es.wikipedia.org`: **247 ms →
  73 ms** por petición tras la primera, con la conexión reutilizada del pool.
  Pesa justo donde no debe: `anthropic_api` existe para ahorrar el arranque de
  Node, y pagaba ese peaje por el otro lado. La sesión vive en `core/http.py`
  —la usan `core` y `system`, y `system` ya depende de `core`— y la cierra
  `friday.py::shutdown`.
- **`taller._proyectos` salió del bucle de eventos.** Recorre el disco por
  niveles con un `exists()` por cada marca de repo; en el hilo de asyncio eso
  congela el HUD al empezar el turno. `_git_sucio`, tres líneas más abajo, ya
  lo hacía bien.
- **El caché del vault tiene techo** (LRU de 512). Guardaba el cuerpo entero
  de cada nota sin límite, y la única purga vivía dentro de `all_notes()`, así
  que dependía de que llamaras a ese método. Un proceso que corre todo el día
  no tenía límite superior de RAM.

### Medido

- La ruta rápida cuesta **150-230 µs** para las 14 skills, contra ~4 s de una
  llamada al motor: 20.000× más barata. La apuesta del router se sostiene.
- `"y eso cuanto cuesta"` puntúa **0,64** contra `metricas`, por encima del
  umbral de 0,62: sin el paso de seguimiento por delante, preguntar por un
  precio devuelve el uso de CPU. La trampa documentada es real.
- `"que tal estas"` puntúa 0,00 en las 14 skills y cae en `chat-fast`.

---

## 2026-08-18 (tarde)

### Corregido

- **FRIDAY dejaba de responder y se quedaba «pensando».** El ama de llaves
  de la memoria sostenía `friday.py::_busy` —el candado que serializa los
  turnos— durante toda la consolidación, incluida la llamada al motor. Y
  `Bus.emit` espera a sus handlers en línea, así que cualquier petición hecha
  en esa ventana se quedaba esperando **antes** del router: sin
  `router.decided` ni `skill.result`, el HUD se clavaba en «pensando» hasta
  180 s, el timeout del motor.
  El `Consolidator` se partió en consulta y comando (`plan` / `summarize` /
  `commit`): lo lento corre fuera del candado, que ahora solo cubre la
  escritura, y si hay un turno en curso el mantenimiento se salta el ciclo.

### Rendimiento

- **Un turno de conversación pasó de 9,6 s a 5,8 s** (medido con
  `claude_code`). Gastaba **dos** llamadas al motor: una para preguntar a qué
  skill enrutar y otra para responder. El paso `chat-fast` del router
  resuelve la primera sin motor cuando ninguna skill reconoció nada, no hay
  verbo de acción y la frase es corta; si algo puntúa aunque sea poco, sigue
  arbitrando el motor. Se apaga con `[chat] fast_conversation = false`.
- **`Vault.read` cachea la nota parseada** con `(mtime, size)` como clave.
  Sigue sin haber índice (regla 1): es RAM que se reconstruye leyendo
  archivos. Un turno recorría el vault entero varias veces —`search`,
  `stats`, el grafo— reparseándolo cada vez.
- **La búsqueda del vault salió del bucle de eventos** (`asyncio.to_thread`).
  Recorrerlo en el hilo de asyncio congelaba el HUD justo antes de la parte
  lenta del turno.

### Cambiado

- Pasada de limpieza de comentarios en los módulos más cargados de prosa
  (motor, geometría, taller, ordenador, política, puertos, TTS, router). El
  *porqué* se conserva en una o dos líneas; el desarrollo largo ya vive en
  `CLAUDE.md`, que es donde se busca.
- `Consolidator.from_config()` sustituye a la construcción a mano que estaba
  duplicada en la skill y en el ciclo autónomo.

---

## 2026-08-18

### Añadido

- **La memoria se consolida sola** (`memory/consolidate.py`, `skills/memoria.py`).
  Cada día hablado dejaba una nota en `raw/`, y la mayoría de sus líneas
  caducan al cumplirse: *«abre Spotify»*, *«sube el volumen»*. A los seis
  meses eso son cientos de archivos que no recuerdan nada y que **toda**
  lectura del vault recorre, porque aquí no hay índice (regla 1): `search`
  abre y puntúa archivo por archivo. Ahora, cada 12 h, las diarias de más de
  14 días se funden en `raw/Memoria consolidada.md` y los originales se
  retiran. Menos disco y, sobre todo, menos archivos que abrir en cada
  búsqueda y en cada reconstrucción del grafo.
  Python clasifica —rutina o no es cuestión de forma, y una regex la
  resuelve— y el motor comprime lo que queda; sin motor los apuntes
  esenciales pasan tal cual, que es peor resumen pero no es pérdida.
  Nada se retira antes de releer el consolidado del disco, la retirada pasa
  por `policy.can_prune()` y los originales van a `vault/.trash/`, fuera de
  búsquedas desde el primer día y borrados a los 30. `wiki/` y `outputs/`
  no se tocan nunca.

- **Picos de pensamiento en el núcleo 3D** (`desktop/geometry.py::ThoughtSpikes`).
  La agitación de los nodos ya decía «está ocupada», pero satura enseguida:
  un turno de dos segundos y un encargo de cuatro minutos se veían igual.
  Ahora cada tramo de espera cumplido saca una aguja del globo, y el esfuerzo
  acumulado las alarga. Sigue contando mientras el taller trabaja en segundo
  plano, que es justo lo que el HUD antes no mostraba: el estado volvía a
  reposo y la ventana decía que no pasaba nada durante minutos.
  La escena anterior no cambia — los picos son una capa más.

---

## 2026-08-17

### Añadido

- **`skills/taller.py` — encargarle trabajo a un agente por voz.**
  *"Métete en mi-proyecto y revisa por qué fallan los tests"*. No bloquea el
  turno: la voz acusa recibo y el resultado vuelve por el bus (`core.say`)
  cuando el agente termina, que pueden ser minutos.
  Cinco guardias, ninguno opcional: solo trabaja bajo `policy.agent_roots`
  (vacía de fábrica), el proyecto se reconoce contra el disco y si empatan
  dos carpetas pregunta, las tareas de lectura corren solas mientras las que
  escriben esperan un «sí» hablado, avisa si el repo tiene cambios sin
  commitear, y `bypassPermissions` está clavado a no aunque el toml lo pida.

- **Catálogo de aplicaciones completo** (`system/win32/apps.py`).
  Deja de ser solo el Menú Inicio: suma `Get-StartApps` (apps de Store/UWP,
  que no dejan acceso directo) y los manifiestos de Steam de **todas** las
  bibliotecas, más una tabla de alias hablados. 191 → 283 entradas en la
  máquina de referencia. Los juegos y las apps empaquetadas ya se abren.

- **Navegador predeterminado de verdad** (`system/win32/defaults.py`).
  Puerto `DefaultApps`: FRIDAY lee las aplicaciones predeterminadas de
  Windows, abre en el navegador que elegiste y **lo nombra** («Buscando
  capibaras en Brave»). Solo `winreg`, sin dependencias nuevas.

- **Conversación con hilo** (`core/chat.py`).
  Los últimos turnos viven en RAM — no es memoria, y se pierde al cerrar a
  propósito. El enrutado gana un paso de *seguimiento* para que «y eso
  cuánto cuesta» no acabe leyendo la CPU. La conversación libre responde en
  prosa, sin contrato JSON.

- **`config/friday.local.toml`**, no versionado y fusionado encima del
  público. Es donde van las rutas de tus proyectos y tus alias.

### Corregido

- **Un error de enrutado ya no lanza programas.** El 17/08, con el modelo
  local, *«Descríbete a ti misma en dos palabras»* se enrutó a `sistema` con
  confianza 0.85 y FRIDAY **abrió el changelog de WinRAR**: `_open` era la
  rama `else` de la skill, así que cualquier fallo de enrutado se convertía
  en un programa abierto. Ahora exige un verbo de abrir y, si no reconoce
  nada como suyo, lo dice y no actúa.

- **Las palabras vacías ya no emparejan nada.** «Descríbete a ti misma en
  dos palabras» y «Que hay de nuevo en la última versión» solo comparten
  «en», y eso puntuaba 0.45 en `apps._score`. Mismo veneno en
  `Vault.search`, donde hacía que casi cualquier pregunta arrastrara una
  nota al contexto de la conversación.

- **Sin ventanas de consola** (`core/proc.py`). FRIDAY corre sin consola, así
  que Windows le creaba una a cada proceso hijo: una ventana negra
  parpadeando en cada turno hablado, cada refresco del catálogo y cada
  `git status`.

### Que los prompts aguanten un modelo local

Medido con `llama3.1:8b` sobre Ollama. Elección de acción del catálogo:
**6/12 → 12/12**, el mismo resultado que Sonnet 5. Por orden de impacto:

1. **La petición del usuario va al final del prompt.** Ella sola: 6/12 →
   12/12. Con la frase arriba del catálogo, el modelo elegía la primera
   acción de la lista casi siempre.
2. **Los huecos de las plantillas se copian literalmente.** El contrato
   mostraba `"confianza": 0.0` y el modelo devolvía `0.0` siempre — bajo el
   umbral, así que se descartaba cada acción ya elegida.
3. **Un campo de metadatos ausente no es una negativa.** Una confianza baja
   *dicha* sí se respeta; que falte, no.
4. **La persona fuera de las llamadas con contrato.** 4 KB de carácter como
   system prompt en una llamada que solo devuelve `{"accion": …}` son dos
   peticiones incompatibles.
5. **Los ejemplos llevan el argumento**: `no te oigo -> +20`, no `no te
   oigo`.

Todo pasa ahora por `core/engine.py::ask_json`, que centraliza el modo JSON
del backend (`format` en Ollama, `response_format` en el dialecto OpenAI),
el esquema de lista cerrada, temperatura 0 y una pasada de rescate.

### Medido, para quien busque latencia

| | |
|---|---|
| arrancar el binario `claude` | 0,2 s |
| turno corto por `claude_code` | 3,3-3,7 s |
| turno corto por Ollama local (HTTP) | 0,3-0,6 s |

El arranque del proceso son 200 ms, no los 3 s: mantener una instancia viva
recupera bastante menos de lo que parece. Ver el ROADMAP.

### Pruebas

64 → **68** de humo, 77 → **129** de sistema.
