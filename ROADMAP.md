# Pendientes

Lo que falta, por qué falta y dónde tocarlo. Nada aquí es una idea suelta:
todo salió de usar FRIDAY o de un límite que se dejó puesto a conciencia.

Cuando algo se cierre, se borra de aquí y se documenta en el `README.md`.

---

## Prioridad alta

### ☐ Encargarle trabajo a Claude Code por voz

*"Métete en `mi-proyecto` y revisa por qué fallan los tests"*, y que lo haga.
La terminal, pero hablando.

**Lo que YA existe:** `ClaudeCodeEngine.complete()` acepta `agentic=True` y en
ese modo devuelve las herramientas (`--allowed-tools`) y el modo de permisos
(`--permission-mode`) en vez de correr como LLM puro. Está escrito y
documentado desde el principio.

**Lo que falta:**

1. **Nadie lo llama.** `agentic=True` no aparece en ninguna skill; hoy es
   código muerto. Hace falta una skill `taller` (o similar) que lo invoque.
2. **El directorio está fijo.** `self.cwd = str(cfg.root)` se decide al
   construir el motor, así que todo correría dentro del repo de FRIDAY. Para
   *"métete en X"* hace falta pasar el `cwd` **por llamada**, no por
   constructor.
3. **Resolver el directorio hablado.** *"mi proyecto"* → una ruta real. El
   puerto `FileIndex` ya sabe buscar; hará falta una lista de raíces de
   trabajo en el toml (`[taller] roots`) para no ponerse a adivinar por todo
   el disco.
4. **Devolver el trabajo.** Claude Code en modo agéntico puede tardar
   minutos. La respuesta hablada tiene que ser *"voy con ello"* y el
   resultado llegar después por el bus, no bloquear el turno.

**Lo que hay que pensar antes de escribir una línea.** Esto es un agente con
permiso de escritura, dirigido por un STT que se equivoca — mira la bitácora:
*"desactivar el Bluetooth"* llegó como *"Desactual Bluetooth"*. Un
*"borra los temporales"* mal transcrito dentro de un repo real es una tarde
perdida. Como mínimo:

- **Raíces declaradas.** Solo directorios de una lista blanca del toml.
  Fuera de ahí, no. Reutilizar el criterio de `policy.write_roots`.
- **Confirmación hablada siempre**, repitiendo *qué* tarea y *en qué ruta*,
  antes de lanzar. La infraestructura de `PendingAction` ya está.
- **Tareas de solo lectura sin confirmar, las que escriben con confirmación.**
  «Revisa», «explica» y «busca» no son lo mismo que «arregla» o «refactoriza».
- **Nunca `--permission-mode bypassPermissions`.** Si la tarea necesita eso,
  la respuesta correcta es que la hagas tú en la terminal.
- Que el repo esté limpio (`git status`) antes de dejar que escriba, o
  avisar de que hay cambios sin commitear que podría pisar.

### ☐ Juegos de Steam y aplicaciones de Microsoft Store

**Comprobado en la máquina el 16/08/2026, y parte de esto ya funciona:**

| Petición | Hoy |
|---|---|
| *"abre Brave"* | ✅ funciona — `Brave.lnk` está en el Menú Inicio |
| *"abre Steam"* | ✅ funciona — el cliente sí está |
| *"abre Geometry Dash"* | ❌ ninguno de los 8 juegos instalados aparece |
| *"abre Spotify"* | ❌ sin coincidencia (no deja `.lnk` en el Menú Inicio) |
| *"abre vscode"* | ❌ solo responde a `code` |

**La causa:** `WindowsAppCatalog.refresh()` construye el catálogo con
`rglob("*.lnk")` sobre el Menú Inicio. Los juegos de Steam no ponen accesos
directos ahí, y las apps empaquetadas (Store/UWP) tampoco.

**Juegos de Steam.** Están en `steamapps/appmanifest_*.acf`, un VDF plano con
`"appid"` y `"name"` — se parsea con una regex, sin dependencias. Se lanzan
con `steam://rungameid/<appid>`, que `os.startfile` ya abre porque es un URI
y el lanzador contempla `kind="uri"`. Ojo: puede haber **varias bibliotecas**;
las rutas están en `steamapps/libraryfolders.vdf`, no asumas una sola.

**Apps de Store/UWP.** `Get-StartApps` (PowerShell) devuelve `Name` + `AppID`
de *todo* lo que el usuario ve en el menú, incluidas las empaquetadas, y se
lanzan con `shell:AppsFolder\<AppID>`. Es una fuente más completa que globear
`.lnk`. El coste es levantar PowerShell una vez por refresco — aceptable
porque el catálogo se cachea (TTL de `[system] app_cache_s`).

**Alias.** `vscode`→`code`, `vs code`, `chrome`→`google chrome`. Una tabla de
sinónimos en el toml antes que tocar `_score()`.

**Dónde va:** todo en `system/win32/apps.py`. No hace falta puerto nuevo ni
cambiar `AppCatalog`: son fuentes adicionales dentro de `refresh()`.

### ☐ Controles de sistema: Bluetooth, wifi, brillo

**De dónde sale:** sesión del 16/08/2026. Se le pidió dos veces *"desactivar
el Bluetooth"* y contestó que no lo tenía claro. No es un fallo del
planificador — esa capacidad no existe en el catálogo, y prefirió admitirlo
antes que inventarse una acción parecida. Pero es una petición
razonabilísima para un asistente de escritorio.

**Dónde va:**
- Puerto nuevo `RadioControl` / `DisplayControl` en `system/ports.py`.
- Implementación en `system/win32/desktop.py` (o un `radios.py` aparte si
  crece).
- Entradas nuevas en `CATALOGO` de `skills/ordenador.py` — recuerda que la
  acción la elige el motor, así que basta con declararla bien.
- Interruptor propio en `policy.can_control()`. **No lo metas dentro de
  `media`**: apagar el wifi te deja sin red, subir el volumen no. El criterio
  de separación es el riesgo, no la comodidad.

**Por dónde empezar:** Bluetooth y wifi por `Windows.Devices.Radios` (WinRT);
brillo por WMI (`WmiMonitorBrightnessMethods`). Antes de añadir una
dependencia, comprueba si `netsh`/PowerShell bastan — pero entonces pasa por
`policy.can_shell()`, que está apagado por defecto y no es casualidad.

### ☐ Decir qué no sabe hacer, en vez de "no me quedó claro"

**De dónde sale:** la misma sesión. Cuando el motor no encuentra acción en el
catálogo, `skills/ordenador.py` responde *"No me quedó claro qué quieres que
haga"*. Es engañoso: sí entendió la petición, lo que pasa es que **no tiene
esa capacidad**. Son dos fallos distintos y el usuario merece saber cuál es.

**Qué debería decir:** *"No sé desactivar el Bluetooth, Jefe. Eso todavía no
lo tengo."* — nombrando lo que se le pidió.

**Dónde va:** `OrdenadorSkill._decidir()` ya recibe del motor un campo
`porque`. Basta con distinguir dos casos en el JSON de respuesta: *no entendí*
frente a *entendí pero no está en la lista*. Ojo con el contrato del prompt:
tiene que seguir funcionando con un modelo local de 8B (regla 3 del
`CLAUDE.md`).

---

## Prioridad media

### ☐ Enrutado: frases con vocabulario de sistema van a `metricas`

**De dónde sale:** pruebas del 16/08/2026. *"Se me cayó el servidor de
producción y tengo una demo en veinte minutos"* enruta a `metricas` en vez de
a conversación libre. Es preexistente, no lo introdujo ningún cambio reciente.

**Causa:** los disparadores de `metricas` son palabras sueltas de dominio
técnico que aparecen de forma natural en frases que no piden métricas. El
puntaje mide especificidad del disparador, pero un disparador corto y común
sigue ganando cuando nadie más compite.

**Dónde va:** `skills/metricas.py::triggers`. Fijar el caso en
`scripts/smoke_test.py` junto a los otros pares que se pisan a propósito.

### ☐ Instalar la voz de Piper

`[voice.tts] engine = "piper"` está configurado, pero no hay ningún `.onnx` en
`models/piper/`, así que siempre cae a SAPI5. Funciona, pero Piper suena
bastante mejor. El código de carga y de reproducción ya está y es
multiplataforma — solo falta el modelo.

---

## Decisiones tomadas a conciencia, no olvidos

No están pendientes: están **decididas**. Si algún día se cambian, que sea a
sabiendas y no por creer que se olvidaron.

- **`allow_shell = false`.** Ejecución de comandos arbitrarios dictados por
  voz, con un STT que se equivoca. Si se abre, que sea con lista blanca de
  comandos, nunca con texto libre.
- **Nada de apagar ni reiniciar** en `SessionControl`. Una orden mal
  transcrita no puede costarte el trabajo sin guardar. Bloquear y suspender
  sí, y aun así se confirman.
- **No se raspan páginas de resultados de buscadores.** Cambian el HTML cada
  pocas semanas y muchos lo bloquean; un asistente apoyado en eso empieza a
  mentir en cuanto se rompe.
- **La memoria es markdown y nada más.** Ninguna base de datos, ningún índice
  persistente.

---

## Algún día

- **`system/linux/`** — los `Protocol` de `system/ports.py` están para esto:
  implementarlos para X11/Wayland no debería tocar ni una skill. Es la prueba
  de fuego de que la inversión de dependencias vale de algo.
- **Piper en streaming** — sintetizar por frases y empezar a hablar antes de
  tener el audio entero. Con respuestas largas se nota la espera.
- **Historial de conversación** — hoy cada petición es independiente. Un
  "y eso cuánto cuesta" después de una respuesta no tiene a qué referirse.
