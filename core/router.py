"""El enrutador. Yo hablo, FRIDAY decide quien trabaja.

Tres caminos, del mas barato al mas caro:

  0. CONFIRMACION  hay una accion esperando un si. Nada mas importa.
  1. RAPIDO        regex de las skills. Sin latencia, sin motor. Cubre el 80%.
  2. PENSADO       el motor clasifica y, si no encaja en nada, responde libre.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any

from memory.graph import Graph
from memory.vault import Vault
from skills import PendingAction, Skill, SkillContext, SkillResult

from .config import Config
from .engine import Engine
from .policy import Policy

FAST_THRESHOLD = 0.62

CONFIRM = re.compile(r"^\s*(s[ií]|dale|adelante|confirmo?|confirmado|"
                     r"hazlo|procede|correcto|ok|okay|va)\s*[.!]?\s*$", re.I)
CANCEL = re.compile(r"^\s*(no|cancela|cancelar|olv[ií]dalo|d[eé]jalo|"
                    r"detente|para|abortar?|mejor no|stop)\s*[.!]?\s*$", re.I)

# comandos literales — no gastan motor
DIRECT = {
    r"^\s*(silencio|c[aá]llate|mute)\s*[.!]?\s*$": "_mute",
    r"^\s*(escucha|unmute|habla)\s*[.!]?\s*$": "_unmute",
    r"^\s*(repite|otra vez|de nuevo)\s*[.!]?\s*$": "_repeat",
    r"^\s*(reparar? (el )?grafo|arregla (los )?enlaces|heal)\s*[.!]?\s*$": "_heal",
    r"^\s*(qu[eé] puedes hacer|ayuda|capacidades)\s*[.!?]?\s*$": "_help",
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

    # ── contexto ──────────────────────────────────────────────────
    def _ctx(self, text: str = "") -> SkillContext:
        return SkillContext(cfg=self.cfg, vault=self.vault, graph=self.graph,
                            engine=self.engine, text=text,
                            system=self.system, policy=self.policy)

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

        scores = {n: s.matches(clean) for n, s in self.skills.items()}
        best = max(scores, key=scores.get) if scores else ""
        if best and scores[best] >= FAST_THRESHOLD:
            return Route(best, scores[best], "fast", scores)

        catalog = "\n".join(f"- {n}: {s.description}" for n, s in self.skills.items())
        prompt = (
            f"Enruta esta peticion de voz a UNA skill.\n\nPETICION: \"{clean}\"\n\n"
            f"SKILLS:\n{catalog}\n- none: no encaja en ninguna, conversacion libre\n\n"
            'Responde SOLO: {"skill": "nombre", "confidence": 0.0-1.0, "why": "5 palabras"}'
        )
        try:
            data = self.engine.extract_json(await self.engine.complete(prompt)) or {}
            name = str(data.get("skill", "none")).strip()
            conf = float(data.get("confidence", 0.5))
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
        return route, res

    # ── conversacion libre ────────────────────────────────────────
    async def _freeform(self, text: str) -> SkillResult:
        hits = self.vault.search(text, limit=3)
        ctxt = self.graph.context_for([h.title for h in hits], depth=1, max_chars=3500) \
            if hits else ""
        prompt = (
            (f"CONTEXTO DEL VAULT:\n{ctxt}\n\n" if ctxt else "") +
            f"El usuario dice: \"{text}\"\n\n"
            "Responde breve. Devuelve SOLO este JSON:\n"
            '{"speak": "1-2 frases para decir en voz alta", "display": "markdown para el panel"}'
        )
        try:
            raw = await self.engine.complete(prompt, system=self.cfg.persona())
            data = self.engine.extract_json(raw)
            if data and data.get("speak"):
                return SkillResult(speak=str(data["speak"])[:400],
                                   display=str(data.get("display") or data["speak"]),
                                   data={"sources": [h.rel for h in hits]})
            plain = re.sub(r"\s+", " ", raw).strip()
            return SkillResult(speak=plain[:280], display=raw,
                               data={"sources": [h.rel for h in hits]})
        except Exception as exc:
            return SkillResult(ok=False, error=str(exc),
                               speak="El motor no responde.",
                               display=f"# Motor caido\n\n```\n{exc}\n```")

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
