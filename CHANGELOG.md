# Registro de cambios

Lo que cambió, cuándo y **por qué**. Las cifras que aparecen aquí están
medidas en la máquina de referencia, no estimadas.

---

## 2026-08-22 (tarde) — una frase puede pedir dos cosas

«Busca este archivo y ábrelo» es de lo primero que le pide cualquiera, y
terminaba con FRIDAY leyendo una lista de rutas: `archivos` busca, `sistema`
abre, y el router elegía **una skill por turno**. Hacía las dos mitades y
ninguna frase las juntaba. Las pruebas de sistema pasaron de 193 a 211.

- **Traspaso tipado, no un planificador.** Una skill devuelve una `Entrega`
  (`kind`, `valor`, `etiqueta`) y otra la consume si declara `acepta`. La
  segunda **no reinterpreta la frase**: recibe el objeto resuelto o no corre.
  «Ábrelo» suelto haría que `sistema` buscara una aplicación llamada «lo»,
  que es la forma exacta del incidente del 17/08.
- **Partir de más era el riesgo entero**, así que las reglas son estrechas:
  conector explícito, verbo de acción en **las dos** mitades, y corte por el
  último conector que cumpla. Eso salva «busca el informe y el contrato» (una
  búsqueda de dos cosas) y «busca el de ventas y marketing y ábrelo» (el
  primer «y» está dentro del nombre). Tope duro de dos mitades: encadenar tres
  cosas sin ver nada intermedio es donde una frase mal oída deja de poder
  repararse.
- **La cadena se detiene ante una confirmación pendiente.** Encadenar por
  encima de un «sí» que el usuario aún no ha dado es ejecutar lo no
  autorizado. Y si la segunda mitad no puede correr, se hace la primera y **se
  dice** — media tarea anunciada entera es peor que media tarea.
- **`policy.can_open`**, permiso nuevo. `can_launch` recibe algo del catálogo
  curado; esto recibe una ruta que salió de rastrear tu disco. «Busca el
  instalador y ábrelo» encuentra un `.exe` en Descargas, y abrirlo sería
  ejecución arbitraria dictada esquivando `allow_shell`. La lista de
  extensiones ejecutables no sale del toml: es el suelo. Incluye `.lnk`.
- **`AppLauncher.open_path`**: abrir un archivo con lo que el usuario tenga
  asociado. Método aparte de `launch` porque consulta otro permiso.

### El pronombre pegado (fallo preexistente)

En español el pronombre se pega al imperativo y el verbo **lleva tilde**:
«ábrelo». `\babre\b` no casa con ninguna de las dos formas — la frontera de
palabra exige un no-alfanumérico detrás y ahí hay una «l». Estaba roto en tres
sitios con tres síntomas distintos: «ábrelo» no contaba como orden en `ACTION`
—así que `is_followup` lo tomaba por continuación de la charla y acababa en
conversación—, no enrutaba a `sistema`, y no entraba en su rama de abrir. La
forma más natural de pedirlo era la que menos funcionaba. Ahora es
`core/lang.py::ENCLITICO`, una vez.

---

## 2026-08-22 — el reloj, las radios y oír mejor

Tres frentes: FRIDAY deja de esperar a que le hablen, gana las capacidades
que el ROADMAP pedía desde el 16/08, y se equivoca menos al recibir órdenes.
Las pruebas pasaron de 267 a 323 (130 de humo + 193 de sistema).

### Deja de esperar a que le hablen

- **El reloj (`core/scheduler.py`).** Recordatorios que salen de la agenda del
  vault y trabajos declarados en `[[schedule.jobs]]`. `due()` es **puro** —
  recibe un instante y devuelve qué toca, sin tocar nada; los efectos viven en
  `friday.py::_programador`. Misma división que `plan`/`commit` en la
  consolidación y por la misma razón.
- **Un trabajo dice una frase**, no llama a una skill. Entra por el router
  como si la hubieras dicho tú, con su política y su confirmación: el reloj no
  es una credencial. A cambio, cualquier capacidad nueva es programable el día
  que existe, sin tocar el programador.
- **La marca de «ya lo disparé» va a la nota diaria**, no a un archivo de
  estado (regla 1). Reiniciar a media mañana no repite el recordatorio de las
  nueve, y de paso queda escrito en el diario que te avisó.
- **Un recordatorio habla por `core.say`, el mantenimiento por `core.info`.**
  Es la regla del ama de llaves aplicada al revés a propósito: contarte que
  ordenó sus archivos es interrumpir, avisarte de una reunión no.
- **Puerta de salida (`system/notify.py`)**: ntfy, webhook o Telegram. Existe
  por el caso que la voz no cubre — un encargo al taller tarda veinte minutos
  y a esa hora puedes estar en otra habitación. **Solo sale, nunca entra**
  (regla 8 nueva). `policy.can_notify` es propio y está apagado de fábrica:
  esto manda datos tuyos a un tercero, que no es lo mismo que traerlos.

### Las capacidades que faltaban

- **Bluetooth, wifi y brillo.** Puertos `RadioControl` y `DisplayControl`,
  cinco entradas nuevas en el catálogo de `ordenador`. Las radios por WinRT
  (`winsdk`, opcional); el brillo por WMI, que ya venía con `pywin32`.
  Cableados por separado a propósito: sin `winsdk` te quedabas también sin
  brillo, que no tiene nada que ver.
- **Ambas APIs tienen afinidad de hilo** y de formas distintas — WinRT quiere
  un bucle de eventos que no puede ser el de FRIDAY, WMI quiere
  `CoInitialize`. Un hilo único con tope de espera, la lección de
  `voice/tts.py` aplicada antes de que costara una sesión.
- **Encender una radio no se confirma; apagarla sí.**
  `can_control(kind, desconecta=True)`. Apagar el wifi te deja sin red y puede
  dejar muda a la propia FRIDAY si el motor es remoto. Confirmar también lo
  inofensivo entrena a decir «sí» sin escuchar.
- **«No te entendí» y «no sé hacerlo» dejan de ser la misma frase.** El caso
  del 16/08: se pidió dos veces *«desactiva el Bluetooth»* y contestó «no me
  quedó claro», habiéndolo entendido perfectamente. Ahora son tres respuestas
  distintas, incluida *«sé hacerlo, pero en este equipo no puedo»*.
- **El taller se puede mirar y parar.** Registro de encargos con estado:
  «¿cómo va lo de mi-proyecto?» y «déjalo». Antes solo había un `set` de
  tareas de asyncio, que bastaba para que el recolector no se las llevara y
  para nada más.

### Se equivoca menos al recibir órdenes

- **`core/lang.py`**, con la normalización del habla que estaba duplicada en
  tres sitios y resuelta distinto en cada uno. `numero()` entiende «volumen al
  veinte» y «a la mitad»; antes `int("veinte")` lanzaba y se caía al valor por
  defecto, poniendo el volumen al 50 cuando le habías pedido veinte.
- **El riesgo entra en el enrutado.** Cada skill declara `riesgo`; el router
  le exige más a las que tienen efecto. **Lo que separa una orden de un
  accidente es el verbo, no el puntaje**: la primera versión subía el listón a
  toda skill de efecto y dejaba «abre eso» fuera del camino rápido, que es
  castigar justo el caso donde hay que ser instantánea.
- **`_sospechoso`**, la defensa que sí cubre el incidente del 17/08: si el
  motor manda a una skill con efecto una frase sin verbo cuyos disparadores
  puntuaron cero, cae a conversación. Reproducido en las pruebas.
- **El eco.** La confianza del STT viaja con el turno hasta el router, y por
  debajo de `OIDO_DUDOSO` una orden **con efecto** se repite antes de
  ejecutarla. Cubre el único fallo que ningún guardia posterior puede ver: la
  política autoriza la acción correcta para una frase que nadie dijo. Solo con
  efecto — confirmar de más es como se pierde la confirmación que importaba.
- **`metricas` deja de acaparar vocabulario técnico.** *«Se me cayó el
  servidor de producción y tengo una demo en veinte minutos»* devolvía el uso
  de CPU. Ahora una palabra débil solo cuenta si la frase además pregunta.
- **«Toda la mañana» ya no es una fecha.** `mañana` tiene dos significados y
  el disparador de `agenda` se llevaba los dos.

### Resiliencia

- **`_supervisar()`** para las tareas de fondo. `asyncio.create_task` no
  guarda referencia fuerte —el recolector puede llevarse un bucle a medio
  correr— y sin `add_done_callback` la excepción que lo mató no la ve nadie.
  Un bucle de fondo que muere en silencio parece que funciona.
- **`net.post()` no sigue ni una redirección**, al revés que `fetch`: en un
  POST el salto reenviaría el cuerpo a un destino que el usuario no escribió.
- **La tabla de despacho de `ordenador` es un método** (`_manos`), no un dict
  enterrado. La prueba que fija «toda acción declarada está cableada» llevaba
  los nueve nombres transcritos a mano, así que declarar una capacidad rompía
  la prueba hasta que la editabas — la forma de prueba que no prueba nada.
  Ahora compara contra la tabla real, en las dos direcciones.
- **`--check` deja de mentir.** «No en esta plataforma» era falso para las
  radios (falta un `pip install`) y para los avisos (falta un destino en el
  toml). Mandar a alguien a buscar un problema de Windows cuando le falta un
  paquete es el mismo fallo que decir «no te entendí» cuando no sabes hacerlo.

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
