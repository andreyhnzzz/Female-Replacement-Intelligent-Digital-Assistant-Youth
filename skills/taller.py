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
import itertools
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from core.bus import BUS
from core.lang import parecido, slug_words
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


# `mi-proyecto`, `mi_proyecto` y «mi proyecto» son lo mismo dicho de tres
# maneras, y el STT siempre entrega la tercera. La funcion vive ahora en
# `core/lang.py`, con las demas normalizaciones del habla; el alias se
# mantiene porque este archivo la nombra en media docena de sitios.
_fold = slug_words

# Cuanto tiene que parecerse un nombre dictado al de una carpeta para que
# FRIDAY se atreva a PREGUNTAR por ella. No para elegirla: para preguntar.
# Por debajo de esto, «metete en la casa» se ofreceria como «mi-caza» y
# proponer basura es peor que decir que no reconoces el proyecto.
PARECIDO_MINIMO = 0.72

# Como se pregunta por un encargo en marcha, y como se cancela.
ESTADO = re.compile(
    r"\b(c[oó]mo va|qu[eé] tal va|va (bien|eso)|c[oó]mo van|"
    r"sigues? con|est[aá]s? (con|en) (eso|ello)|"
    r"(que|qu[eé]) (encargos?|tareas?) (tienes|hay)|encargos? en (marcha|curso))\b",
    re.I)

CANCELAR = re.compile(
    r"\b(cancela|cancelar|para|detente|d[eé]jalo|d[eé]jalo ya|olv[ií]dalo|"
    r"aborta|abortar|anula|ya no|para ya)\b", re.I)


@dataclass
class Encargo:
    """Un trabajo en marcha. Existe para poder contestar «¿como va?».

    Antes el taller solo guardaba un `set` de tareas de asyncio: bastaba
    para que el recolector no se las llevara, y no para nada mas. Preguntar
    por un encargo, o pararlo, no tenia respuesta posible — el dato no
    estaba. Lanzar trabajo que dura minutos y no poder mirarlo es media
    capacidad.
    """
    ident: str
    proyecto: str
    ruta: Path
    tarea: str
    escribe: bool
    t0: float = field(default_factory=time.time)
    task: "asyncio.Task | None" = None
    estado: str = "corriendo"          # corriendo | hecho | fallido | cancelado

    @property
    def segundos(self) -> int:
        return int(time.time() - self.t0)

    @property
    def vivo(self) -> bool:
        return self.estado == "corriendo"

    def describe(self) -> str:
        minutos = self.segundos // 60
        cuanto = f"{minutos} min" if minutos else f"{self.segundos}s"
        return f"{self.proyecto}: {self.tarea} ({cuanto})"


# Herramientas que no son «leer y escribir archivos»: ejecutan comandos o
# salen a la red. Las listas vienen del toml, asi que sin este filtro meter
# `Bash` en `read_tools` convertia una tarea de SOLO LECTURA —que corre sin
# confirmar— en ejecucion arbitraria, con `policy.allow_shell` en false y sin
# enterarse. La regla 6 no admite que una capacidad con efecto se declare por
# configuracion y esquive al guardia.
_TOOLS_CON_EFECTO = {
    "Bash": "allow_shell", "BashOutput": "allow_shell", "KillShell": "allow_shell",
    "Execute": "allow_shell", "Task": "allow_shell", "Agent": "allow_shell",
    "WebFetch": "allow_web_fetch", "WebSearch": "allow_web_fetch",
}


def _tools_permitidas(tools: list[str], policy) -> tuple[list[str], list[str]]:
    """Filtra la lista declarada en el toml contra la politica.

    Devuelve (permitidas, retiradas). Retirar en silencio seria peor que no
    filtrar: quien lo puso en el toml tiene que enterarse de por que no esta.
    """
    ok, fuera = [], []
    for t in tools:
        interruptor = _TOOLS_CON_EFECTO.get(t)
        if interruptor and not getattr(policy, interruptor, False):
            fuera.append(t)
        else:
            ok.append(t)
    return ok, fuera


class TallerSkill(Skill):
    name = "taller"
    description = ("Le encarga trabajo a un agente dentro de un proyecto: "
                   "revisar por que fallan los tests, explicar un modulo, "
                   "arreglar algo. Trabaja en segundo plano.")
    triggers = [
        r"\bm[eé]tete en\b", r"\bentra (en|al)\b",
        r"\ben (el |mi )?(proyecto|repo|repositorio)\b",
        r"\bfallan los tests?\b", r"\blos tests?\b", r"\btaller\b",
        r"\bencarga(le)?\b", r"\bencargos?\b", r"\bpon(te)? a trabajar\b",
        r"\brevisa (el|los) (c[oó]digo|repo|tests?)\b",
        # Preguntar por lo que ya esta corriendo. «como va» a secas se queda
        # fuera a proposito: es demasiado corto y comun, y se lo robaria a
        # media casa. «como va lo de» ya nombra un encargo.
        r"\bc[oó]mo va lo de\b", r"\bencargos? en (marcha|curso)\b",
    ]
    needs = ()
    riesgo = "efecto"        # suelta un agente dentro de un repo

    def __init__(self, ctx_cfg) -> None:
        super().__init__(ctx_cfg)
        self.timeout_s = float(self.opts.get("timeout_s", 900))
        self.max_turns = int(self.opts.get("max_turns", 24))
        self.depth = max(1, int(self.opts.get("depth", 2)))
        self.read_tools = list(self.opts.get(
            "read_tools", ["Read", "Glob", "Grep"]))
        self.write_tools = list(self.opts.get(
            "write_tools", ["Read", "Glob", "Grep", "Write", "Edit"]))
        # Los encargos en marcha, por identificador. Sostiene las
        # referencias vivas —sin esto el recolector se lleva una tarea a
        # medio correr— y ademas es lo que permite responder «como va».
        self._encargos: dict[str, Encargo] = {}
        self._contador = itertools.count(1)
        # Un encargo tarda minutos. Sin tope, tres frases seguidas levantan
        # tres agentes a la vez sobre el mismo disco.
        self.max_jobs = max(1, int(self.opts.get("max_jobs", 2)))

    # ══════════════════════════════════════════════ el registro
    def vivos(self) -> list[Encargo]:
        return [e for e in self._encargos.values() if e.vivo]

    def _recorta(self, tope: int = 12) -> None:
        """Deja de recordar los encargos terminados mas viejos.

        Un proceso que corre todo el dia no puede crecer sin fin — la misma
        razon por la que el cache de notas lleva techo. Los vivos no se
        tocan nunca: un encargo en marcha no se olvida por antiguo.
        """
        acabados = [e for e in self._encargos.values() if not e.vivo]
        for viejo in sorted(acabados, key=lambda e: e.t0)[:-tope or None]:
            self._encargos.pop(viejo.ident, None)

    def _estado_md(self) -> SkillResult:
        """«¿Como va lo de mi-proyecto?» — lo que faltaba para poder mirar."""
        vivos = self.vivos()
        acabados = [e for e in self._encargos.values() if not e.vivo][-4:]

        if not vivos and not acabados:
            return SkillResult(speak="No tengo ningun encargo en marcha.",
                               display="# Taller vacio\n\nNada corriendo.",
                               data={"jobs": 0})

        lineas = ["# Taller", ""]
        if vivos:
            lineas.append(f"### En marcha ({len(vivos)})")
            lineas += [f"- `{e.ident}` **{e.proyecto}** — {e.tarea} "
                       f"_({e.segundos // 60} min)_" for e in vivos]
            lineas.append("")
        if acabados:
            lineas.append("### Ultimos")
            lineas += [f"- `{e.ident}` **{e.proyecto}** — {e.estado}"
                       for e in acabados]

        if vivos:
            uno = vivos[0]
            minutos = uno.segundos // 60
            hablado = (f"Sigo con lo de {uno.proyecto}"
                       + (f", llevo {minutos} minutos." if minutos
                          else ", acabo de empezar."))
            if len(vivos) > 1:
                hablado += f" Y {len(vivos) - 1} mas."
        else:
            ultimo = acabados[-1]
            hablado = f"Nada en marcha. Lo ultimo fue {ultimo.proyecto}: {ultimo.estado}."

        return SkillResult(speak=hablado, display="\n".join(lineas),
                           data={"jobs": len(vivos),
                                 "encargos": [e.describe() for e in vivos]})

    def _cancelar(self, text: str) -> SkillResult:
        """Parar un encargo. Si hay varios y no dijo cual, pregunta.

        Cancelar no se confirma: es la operacion que **deshace**, y pedir un
        «si» para dejar de hacer algo es exactamente al reves que el resto de
        la politica. Lo que si hace falta es no cancelar el que no era, y por
        eso con dos en marcha y sin nombre no se elige por antiguedad.
        """
        vivos = self.vivos()
        if not vivos:
            return SkillResult(speak="No tengo nada en marcha que parar.",
                               display="# Nada que cancelar")

        blob = _fold(text)
        nombrados = [e for e in vivos
                     if re.search(rf"(?<![a-z0-9]){re.escape(_fold(e.proyecto))}"
                                  rf"(?![a-z0-9])", blob)]
        objetivo: Encargo | None = None
        if len(nombrados) == 1:
            objetivo = nombrados[0]
        elif not nombrados and len(vivos) == 1:
            objetivo = vivos[0]

        if objetivo is None:
            listado = "\n".join(f"- `{e.ident}` {e.describe()}" for e in vivos)
            return SkillResult(
                ok=False, error="cual encargo",
                speak=f"Tengo {len(vivos)} en marcha. ¿Cual paro?",
                display=f"# ¿Cual paro?\n\n{listado}",
                data={"encargos": [e.ident for e in vivos]})

        objetivo.estado = "cancelado"
        if objetivo.task is not None:
            objetivo.task.cancel()
        return SkillResult(
            speak=f"Listo, dejo lo de {objetivo.proyecto}.",
            display=f"# Cancelado\n\n**{objetivo.proyecto}** — ~~{objetivo.tarea}~~\n\n"
                    f"_Llevaba {objetivo.segundos // 60} min._",
            data={"cancelado": objetivo.ident, "project": objetivo.proyecto})

    # ══════════════════════════════════════════════ ejecucion
    async def run(self, ctx: SkillContext) -> SkillResult:
        text = ctx.text.strip()
        policy = ctx.policy

        # Preguntar por un encargo y pararlo van ANTES de todo lo demas: no
        # necesitan politica, ni motor, ni recorrer el disco, y «déjalo» con
        # un agente corriendo no puede acabar interpretandose como el
        # encargo de dejar algo en algun proyecto.
        if CANCELAR.search(text) and self.vivos():
            return self._cancelar(text)
        if ESTADO.search(text):
            return self._estado_md()

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

        # Recorre el disco: `iterdir` por nivel y un `exists` por cada marca
        # de repo. En el bucle de eventos eso congela el HUD justo al
        # empezar el turno, que es cuando mas se nota.
        proyectos = await asyncio.to_thread(self._proyectos, policy)
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
            # Un nombre dictado rara vez llega igual que en el disco:
            # «api-clientes» sale como «api clientes» y «FRIDAY» como
            # «friday». El emparejado exacto ya cubre esos dos por folding,
            # pero no cubre que el STT se coma una silaba. Ahi se **ofrece**
            # el parecido, nunca se elige: preguntar cuesta una frase.
            cerca = self._sugerir(text, proyectos)
            if cerca:
                sugerido = ", ".join(f"**{n}**" for n in cerca[:3])
                return SkillResult(
                    ok=False, error="proyecto no reconocido",
                    speak=f"No estoy segura. ¿Te refieres a {cerca[0]}?",
                    display=f"# ¿Te refieres a...?\n\nNo encontre ese nombre "
                            f"exacto. Lo que mas se le parece: {sugerido}.\n\n"
                            f"### Los que puedo tocar\n{listado}",
                    data={"projects": [n for n, _ in proyectos],
                          "sugerencias": cerca})
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

        vivos = self.vivos()
        if len(vivos) >= self.max_jobs:
            return SkillResult(
                ok=False, error="taller ocupado",
                speak=f"Ya tengo {len(vivos)} encargos en marcha. "
                      f"Espera a que acabe alguno, o dime que lo deje.",
                display=f"# Taller ocupado\n\n{len(vivos)} encargos "
                        f"corriendo (tope: {self.max_jobs}).\n\n"
                        + "\n".join(f"- `{e.ident}` {e.describe()}" for e in vivos),
                data={"jobs": len(vivos), "max_jobs": self.max_jobs})

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
    def _tools(self, escribe: bool, policy) -> tuple[list[str], list[str]]:
        """La caja de herramientas del encargo, ya filtrada por la politica.

        Un unico sitio para las dos rutas —lo que se anuncia y lo que se
        entrega al motor—, o el panel diria «Bash» mientras el agente corre
        sin el, que es la clase de mentira que hace inutil un aviso.
        """
        return _tools_permitidas(
            self.write_tools if escribe else self.read_tools, policy)

    def _lanzar(self, ctx: SkillContext, nombre: str, ruta: Path,
                tarea: str, escribe: bool) -> SkillResult:
        """Arranca el trabajo y devuelve el turno. Lo que sale de aqui es un
        acuse de recibo; el resultado llega por el bus al terminar."""
        encargo = Encargo(ident=f"e{next(self._contador)}", proyecto=nombre,
                          ruta=ruta, tarea=tarea, escribe=escribe)
        self._encargos[encargo.ident] = encargo
        encargo.task = asyncio.create_task(
            self._trabajar(ctx, encargo))
        # El encargo NO se borra del registro al terminar: se queda con su
        # estado. Preguntar «como fue lo de X» treinta segundos despues de
        # que acabara tiene que poder contestarse, y un dict que se vacia al
        # acabar contesta «no habia nada» a algo que si paso.
        encargo.task.add_done_callback(lambda _t: self._recorta())

        tools, retiradas = self._tools(escribe, ctx.policy)
        nota = (f"\n\n> Retiradas por politica: `{', '.join(retiradas)}`"
                if retiradas else "")

        return SkillResult(
            speak=f"Voy con ello, Jefe. {tarea.capitalize()}, en {nombre}. "
                  f"Te aviso cuando acabe.",
            display=(f"# En marcha\n\n**{nombre}** · `{ruta}`\n\n"
                     f"**Tarea:** {tarea}\n\n"
                     f"**Herramientas:** `{', '.join(tools)}`{nota}\n\n"
                     f"Corre en segundo plano. Te aviso al terminar."),
            data={"action": "delegate", "project": nombre, "path": str(ruta),
                  "task": tarea, "writes": escribe, "async": True,
                  "tools": tools, "tools_retiradas": retiradas})

    async def _trabajar(self, ctx: SkillContext, encargo: Encargo) -> None:
        nombre, ruta = encargo.proyecto, encargo.ruta
        tarea, escribe = encargo.tarea, encargo.escribe
        t0 = encargo.t0
        await BUS.emit("agent.started", project=nombre, path=str(ruta),
                       task=tarea, writes=escribe, ident=encargo.ident)

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
            tools, _ = self._tools(escribe, ctx.policy)
            kw = dict(cwd=str(ruta), timeout=self.timeout_s,
                      max_turns=self.max_turns, tools=tools,
                      permission_mode="acceptEdits" if escribe else "default")

            if hasattr(engine, "complete_agentic"):
                salida = await engine.complete_agentic(prompt, system=system, **kw)
            else:
                salida = await engine.complete(prompt, system=system,
                                               agentic=True, **kw)
        except asyncio.CancelledError:
            # Lo paro el usuario. No se avisa por `core.say`: acaba de
            # decirlo el, y repetirselo es ruido. El acuse ya se lo dio la
            # rama que cancela.
            encargo.estado = "cancelado"
            await BUS.emit("agent.cancelled", project=nombre, task=tarea,
                           ident=encargo.ident)
            raise
        except Exception as exc:
            encargo.estado = "fallido"
            await BUS.emit("agent.failed", project=nombre, task=tarea,
                           error=str(exc)[:300], ident=encargo.ident)
            await BUS.emit("core.say",
                           text=f"El encargo en {nombre} fallo. {str(exc)[:120]}",
                           display=f"# Encargo fallido\n\n**{nombre}** · {tarea}\n\n"
                                   f"```\n{exc}\n```",
                           skill=self.name)
            return

        ms = int((time.time() - t0) * 1000)
        encargo.estado = "hecho"
        resumen = self._resumen(salida)
        await BUS.emit("agent.done", project=nombre, task=tarea, ms=ms,
                       chars=len(salida), ident=encargo.ident)
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
    def _sugerir(text: str, proyectos: list[tuple[str, Path]]) -> list[str]:
        """Nombres que se parecen a alguna palabra de la frase.

        **Solo para preguntar.** Un parecido de 0.8 entre lo que oyo el STT y
        una carpeta es una buena pista y una pesima decision: la diferencia
        entre `friday` y `friday-docs` tambien es alta, y elegir mal cuesta
        que un agente escriba en el repo equivocado. Por eso esto devuelve
        una lista para leerla en voz alta, y no una ruta para trabajar.
        """
        palabras = [w for w in _fold(text).split() if len(w) >= 4]
        if not palabras:
            return []
        puntuados: list[tuple[float, str]] = []
        for nombre, _ruta in proyectos:
            clave = _fold(nombre)
            if len(clave) < 3:
                continue
            mejor = max((parecido(w, clave) for w in palabras), default=0.0)
            if mejor >= PARECIDO_MINIMO:
                puntuados.append((mejor, nombre))
        puntuados.sort(reverse=True)
        return [n for _s, n in puntuados]

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
