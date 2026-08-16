# F.R.I.D.A.Y OS — contexto para Claude Code

Asistente por voz. Python 3.12, asyncio. Corre local.

## Reglas de este repo

1. **La memoria es markdown y nada más.** Nunca propongas SQLite, Chroma, ni un
   índice persistente. Si algo necesita ser rápido, se cachea en RAM y se
   reconstruye leyendo archivos.
2. **El audio no sale del equipo.** No agregues clientes HTTP a `voice/`.
   `core/privacy.py` bloquea sockets no-loopback durante el pipeline de audio y
   la prueba de humo lo verifica.
3. **El motor es intercambiable.** Nada fuera de `core/engine.py` puede asumir
   que el backend es Claude. Si escribes un prompt, debe funcionar con un
   modelo local de 8B.
4. **Los archivos los escribe Python, no el motor.** El motor razona y devuelve
   texto/JSON; `memory/vault.py` es el único que toca el disco del vault.
5. **Nadie importa a nadie.** La comunicación entre capas va por `core/bus.py`.

## Cableado

```
voice/ptt.py  --(hilo)-->  voice/stt.py  --> friday.py::handle
                                              |
                          core/router.py <----+
                                |
                    skills/*.py --> memory/vault.py (escribe .md)
                                |
                    core/bus.py --> hud/server.py --> websocket --> hud/web/
```

`friday.py` es el único que conoce a todos. Es a propósito.

## Contratos

- **Skill**: hereda `skills/base.py::Skill`. Define `name`, `description`,
  `triggers` (regex) y `async run(ctx) -> SkillResult`. Registrar en
  `skills/__init__.py::ALL_SKILLS` y en `skills.enabled` del toml.
- **Engine**: hereda `core/engine.py::Engine` con `async complete(prompt, system)`
  y `async health()`. Registrar en `ENGINES`.
- **Prompts**: cada llamada declara su propio formato de salida. `config/persona.md`
  define el **tono**, nunca la estructura — si vuelves a meter un contrato JSON
  ahí, pelea con el de cada skill y todo cae al fallback.

## Trampas conocidas (ya nos mordieron)

- **Windows + npm shim**: pasar prompts largos por argv a `claude.CMD` los
  corrompe. Van por **stdin**.
- **Claude Code como motor** necesita `--tools ""` y `--system-prompt`, si no se
  comporta como agente de código: intenta escribir archivos y responde en prosa
  en vez del JSON pedido.
- **`privacy.sealed()` es thread-local.** Debe abrirse **dentro** del hilo que
  hace el trabajo, no alrededor de `asyncio.to_thread(...)`.
- **Python 3.14 no sirve**: `faster-whisper` no tiene wheels. El venv es 3.12.
- Los assets del HUD llevan cache-busting por mtime en `hud/server.py::index`.

## Verificar cambios

```powershell
.\.venv\Scripts\python scripts\smoke_test.py        # 35 pruebas, sin red
.\.venv\Scripts\python friday.py --check            # dependencias
.\.venv\Scripts\python friday.py --no-voice --no-hud --say "dame las metricas"
```

La prueba de humo usa un vault temporal y un motor simulado: no toca el vault
real ni gasta llamadas. Si tocas `memory/`, `skills/` o `core/`, córrela.
