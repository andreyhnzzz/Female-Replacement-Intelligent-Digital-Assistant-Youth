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
  <img src="https://img.shields.io/badge/Licencia-MIT-FFB300?style=for-the-badge&logo=opensourceinitiative&logoColor=white" alt="Licencia MIT">
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
.\scripts\build_exe.ps1          # FRIDAY.exe para arrancar con doble clic (opcional)
.\scripts\run.ps1                # acompañante + voz
```

**Pulsa F9, habla, pulsa F9 otra vez.** El núcleo aparece en la esquina, el
icono queda en la bandeja del sistema.

`build_exe.ps1` deja un **FRIDAY.exe** de 82 KB en la raíz: doble clic y
arranca sin ventana de consola, listo para anclar a la barra de tareas. Es un
*lanzador*, no un instalador — necesita el repo y su `.venv` al lado, y por eso
no se versiona. Dentro no lleva ni una línea de tus datos: solo una ruta
relativa al intérprete, verificable con `strings`.

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

## 🧠 Las 13 skills

FRIDAY enruta sola. No hay que invocarlas por nombre.

### 🖥️ Sobre la computadora

| Skill | Ejemplos |
|---|---|
| **sistema** | *"abre Geometry Dash"* · *"abre YouTube"* · *"qué tengo abierto"* · *"busca gatos en google"* |
| **archivos** | *"organiza mis descargas"* · *"busca el archivo presupuesto"* · *"renombra …"* |
| **pantalla** | *"qué estoy viendo"* · *"explícame esto"* |
| **ordenador** | *"no te oigo"* · *"ponlo a la mitad"* · *"sáltate esta canción"* · *"qué tengo copiado"* |
| **taller** | *"métete en mi-proyecto y revisa por qué fallan los tests"* |

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

Y antes que nada de eso hay un tercer camino: **seguimiento**. Si la frase no
se sostiene sola, es del hilo de conversación y no de ninguna skill.

---

## 💬 Conversar, no solo mandar

Además de las órdenes, FRIDAY sostiene una conversación como la sostendría por
escrito. Los últimos turnos viven en RAM, así que una frase puede apoyarse en
la anterior:

```
› qué es una TPU, en una frase
  Un chip diseñado por Google para acelerar operaciones de redes neuronales…

› y eso cuánto cuesta
  No se venden sueltas: Google las alquila por hora en Google Cloud…
```

Ese segundo turno es la parte difícil. *"Y eso cuánto cuesta"* dispara el
`\bcuánto\b` de `metricas`: sin el paso de seguimiento, preguntar por un precio
te devuelve el uso de CPU. Se reconoce por **anáfora** (*eso*, *lo que
dijiste*) o por conectivo más pregunta pelada (*"¿y por qué?"*), y un verbo de
acción lo cancela — *"abre eso"* lleva anáfora pero es una orden.

La conversación libre **no** usa contrato JSON, a diferencia de las skills:
pedirle a un modelo que converse dentro de un campo de JSON le encoge las
respuestas a una frase de trámite, y con un 8B local rompe el formato cada
tanto y se pierde el turno. El panel recibe todo; la voz corta por frases
enteras, nunca a media palabra.

```toml
[chat]
max_turns       = 12    # turnos recordados
ttl_s           = 900   # sin hablar este rato, el hilo se corta solo
speak_max_chars = 700   # lo que se dice; el panel lleva el resto
```

Vive en RAM y se pierde al cerrar, **a propósito**: esto no es memoria. La
memoria es markdown y se gana diciendo *"recuerda que…"*. Di *"cambiemos de
tema"* para cortar el hilo a mano.

---

## 🛠️ El taller: encargarle trabajo, no pedirle texto

```
› métete en mi-proyecto y explica en dos frases qué hace
  Voy con ello, Jefe. Te aviso cuando acabe.
  … 14 s después …
  Listo lo de mi-proyecto. Es una aplicación de escritorio que…
```

La terminal, pero hablando. El encargo **no bloquea el turno**: un agente tarda
minutos, así que la voz acusa recibo y el resultado vuelve por el bus cuando
está. Mientras tanto FRIDAY sigue atendiendo.

Es la capacidad más peligrosa que tiene, así que es la que más guardias lleva:

| Guardia | Qué evita |
|---|---|
| `policy.agent_roots` — lista blanca explícita | Que un nombre mal transcrito acabe en un directorio cualquiera. **No hereda de `write_roots`**: poder guardar un briefing en Documentos no es poder refactorizar ahí. |
| El proyecto se **reconoce**, no se adivina | Si dos carpetas responden igual de bien, no gana ninguna: pregunta. |
| Leer ≠ escribir | *"Revisa"* corre sola con herramientas de solo lectura. *"Arregla"* espera un **sí** hablado, repitiendo qué tarea y en qué ruta. |
| Aviso de repo sucio | Si hay cambios sin commitear, lo dice antes de dejar escribir: es la diferencia entre poder deshacer el trabajo del agente y no. |
| `bypassPermissions` clavado a no | Ni pidiéndolo por config. Si una tarea lo necesita, la haces tú en la terminal. |

Viene **apagada de fábrica**: `agent_roots` está vacía, así que recién
instalada esta capacidad no alcanza ninguna carpeta tuya. Tus rutas van en
`config/friday.local.toml`, que no se versiona:

```toml
[policy]
allow_agent = true
agent_roots = ["~/proyectos", "~/trabajo/api-clientes"]
```

La skill no sabe que existe Claude: pide *un motor que sepa trabajar en un
repo* (`agentic_capable`) y el conmutador le da el que haya.

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

## 🦙 ¿Y con un modelo local?

Sí, salvo el taller. La regla 3 del repo dice que *un prompt debe funcionar con
un 8B local*, y cuando se midió de verdad no se cumplía. Medido con
**`llama3.1:8b` (Q4_K_M) sobre Ollama**, elección de acción del catálogo:

| | acierto |
|---|---|
| Antes | 6 / 12 |
| Después | **12 / 12** (igual que Sonnet 5) |

Lo revelador es **qué** lo arregló. Por orden de impacto medido:

1. **La frase del usuario, al final del prompt.** Ella sola: 6/12 → 12/12. Con
   la petición arriba del catálogo, el 8B elegía casi siempre la primera acción
   de la lista. Atiende a lo último que leyó.
2. **Los huecos de la plantilla se copian literalmente.** El ejemplo del
   contrato decía `"confianza": 0.0` y el modelo devolvía `0.0` **siempre** —
   por debajo del umbral, así que se descartaba cada acción. Un valor de
   ejemplo plausible (`0.9`) y desaparece el problema. El hueco que dejas es
   la respuesta que te dan.
3. **Que falte un campo de metadatos no es una negativa.** La confianza ausente
   se trataba como `0.0`. Los modelos pequeños omiten campos accesorios todo el
   rato; ahora la ausencia no penaliza, pero una confianza baja *dicha* sí se
   respeta.
4. **La persona fuera de las llamadas con contrato.** Son 4 KB de carácter
   («expresiva, urgencia compartida, marcos verbales…») que viajaban como
   system prompt en llamadas que solo debían devolver `{"accion": …}`. Claude
   obedece la cláusula de formato del final; un 8B se pone a hablar en
   personaje. Ahí no falló el modelo: le pedíamos dos cosas incompatibles.
5. **Los ejemplos llevan el argumento, no solo la frase.** Con `no te oigo` a
   secas el modelo acertaba la acción y le ponía `-20`. Con `no te oigo -> +20`
   aprende el signo.
6. **Las palabras vacías no puntúan en la búsqueda del vault.** Con «que» y
   «los» contando, casi cualquier pregunta traía alguna nota, y esa nota se
   inyecta como contexto. Claude ignora el ruido; el 8B respondía sobre ella.

Y una defensa que sale gratis: donde el backend lo soporta, la lista blanca
viaja como **esquema JSON** (`format` en Ollama, `response_format` en el
dialecto OpenAI), así que inventarse una acción deja de ser posible en vez de
solo estar mal. Curiosamente **no cambió la precisión** (12/12 con y sin), pero
elimina una clase entera de fallo.

Todo esto vive en `core/engine.py::ask_json`, por donde pasa toda llamada con
contrato.

**Lo que no se puede en local:** el **taller**. Necesita un bucle de
herramientas que este repo deliberadamente no tiene, y por eso
`OllamaEngine.agentic_capable` es `False` — es honesto, no una carencia
pendiente.

**Lo que ni se entera del modelo:** todo el camino rápido — abrir apps y
juegos, ventanas, búsquedas, archivos, agenda. Regex, 0 ms, sin motor.

```powershell
ollama serve ; ollama pull llama3.1:8b
```

```
› cambia a local
  Listo, Jefe. Pensando con Llama 3.1 8B.
```

Coste real en esta máquina: **~1,5-2 s** por llamada con contrato y **~4-5 s**
por turno de conversación (la primera tras cargar el modelo, ~20 s). Frente a
Claude pierdes calidad de redacción, no capacidad.

---

## 🎮 Abrir cosas: cuatro fuentes, no una carpeta

*"Abre Geometry Dash"* no funcionaba, y no por el enrutado: el juego no existía
para FRIDAY. El catálogo se armaba globeando `*.lnk` en el Menú Inicio, y ni los
juegos de Steam ni las apps de la Store dejan acceso directo ahí.

| Fuente | Qué aporta | Cómo se lanza |
|---|---|---|
| Menú Inicio (`*.lnk`) | lo clásico, y lo más barato de leer | el `.lnk` |
| `Get-StartApps` | **todo** lo que ves en el menú, incluidas Store/UWP | `shell:AppsFolder\<AppID>` |
| `steamapps/*.acf` | los juegos instalados, de **todas** las bibliotecas | `steam://rungameid/<appid>` |
| PATH y URIs | `code`, `ms-settings:`, la papelera | directo |

Los manifiestos de Steam son VDF plano: dos regex y ninguna dependencia nueva.
Ojo con dar por hecho una sola biblioteca — quien tiene un SSD chico reparte los
juegos, y `libraryfolders.vdf` es quien sabe dónde están.

Y una tabla de alias para lo que se dice distinto de como se llama:

```toml
[system.app_aliases]
navegador = ["brave", "google chrome"]   # cada alias admite varios candidatos
```

Los que sean tuyos van en `config/friday.local.toml` — ese archivo no se
versiona, y así tus alias no le cuentan al mundo qué tienes instalado.

**El navegador tampoco se elige aquí.** FRIDAY lee las aplicaciones
predeterminadas de Windows y abre en el que tengas marcado — y lo nombra:

```
› busca capibaras en youtube
  Buscando capibaras en Brave.        (6 ms, sin gastar motor)
```

`webbrowser.open` habría abierto el mismo navegador, pero a ciegas: no sabe
cuál es, y además obedece a la variable `BROWSER`, que puede apuntar a algo que
nunca elegiste. Leer el registro (`winreg`, biblioteca estándar) da el nombre,
y el nombre es la diferencia entre un asistente y un `os.startfile` con voz.

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
allow_agent        = true         # delegar trabajo en un repo (skill `taller`)
confirm_over_files = 5            # sobre esto, pide confirmación hablada
write_roots  = ["~/Documents", "~/Downloads", "~/Desktop", "~/Pictures"]
agent_roots  = []                    # dónde puede soltar un agente (vacía = apagado)
blocked_apps = ["regedit*", "diskpart*", "cmd.exe", "powershell*"]
```

`allow_web` y `allow_web_fetch` son permisos distintos a propósito: uno entrega
una URL a tu navegador —la petición la hace tu navegador, con tu sesión—, el
otro autoriza que FRIDAY salga a internet ella misma. El segundo es más fuerte
y tiene su propio interruptor. `agent_roots` va aparte de `write_roots` por lo
mismo: delegar en algo que decide solo qué archivos tocar no es lo mismo que
escribir un archivo que tú pediste.

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
  router.py            confirmación → seguimiento → rápido → pensado
  chat.py              el hilo de conversación (RAM, no memoria)
  policy.py            el guardia de permisos
  privacy.py           candado de red del audio
memory/                vault.py (markdown) · graph.py (enlaces)
system/
  ports.py             ⭐ los Protocol: la inversión de dependencias
  factory.py           lo único que sabe en qué SO corre
  net.py               ⭐ la única salida HTTP del proyecto
  files.py · web.py · news.py · pages.py
  win32/               implementaciones de Windows (apps, ventanas, escritorio,
                       apps predeterminadas)
skills/                las 13 manos
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
.\.venv\Scripts\python scripts\smoke_test.py     # 62 · memoria, skills, enrutado, conversación
.\.venv\Scripts\python scripts\system_test.py    # 117 · política, puertos, red, motor, taller, PTT
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
| Parpadea una ventana negra al hablarle | Ya no debería: todo proceso hijo va con `CREATE_NO_WINDOW` (`core/proc.py`). Si vuelve, es un `subprocess` nuevo sin el flag. |
| Abrió un programa que no le pedí | Pasaba cuando el enrutado fallaba: `sistema` lanzaba la mejor coincidencia de cualquier frase. Ahora exige un verbo de abrir. |
| Un juego recién instalado no aparece | El catálogo se cachea 10 min (`[system] app_cache_s`). |
| "No tengo ningún directorio donde trabajar" | `[policy] agent_roots` está vacía. Es lo correcto de fábrica: declara dónde. |
| "No reconozco ese proyecto" | El nombre no coincide con ninguna carpeta bajo `agent_roots`, o coincide con dos. El panel lista las que ve. |
| Un "y eso…" contesta otra cosa | El hilo se enfría a los 15 min (`[chat] ttl_s`). Pasado ese rato, es una pregunta nueva. |

---

## 🧭 Qué falta

Lo pendiente, lo decidido a conciencia y lo de algún día está en
**[ROADMAP.md](ROADMAP.md)**. Lo más inmediato:

- **Bluetooth, wifi y brillo** — hoy no existen en el catálogo de acciones, y
  es una petición razonabilísima para un asistente de escritorio.
- **Que diga qué no sabe hacer** por su nombre (*"no sé desactivar el
  Bluetooth"*) en vez de un genérico *"no me quedó claro"*: entender la
  petición y no tener la capacidad son dos fallos distintos.
- **Instalar la voz de Piper** — está configurada, pero sin el `.onnx` cae
  siempre a SAPI5.

---

## 📄 Licencia

**[MIT](LICENSE)** — © 2026 andreyhnzzz. Úsalo, cópialo, modifícalo y véndelo
si quieres; solo conserva el aviso de copyright. Sin garantía de ningún tipo.

Las dependencias mantienen la suya, y dos importan: **PySide6 y pynput son
LGPLv3**. Con el proyecto tal cual no añade ninguna carga —Python las importa
en tiempo de ejecución y cualquiera puede reemplazarlas en su `.venv`—, pero
sí la añadiría un bundle que las lleve dentro. El detalle está en
**[NOTICE.md](NOTICE.md)**.

F.R.I.D.A.Y es un nombre y un personaje de Marvel. Esto es un proyecto
personal sin afiliación ni respaldo de Marvel ni Disney.

---

<div align="center">

**F.R.I.D.A.Y no vive en un servidor de otro. Vive en tu escritorio.**

</div>
