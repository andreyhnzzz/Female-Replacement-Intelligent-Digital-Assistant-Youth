"""SKILL — taller: encargarle trabajo a un agente, hablando.

    «Metete en mi-proyecto y revisa por que fallan los tests»

La capacidad mas peligrosa de FRIDAY, y la que mas guardias tiene:

  1. Solo bajo `policy.agent_roots`, vacia de fabrica.
  2. El proyecto se reconoce contra el disco; si no hay coincidencia clara,
     pregunta. Un STT que oye «Desactual Bluetooth» no elige carpeta.
  3. Leer corre solo; escribir espera un «si» que repite tarea y ruta.
  4. `bypassPermissions` esta clavado a no en `core/engine.py`.
  5. Avisa si el repo tiene cambios sin commitear: es la diferencia entre
     poder deshacer el trabajo del agente y no.

El encargo **no bloquea el turno**: la voz acusa recibo y el resultado vuelve
por `core.say` cuando este, que pueden ser minutos.

No sabe que existe Claude (regla 3): pide un motor que sepa trabajar en un
repo y el conmutador le da el que haya.
"""
from __future__ import annotations

import asyncio
import re
import subprocess
import time
import unicodedata
from pathlib import Path

from core.bus import BUS
from core.proc import NO_WINDOW

from .base import PendingAction, Skill, SkillContext, SkillResult

# ── como se pide ──────────────────────────────────────────────────
ENTRAR = re.compile(
    r"\b(m[eé]tete|meterse|entra|entrar|ve|vete|anda|ponte|abre|trabaja)\s+"
    r"(en|a|al|dentro de)\s+", re.I)

PROYECTO = re.compile(
    r"\b(?:en|dentro de)\s+(?:el\s+|la\s+|mi\s+)?"
    r"(?:proyecto|repo|repositorio|carpeta|directorio)\s+", re.I)

# Verbos que dejan el disco como estaba. Todo lo demas que suene a trabajo
# se trata como escritura: ante la duda, se confirma.
LECTURA = re.compile(
    r"\b(revisa|revisar|explica|expl[ií]came|analiza|examina|busca|"
    r"encuentra|lee|resume|dime|averigua|investiga|comprueba|diagnostica|"
    r"por\s+qu[eé]|qu[eé]\s+hace|c[oó]mo\s+funciona|audita|inspecciona)\b", re.I)

ESCRITURA = re.compile(
    r"\b(arregla|arreglar|corrige|corregir|repara|implementa|implementar|"
    r"refactoriza|reescribe|escribe|crea|a[ñn]ade|agrega|borra|elimina|"
    r"renombra|actualiza|migra|formatea|documenta|commitea|optimiza|"
    r"instala|actualiza|resuelve|soluciona|termina|completa)\b", re.I)

# Salida de compilacion, dependencias y metadatos: nunca son un proyecto.
# Sin esto un arbol Maven aporta `src`, `target` y `classes` a la lista, y
# ademas duplicados, porque cada repo tiene los suyos.
_NO_PROYECTO = {
    "target", "build", "dist", "out", "bin", "obj", "node_modules",
    "venv", "env", "classes", "generated-sources", "maven-status",
    "site-packages", "coverage", "htmlcov", "logs", "tmp", "temp",
}

# Lo que hace que una carpeta honda SI sea un proyecto.
_MARCAS = (".git", "pom.xml", "package.json", "pyproject.toml", "Cargo.toml",
           "go.mod", "CMakeLists.txt", "build.gradle", "build.gradle.kts",
           "requirements.txt", "Makefile", "composer.json")

# Ruido que sobra una vez identificados proyecto y tarea.
_LIMPIA = re.compile(
    r"^\s*(?:y\s+|luego\s+|despu[eé]s\s+|por favor\s+|ah[ií]\s+|"
    r"que\s+|a\s+ver\s+si\s+)+", re.I)


def _fold(s: str) -> str:
    """`mi-proyecto`, `mi_proyecto` y «mi proyecto» son lo mismo dicho de tres
    maneras, y el STT siempre entrega la tercera."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


class TallerSkill(Skill):
    name = "taller"
    description = ("Le encarga trabajo a un agente dentro de un proyecto: "
                   "revisar por que fallan los tests, explicar un modulo, "
                   "arreglar algo. Trabaja en segundo plano.")
    triggers = [
        r"\bm[eé]tete en\b", r"\bentra (en|al)\b",
        r"\ben (el |mi )?(proyecto|repo|repositorio)\b",
        r"\bfallan los tests?\b", r"\blos tests?\b", r"\btaller\b",
        r"\bencarga(le)?\b", r"\bpon(te)? a trabajar\b",
        r"\brevisa (el|los) (c[oó]digo|repo|tests?)\b",
    ]
    needs = ()

    def __init__(self, ctx_cfg) -> None:
        super().__init__(ctx_cfg)
        self.timeout_s = float(self.opts.get("timeout_s", 900))
        self.max_turns = int(self.opts.get("max_turns", 24))
        self.depth = max(1, int(self.opts.get("depth", 2)))
        self.read_tools = list(self.opts.get(
            "read_tools", ["Read", "Glob", "Grep"]))
        self.write_tools = list(self.opts.get(
            "write_tools", ["Read", "Glob", "Grep", "Write", "Edit"]))
        # Referencias vivas: sin esto el recolector se lleva una tarea a
        # medio correr.
        self._jobs: set[asyncio.Task] = set()

    # ══════════════════════════════════════════════ ejecucion
    async def run(self, ctx: SkillContext) -> SkillResult:
        text = ctx.text.strip()
        policy = ctx.policy

        if policy is None:
            return SkillResult(ok=False, error="sin politica",
                               speak="No puedo delegar trabajo sin politica.")

        # Por capacidad, no por marca: el modelo activo puede no saber y otro
        # del roster si.
        motor_ok = bool(getattr(ctx.engine, "agentic_capable", False))
        if not motor_ok and hasattr(ctx.engine, "agentic_spec"):
            motor_ok = ctx.engine.agentic_spec() is not None
        if not motor_ok:
            return SkillResult(
                ok=False, error="motor no agentico",
                speak="El motor de ahora no sabe trabajar dentro de un repo.",
                display="# Sin motor agentico\n\nEl adaptador activo entra "
                        "texto y saca texto. Cambia a uno que trabaje en repos.")

        proyectos = self._proyectos(policy)
        if not proyectos:
            return SkillResult(
                ok=False, error="sin agent_roots",
                speak="No tengo ningun directorio donde se me permita trabajar.",
                display="# Sin directorios de trabajo\n\nDeclara donde puedo "
                        "delegar en `[policy] agent_roots` del toml. Esta "
                        "vacia a proposito: recien instalada, esta capacidad "
                        "no alcanza ninguna carpeta tuya.")

        elegido = self._elegir(text, proyectos)
        if elegido is None:
            listado = "\n".join(f"- **{n}** — `{p}`" for n, p in proyectos[:12])
            return SkillResult(
                ok=False, error="proyecto no reconocido",
                speak="No reconozco ese proyecto. Dime cual de los que tengo.",
                display=f"# ¿En cual?\n\nNo encontre a que proyecto te "
                        f"refieres.\n\n### Los que puedo tocar\n{listado}",
                data={"projects": [n for n, _ in proyectos]})

        nombre, ruta = elegido
        tarea = self._tarea(text, nombre)
        if not tarea:
            return SkillResult(
                speak=f"¿Que hago en {nombre}?",
                display=f"# {nombre}\n\n`{ruta}`\n\nDime que quieres que haga ahi.",
                data={"project": nombre, "path": str(ruta)})

        escribe = self._escribe(tarea)
        decision = policy.can_delegate(ruta, writes=escribe)

        if decision.verdict.value == "deny":
            return SkillResult(
                ok=False, error=f"{decision.rule}: {decision.reason}",
                speak=f"No puedo trabajar en {nombre}. {decision.reason}.",
                display=f"# Bloqueado\n\n**{nombre}** · `{ruta}`\n\n"
                        f"> {decision.reason}\n\nregla: `{decision.rule}`")

        if decision.verdict.value == "confirm":
            sucio = await asyncio.to_thread(self._git_sucio, ruta)
            aviso = ("\n\n⚠ El repo tiene cambios sin commitear: si el agente "
                     "escribe encima, no vas a poder separarlos." if sucio else "")
            describe = f"«{tarea}» en {nombre} ({ruta})"

            return SkillResult(
                # El encargo se repite tal cual lo dijiste: si el STT lo
                # entendio mal, esta es tu ocasion de oirlo.
                speak=(f"Entendido: {tarea}. En {nombre}."
                       + (" Ojo, tienes cambios sin commitear." if sucio else "")
                       + " ¿Le doy?"),
                display=(f"# Confirmar encargo\n\n**Tarea:** {tarea}\n\n"
                         f"**Proyecto:** {nombre}\n\n**Ruta:** `{ruta}`\n\n"
                         f"**Puede escribir:** si — `{', '.join(self.write_tools)}`"
                         f"{aviso}\n\nDi «si» para lanzarlo."),
                data={"project": nombre, "path": str(ruta), "task": tarea,
                      "writes": True, "dirty": sucio},
                pending=PendingAction(
                    describe=describe,
                    run=lambda: self._lanzar(ctx, nombre, ruta, tarea, True),
                    ttl_s=180.0))

        return self._lanzar(ctx, nombre, ruta, tarea, False)

    # ══════════════════════════════════════════════ el encargo
    def _lanzar(self, ctx: SkillContext, nombre: str, ruta: Path,
                tarea: str, escribe: bool) -> SkillResult:
        """Arranca el trabajo y devuelve el turno. Lo que sale de aqui es un
        acuse de recibo; el resultado llega por el bus al terminar."""
        job = asyncio.create_task(
            self._trabajar(ctx, nombre, ruta, tarea, escribe))
        self._jobs.add(job)
        job.add_done_callback(self._jobs.discard)

        return SkillResult(
            speak=f"Voy con ello, Jefe. {tarea.capitalize()}, en {nombre}. "
                  f"Te aviso cuando acabe.",
            display=(f"# En marcha\n\n**{nombre}** · `{ruta}`\n\n"
                     f"**Tarea:** {tarea}\n\n"
                     f"**Herramientas:** "
                     f"`{', '.join(self.write_tools if escribe else self.read_tools)}`\n\n"
                     f"Corre en segundo plano. Te aviso al terminar."),
            data={"action": "delegate", "project": nombre, "path": str(ruta),
                  "task": tarea, "writes": escribe, "async": True})

    async def _trabajar(self, ctx: SkillContext, nombre: str, ruta: Path,
                        tarea: str, escribe: bool) -> None:
        t0 = time.time()
        await BUS.emit("agent.started", project=nombre, path=str(ruta),
                       task=tarea, writes=escribe)

        prompt = (
            f"Estas trabajando en el proyecto «{nombre}», en {ruta}.\n\n"
            f"TAREA: {tarea}\n\n"
            + ("Puedes leer y modificar archivos del proyecto.\n"
               if escribe else
               "Trabajo de SOLO LECTURA: no modifiques ningun archivo.\n")
            + "\nCuando termines, cierra tu respuesta con una ultima linea "
              "que empiece por «RESUMEN:» y quepa en dos frases: es lo unico "
              "que se va a leer en voz alta."
        )
        system = ("Trabajas por encargo hablado. Sin preambulos. Si la tarea "
                  "es ambigua, elige la lectura mas razonable y dilo en el "
                  "resumen en vez de detenerte a preguntar: quien te encargo "
                  "esto no esta mirando la pantalla.")

        try:
            engine = ctx.engine
            kw = dict(cwd=str(ruta), timeout=self.timeout_s,
                      max_turns=self.max_turns,
                      tools=self.write_tools if escribe else self.read_tools,
                      permission_mode="acceptEdits" if escribe else "default")

            if hasattr(engine, "complete_agentic"):
                salida = await engine.complete_agentic(prompt, system=system, **kw)
            else:
                salida = await engine.complete(prompt, system=system,
                                               agentic=True, **kw)
        except Exception as exc:
            await BUS.emit("agent.failed", project=nombre, task=tarea,
                           error=str(exc)[:300])
            await BUS.emit("core.say",
                           text=f"El encargo en {nombre} fallo. {str(exc)[:120]}",
                           display=f"# Encargo fallido\n\n**{nombre}** · {tarea}\n\n"
                                   f"```\n{exc}\n```",
                           skill=self.name)
            return

        ms = int((time.time() - t0) * 1000)
        resumen = self._resumen(salida)
        await BUS.emit("agent.done", project=nombre, task=tarea, ms=ms,
                       chars=len(salida))
        await BUS.emit(
            "core.say",
            text=f"Listo lo de {nombre}. {resumen}",
            display=(f"# {nombre} — hecho\n\n**Tarea:** {tarea}\n\n"
                     f"_{ms // 1000}s_\n\n---\n\n{salida}"),
            skill=self.name)

    # ══════════════════════════════════════════════ auxiliares
    def _proyectos(self, policy) -> list[tuple[str, Path]]:
        """Los candidatos, solo bajo las raices declaradas: la lista blanca no
        filtra al final, es de donde salen las opciones.

        Una raiz puede ser un contenedor (sus hijos son proyectos) o ya un
        repo (sus hijos son `src`, `config`... y no se listan). Se distingue
        por las marcas; sin eso «metete en src» seria ambiguo entre los
        cuatro `src` que tengas.
        """
        out: list[tuple[str, Path]] = []
        vistos: set[str] = set()

        def sumar(p: Path) -> None:
            if str(p).lower() not in vistos:
                vistos.add(str(p).lower())
                out.append((p.name, p))

        def hijos(base: Path) -> list[Path]:
            try:
                return [c for c in base.iterdir()
                        if c.is_dir() and not c.name.startswith(".")
                        and c.name.lower() not in _NO_PROYECTO]
            except OSError:
                return []

        def es_proyecto(p: Path) -> bool:
            return any((p / marca).exists() for marca in _MARCAS)

        for root in getattr(policy, "agent_roots", []):
            if not root.is_dir():
                continue
            sumar(root)
            if es_proyecto(root):
                continue                         # la raiz ES el proyecto

            nivel = hijos(root)
            for h in nivel:                      # contenedor: sus hijos valen
                sumar(h)
            for _ in range(self.depth - 1):      # mas hondo: solo si parece repo
                siguiente: list[Path] = []
                for base in nivel:
                    if es_proyecto(base):
                        continue                 # no se entra en un repo ya listado
                    for c in hijos(base):
                        if es_proyecto(c):
                            sumar(c)
                        siguiente.append(c)
                if not siguiente:
                    break
                nivel = siguiente
        return out

    @staticmethod
    def _elegir(text: str, proyectos: list[tuple[str, Path]]):
        """Que proyecto nombro el usuario. None si no esta claro.

        Gana el nombre mas largo: con `friday` y `friday-docs` en disco,
        «revisa friday-docs» no puede acabar en `friday`. Si dos empatan no
        gana ninguna — preguntar cuesta una frase, equivocarse de repo
        cuesta una tarde.
        """
        blob = _fold(text)
        largo = 0
        candidatos: list[tuple[str, Path]] = []
        for nombre, ruta in proyectos:
            clave = _fold(nombre)
            if not clave or len(clave) < 3:
                continue
            if not re.search(rf"(?<![a-z0-9]){re.escape(clave)}(?![a-z0-9])", blob):
                continue
            if len(clave) > largo:
                largo, candidatos = len(clave), [(nombre, ruta)]
            elif len(clave) == largo:
                candidatos.append((nombre, ruta))

        return candidatos[0] if len(candidatos) == 1 else None

    @staticmethod
    def _tarea(text: str, nombre: str) -> str:
        """Lo que queda cuando quitas «metete en X y»: el encargo."""
        limpio = ENTRAR.sub(" ", text)
        limpio = PROYECTO.sub(" ", limpio)
        limpio = re.sub(rf"(?i)(?<![a-z0-9]){re.escape(nombre)}(?![a-z0-9])",
                        " ", limpio)
        # el nombre tal cual puede no estar (el STT lo separo): tambien por folding
        if _fold(nombre) in _fold(limpio):
            limpio = re.sub(rf"(?i)(?<![a-z0-9]){re.escape(_fold(nombre))}(?![a-z0-9])",
                            " ", limpio)
        limpio = re.sub(r"\s+", " ", limpio).strip(" ,.:;¿?—-")
        return _LIMPIA.sub("", limpio).strip()

    @staticmethod
    def _escribe(tarea: str) -> bool:
        """¿La tarea toca archivos?

        Escribir manda sobre leer: «revisa y arregla los tests» escribe. Y un
        verbo que no se reconoce cuenta como escritura — no entender la
        intencion no es razon para asumir la version inofensiva.
        """
        if ESCRITURA.search(tarea):
            return True
        return not LECTURA.search(tarea)

    @staticmethod
    def _git_sucio(ruta: Path) -> bool:
        """¿Hay cambios sin commitear que el agente podria pisar?

        Acotado a `-- .`: un directorio que cuelga de otro repo reportaria la
        suciedad del padre, que no tiene que ver con lo que el agente toca.
        """
        try:
            proc = subprocess.run(
                ["git", "status", "--porcelain", "--", "."], cwd=str(ruta),
                capture_output=True, timeout=8, check=False,
                creationflags=NO_WINDOW)
        except (OSError, subprocess.SubprocessError):
            return False
        return proc.returncode == 0 and bool(proc.stdout.strip())

    @staticmethod
    def _resumen(salida: str) -> str:
        """Lo que se dice en voz alta de un trabajo que puede ser larguisimo."""
        for linea in reversed(salida.strip().splitlines()):
            m = re.match(r"\s*RESUMEN\s*:\s*(.+)", linea, re.I)
            if m:
                return m.group(1).strip()[:400]
        plano = re.sub(r"\s+", " ", re.sub(r"[#*`]", "", salida)).strip()
        return plano[:280] or "Sin resultado que contar."
