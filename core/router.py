"""El enrutador. Yo hablo, FRIDAY decide quien trabaja.

Cuatro caminos, del mas barato al mas caro:

  0. CONFIRMACION  hay una accion esperando un si. Nada mas importa.
  1. SEGUIMIENTO   la frase no se sostiene sola («y eso cuanto cuesta»):
                   es el turno anterior el que la explica.
  2. RAPIDO        regex de las skills. Sin latencia, sin motor. Cubre el 80%.
  2b. CHARLA       nadie reconocio nada y no hay verbo de accion: es
                   conversacion, y preguntarselo al motor cuesta un turno
                   entero de latencia para confirmar lo evidente.
  3. PENSADO       el motor clasifica y, si no encaja en nada, responde libre.
"""
from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from typing import Any

from memory.graph import Graph
from memory.vault import Vault
from skills import PendingAction, Skill, SkillContext, SkillResult

from .chat import Conversation, build_conversation
from .config import Config
from .engine import Engine, ask_json, enum_schema
from .policy import Policy

FAST_THRESHOLD = 0.62

CONFIRM = re.compile(r"^\s*(s[ií]|dale|adelante|confirmo?|confirmado|"
                     r"hazlo|procede|correcto|ok|okay|va)\s*[.!]?\s*$", re.I)
CANCEL = re.compile(r"^\s*(no|cancela|cancelar|olv[ií]dalo|d[eé]jalo|"
                    r"detente|para|abortar?|mejor no|stop)\s*[.!]?\s*$", re.I)

# ── seguimiento de conversacion ───────────────────────────────────
# Frases que no se sostienen solas, por anafora («eso») o por ser conectivo
# mas pregunta pelada («y por que?»). Tiene que ganarle al enrutado rapido:
# «y eso cuanto cuesta» dispara el `\bcuanto\b` de `metricas` y devuelve la
# CPU. Contra un disparador corto y comun el puntaje no puede ayudar.
FOLLOWUP = re.compile(
    r"(\b(eso|esa|ese|esos|esas|aquello|lo mismo|lo anterior|lo de antes|"
    r"lo que (dijiste|me dijiste|acabas de decir))\b"
    r"|^\s*(y|pero|entonces|osea|o sea)\s+(por\s+qu[eé]|para\s+qu[eé]|c[oó]mo|"
    r"cu[aá]ndo|d[oó]nde|qui[eé]n|cu[aá]nto|qu[eé])\b"
    r"|^\s*(y|pero|entonces)\s*[.?!]*\s*$"
    r"|^\s*(por\s+qu[eé]|c[oó]mo\s+as[ií])\s*[.?!]*\s*$"
    r"|^\s*(explicam?e|expl[ií]came|ampl[ií]a|profundiza|dame m[aá]s|"
    r"cu[eé]ntame m[aá]s|sigue|contin[uú]a)\b"
    r"|^\s*no\s+(te\s+)?entend[ií]\b)", re.I)

# Un verbo de accion cancela el seguimiento: «abre eso» lleva anafora pero
# es una orden, y las ordenes son de las skills.
ACTION = re.compile(
    r"\b(abre|abrir|lanza|ejecuta|inicia|arranca|cierra|enfoca|organiza|"
    r"mueve|renombra|borra|recuerda|apunta|anota|guarda|escribe|busca|"
    r"b[uú]scame|investiga|sube|baja|silencia|pausa|reproduce|bloquea|"
    r"copia|pega|cambia a)\b", re.I)


# comandos literales — no gastan motor
DIRECT = {
    r"^\s*(silencio|c[aá]llate|mute)\s*[.!]?\s*$": "_mute",
    r"^\s*(escucha|unmute|habla)\s*[.!]?\s*$": "_unmute",
    r"^\s*(repite|otra vez|de nuevo)\s*[.!]?\s*$": "_repeat",
    r"^\s*(reparar? (el )?grafo|arregla (los )?enlaces|heal)\s*[.!]?\s*$": "_heal",
    r"^\s*(qu[eé] puedes hacer|ayuda|capacidades)\s*[.!?]?\s*$": "_help",
    r"^\s*(cambiemos de tema|nuevo tema|empecemos de cero|"
    r"olvida (la conversaci[oó]n|el hilo))\s*[.!?]?\s*$": "_reset_chat",
}


@dataclass
class Route:
    skill: str
    confidence: float
    how: str              # fast | engine | fallback | direct | confirm
    scores: dict[str, float]


class Router:
    def __init__(self, cfg: Config, vault: Vault, graph: Graph, engine: Engine,
                 skills: dict[str, Skill], system: Any = None,
                 policy: Policy | None = None):
        self.cfg = cfg
        self.vault = vault
        self.graph = graph
        self.engine = engine
        self.skills = skills
        self.system = system
        self.policy = policy
        self.last_result: SkillResult | None = None
        self.pending: PendingAction | None = None
        self.chat: Conversation = build_conversation(cfg)
        self.fast_chat = bool(cfg.get("chat.fast_conversation", True))
        self.smalltalk_words = int(cfg.get("chat.smalltalk_max_words", 12))

    # ── contexto ──────────────────────────────────────────────────
    def _ctx(self, text: str = "") -> SkillContext:
        return SkillContext(cfg=self.cfg, vault=self.vault, graph=self.graph,
                            engine=self.engine, text=text,
                            system=self.system, policy=self.policy)

    # ── seguimiento ───────────────────────────────────────────────
    def is_followup(self, text: str) -> bool:
        """¿Continua el turno anterior en vez de empezar uno? Hilo vivo,
        anafora y ningun verbo de accion — las tres."""
        if not self.chat.active:
            return False
        return bool(FOLLOWUP.search(text)) and not ACTION.search(text)

    def _is_smalltalk(self, text: str, scores: dict[str, float]) -> bool:
        """¿Se puede dar por conversacion sin preguntarle al motor?

        La condicion fuerte es que **ninguna** skill haya reconocido nada: el
        paso pensado existe para rescatar frases que las regex no cubren, y
        si algo puntuo, esa duda vale los cuatro segundos.
        """
        if not self.fast_chat or any(scores.values()):
            return False
        return (not ACTION.search(text)
                and len(text.split()) <= self.smalltalk_words)

    # ── decidir ───────────────────────────────────────────────────
    async def decide(self, text: str) -> Route:
        clean = text.strip()

        # 0. una accion espera confirmacion: tiene prioridad sobre todo
        if self.pending is not None:
            if self.pending.expired:
                self.pending = None
            elif CONFIRM.match(clean):
                return Route("_confirm", 1.0, "confirm", {})
            elif CANCEL.match(clean):
                return Route("_cancel_pending", 1.0, "confirm", {})

        for pat, name in DIRECT.items():
            if re.match(pat, clean, re.I):
                return Route(name, 1.0, "direct", {})

        # 1. continuacion del hilo: la frase depende del turno anterior
        if self.is_followup(clean):
            return Route("none", 0.9, "chat", {})

        scores = {n: s.matches(clean) for n, s in self.skills.items()}
        best = max(scores, key=scores.get) if scores else ""
        if best and scores[best] >= FAST_THRESHOLD:
            return Route(best, scores[best], "fast", scores)

        # 2b. charla evidente: nadie reconocio nada, no hay verbo de accion y
        # la frase es corta. Un turno de conversacion gastaba DOS llamadas al
        # motor —clasificar y luego responder— y por `claude_code` cada una
        # ronda los cuatro segundos. Esta es la que sobra.
        if self._is_smalltalk(clean, scores):
            return Route("none", 0.6, "chat-fast", scores)

        catalog = "\n".join(f"- {n}: {s.description}" for n, s in self.skills.items())
        prompt = (
            f"SKILLS:\n{catalog}\n"
            "- none: conversacion. Charla, opiniones, preguntas generales, "
            "desahogos, o cualquier cosa que no pida una accion concreta.\n\n"
            # «none» se nombra dos veces: un modelo pequeño casi nunca elige
            # la ultima opcion de una lista de catorce.
            "Si el usuario no te esta PIDIENDO que hagas algo, es \"none\".\n"
            "Tambien es \"none\" si te pregunta por TI (quien eres, como "
            "estas, que sabes hacer) o si es una pregunta de conocimiento "
            "general que se contesta hablando.\n\n"
            # La peticion al final, pegada a la respuesta: con un 8B, es lo
            # que mas mueve el acierto de esta llamada.
            f"PETICION DE VOZ:\n\"{clean}\"\n\n"
            "Enruta esa peticion a UNA skill de la lista.\n\n"
            'Responde SOLO: {"skill": "nombre", "confidence": 0.85, '
            '"why": "5 palabras"}'
        )
        schema = enum_schema({"skill": list(self.skills) + ["none"],
                              "confidence": "number", "why": "string"},
                             requeridos=["skill"])
        try:
            data = await ask_json(self.engine, prompt, schema=schema) or {}
            name = str(data.get("skill", "none")).strip().lower()
            try:
                conf = float(data.get("confidence", 0.5))
            except (TypeError, ValueError):
                conf = 0.5          # el numero es informativo; el nombre manda
            return Route(name if name in self.skills else "none", conf, "engine", scores)
        except Exception:
            return Route(best or "none", scores.get(best, 0.0), "fallback", scores)

    # ── ejecutar ──────────────────────────────────────────────────
    async def dispatch(self, text: str, route: Route | None = None) -> tuple[Route, SkillResult]:
        route = route or await self.decide(text)
        t0 = time.time()

        if route.skill.startswith("_"):
            res = await self._builtin(route.skill)
        elif route.skill in self.skills:
            ctx = self._ctx(text)
            try:
                res = await self.skills[route.skill].run(ctx)
            except Exception as exc:
                res = SkillResult(ok=False, error=f"{type(exc).__name__}: {exc}",
                                  speak=f"La skill {route.skill} fallo.",
                                  display=f"# Error en `{route.skill}`\n\n```\n{exc}\n```")
        else:
            res = await self._freeform(text)

        # una skill que devuelve accion pendiente la deja armada aqui
        if res.pending is not None:
            self.pending = res.pending

        res.data["_ms"] = int((time.time() - t0) * 1000)
        res.data["_route"] = {"skill": route.skill, "how": route.how,
                              "confidence": route.confidence}
        res.data["_pending"] = self.pending.describe if self.pending else ""

        if res.ok and not route.skill.startswith("_"):
            self.last_result = res

        # El hilo recoge tambien lo que atendio una skill, o «y eso cuanto
        # pesa» tras un briefing no tendria a que referirse. Se guarda lo
        # hablado, no el markdown: es lo que el usuario oyo.
        if not route.skill.startswith("_"):
            self.chat.add("user", text)
            self.chat.add("assistant", res.speak or res.error)

        return route, res

    # ── conversacion libre ────────────────────────────────────────
    def _recall(self, text: str) -> tuple[list, str]:
        """Notas que vienen al caso, con su vecindad en el grafo.

        Recorre y parsea el vault entero (no hay indice, regla 1), asi que va
        en un hilo: hacerlo en el bucle de eventos congela el HUD y retrasa
        cualquier evento del bus justo antes de la parte lenta del turno.
        """
        hits = self.vault.search(text, limit=3)
        ctxt = self.graph.context_for([h.title for h in hits], depth=1,
                                      max_chars=3500) if hits else ""
        return hits, ctxt

    async def _freeform(self, text: str) -> SkillResult:
        """Conversar: prosa, sin contrato JSON.

        Pedir JSON aqui encoge las respuestas a una frase de tramite y con un
        8B rompe el formato cada tanto. La persona da el tono, no la
        estructura.
        """
        historia = self.chat.transcript(limit=int(self.cfg.get("chat.max_chars", 4000)))
        hits, ctxt = await asyncio.to_thread(self._recall, text)

        prompt = (
            (f"CONVERSACION HASTA AHORA:\n{historia}\n\n" if historia else "") +
            (f"NOTAS DEL VAULT QUE PUEDEN VENIR AL CASO:\n{ctxt}\n\n" if ctxt else "") +
            f"{self.chat.user_title} dice: \"{text}\"\n\n"
            "Responde como en una conversacion hablada: directo, sin preambulo "
            "y sin ofrecer ayuda al final. Si la frase se refiere a algo dicho "
            "antes, resuelvelo con la conversacion de arriba. Si no lo sabes, "
            "dilo. Texto plano o markdown simple; nada de JSON."
        )
        try:
            raw = (await self.engine.complete(prompt, system=self.cfg.persona())).strip()
            if not raw:
                return SkillResult(ok=False, error="respuesta vacia",
                                   speak="Me quede en blanco, Jefe.",
                                   display="# Sin respuesta")
            return SkillResult(speak=self._for_voice(raw), display=raw,
                               data={"sources": [h.rel for h in hits],
                                     "turns": len(self.chat)})
        except Exception as exc:
            return SkillResult(ok=False, error=str(exc),
                               speak="El motor no responde.",
                               display=f"# Motor caido\n\n```\n{exc}\n```")

    def _for_voice(self, text: str) -> str:
        """Recorta por frases enteras, nunca a media palabra: cortarse a
        mitad de una idea suena peor que una respuesta corta. El panel
        siempre lleva el texto completo."""
        limit = int(self.cfg.get("chat.speak_max_chars", 700))
        plain = re.sub(r"\s+", " ", text).strip()
        if len(plain) <= limit:
            return plain

        out = ""
        for frase in re.split(r"(?<=[.!?])\s+", plain):
            if len(out) + len(frase) + 1 > limit:
                break
            out = f"{out} {frase}".strip()
        return out or plain[:limit].rsplit(" ", 1)[0]

    # ── comandos internos ─────────────────────────────────────────
    async def _builtin(self, name: str) -> SkillResult:
        if name == "_confirm":
            action = self.pending
            self.pending = None
            if action is None or action.expired:
                return SkillResult(speak="Ya no hay nada pendiente.",
                                   display="# Nada pendiente")
            try:
                return action.run()
            except Exception as exc:
                return SkillResult(ok=False, error=str(exc),
                                   speak="Fallo al aplicar.",
                                   display=f"# Fallo\n\n```\n{exc}\n```")

        if name == "_cancel_pending":
            desc = self.pending.describe if self.pending else ""
            self.pending = None
            return SkillResult(
                speak="Cancelado." if desc else "No habia nada pendiente.",
                display=f"# Cancelado\n\n~~{desc}~~" if desc else "# Nada pendiente")

        if name == "_reset_chat":
            previos = len(self.chat)
            self.chat.clear()
            return SkillResult(
                speak="Hilo limpio, Jefe." if previos else "No habia hilo que limpiar.",
                display=f"# Conversacion reiniciada\n\n{previos} turnos descartados.",
                data={"cleared": previos})

        if name == "_repeat":
            return self.last_result or SkillResult(speak="No hay nada que repetir.",
                                                   display="—")

        if name == "_heal":
            created = self.graph.heal()
            return SkillResult(
                speak=f"Cree {len(created)} stubs. Grafo reparado." if created
                      else "No hay enlaces rotos.",
                display="# Reparacion del grafo\n\n" +
                        ("\n".join(f"- [[{c}]]" for c in created) or "Nada roto."),
                data={"created": created}, writes=created)

        if name == "_help":
            lines = ["# Capacidades", ""]
            for s in self.skills.values():
                falta = ""
                if s.needs and self.system is not None:
                    missing = [n for n in s.needs if getattr(self.system, n, None) is None]
                    falta = f"  _(sin {', '.join(missing)})_" if missing else ""
                lines.append(f"- **{s.name}** — {s.description}{falta}")
            return SkillResult(speak=f"{len(self.skills)} capacidades activas.",
                               display="\n".join(lines),
                               data={"skills": list(self.skills)})

        return SkillResult(speak="", display="", data={"command": name})

    def catalog(self) -> list[dict[str, Any]]:
        return [s.spec() for s in self.skills.values()]
