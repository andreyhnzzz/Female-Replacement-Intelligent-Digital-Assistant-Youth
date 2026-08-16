# F.R.I.D.A.Y — contexto del repo

Acompañante de escritorio con voz local y acceso al sistema.
Python 3.12, asyncio + Qt/QML. Corre local. **No es una app web.**

## Reglas de este repo

1. **La memoria es markdown y nada más.** Nunca propongas SQLite, Chroma ni un
   índice persistente. Lo que necesite ser rápido se cachea en RAM y se
   reconstruye leyendo archivos.
2. **El audio no sale del equipo.** No agregues clientes HTTP a `voice/`.
   `core/privacy.py` bloquea sockets no-loopback durante el pipeline de audio.
3. **El motor es intercambiable.** Nada fuera de `core/engine.py` puede asumir
   que el backend es Claude. Un prompt debe funcionar con un modelo local de 8B.
4. **Los archivos los escribe Python, no el motor.** El motor razona y devuelve
   texto/JSON; `memory/vault.py` y `system/files.py` son los únicos que escriben.
5. **Nadie importa a nadie.** La comunicación entre capas va por `core/bus.py`.
6. **Nada con efecto pasa sin política.** Toda acción sobre el sistema consulta
   `core/policy.py`. Si añades una capacidad que escribe, lanza o borra, tiene
   que pasar por ahí. Sin excepciones.
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
                                |                       |
                          core/policy.py          system/win32/ · system/files.py
                                |
                          core/bus.py --> desktop/bridge.py --> QML
```

`friday.py` es el único que conoce a todos. Es a propósito.

## Contratos

- **Skill**: hereda `skills/base.py::Skill`. Define `name`, `description`,
  `triggers` (regex), `needs` (puertos requeridos) y `async run(ctx) -> SkillResult`.
  Registrar en `skills/__init__.py::ALL_SKILLS` y en `skills.enabled` del toml.
- **Puerto nuevo**: `Protocol` en `system/ports.py`, campo en `SystemAccess`,
  implementación en `system/win32/` o `system/`, cableado en `system/factory.py`.
  **Separa lectura de escritura** — es interface segregation, no burocracia.
- **Acción que necesita permiso**: devuelve `SkillResult(pending=PendingAction(...))`.
  El router la guarda y la ejecuta cuando el usuario dice "sí".
- **Engine**: hereda `core/engine.py::Engine`. Registrar en `ENGINES`.
- **Prompts**: cada llamada declara su propio formato. `config/persona.md` define
  el **tono**, nunca la estructura — si metes un contrato JSON ahí, pelea con el
  de cada skill y todo cae al fallback.

## Trampas conocidas (ya nos mordieron)

- **Windows + npm shim**: pasar prompts largos por argv a `claude.CMD` los
  corrompe. Van por **stdin**.
- **Claude Code como motor** necesita `--tools ""` y `--system-prompt`; si no,
  se comporta como agente de código: intenta escribir archivos y responde en
  prosa en vez del JSON pedido.
- **`privacy.sealed()` es thread-local.** Va **dentro** del hilo que trabaja,
  no alrededor de `asyncio.to_thread(...)`.
- **Python 3.14 no sirve**: `faster-whisper` no tiene wheels. El venv es 3.12.
- **QML `pixelSize` es entero.** `13.5` revienta la carga entera del componente.
- **`setPosition()` va después de `show()`**, o el gestor de ventanas reubica.
- **Sin `@Slot`, QML no ve un método** como función invocable.
- **Puntaje de triggers = especificidad, no cobertura.** Si mides cobertura,
  "recuerda que <párrafo>" se diluye y pierde. Ver `skills/base.py::matches`.
- **Ventana translúcida sin blur = texto ilegible.** Qt no desenfoca lo que hay
  detrás; eso lo hace el compositor (`desktop/backdrop.py`, opcional).

## Verificar cambios

```powershell
.\.venv\Scripts\python scripts\smoke_test.py     # 35 · memoria, skills, privacidad
.\.venv\Scripts\python scripts\system_test.py    # 31 · política, puertos, confirmación
.\.venv\Scripts\python friday.py --check         # dependencias y capacidades
.\.venv\Scripts\python scripts\ui_preview.py     # solo la interfaz, iteración rápida
```

Las pruebas usan directorios temporales y motor simulado: no tocan el vault
real, no mueven archivos del usuario y no gastan llamadas. Si tocas `memory/`,
`skills/`, `core/` o `system/`, córrelas.
