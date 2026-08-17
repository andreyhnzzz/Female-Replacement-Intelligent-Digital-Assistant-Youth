# Registro de cambios

Lo que cambió, cuándo y **por qué**. Las cifras que aparecen aquí están
medidas en la máquina de referencia, no estimadas.

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
