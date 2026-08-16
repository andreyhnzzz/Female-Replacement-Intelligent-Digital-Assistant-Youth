"""El enrutador. Yo hablo, FRIDAY decide quien trabaja.

Dos caminos:
  1. RAPIDO   — regex de las skills. Sin latencia, sin motor. Cubre el 80%.
  2. PENSADO  — si nada gana claro, el motor clasifica y/o responde libre.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any

from memory.graph import Graph
from memory.vault import Vault
from skills import Skill, SkillContext, SkillResult

from .config import Config
from .engine import Engine

FAST_THRESHOLD = 0.62

# comandos literales del HUD / voz — no gastan motor
DIRECT = {
    r"^\s*(silencio|c[aá]llate|mute)\s*$": ("_mute", {}),
    r"^\s*(escucha|unmute|habla)\s*$": ("_unmute", {}),
    r"^\s*(repite|otra vez)\s*$": ("_repeat", {}),
    r"^\s*(cancela|para|detente|stop)\s*$": ("_cancel", {}),
    r"^\s*(reparar? grafo|arregla enlaces|heal)\s*$": ("_heal", {}),
}


@dataclass
class Route:
    skill: str
    confidence: float
    how: str              # fast | engine | fallback | direct
    scores: dict[str, float]


class Router:
    def __init__(self, cfg: Config, vault: Vault, graph: Graph,
                 engine: Engine, skills: dict[str, Skill]):
        self.cfg = cfg
        self.vault = vault
        self.graph = graph
        self.engine = engine
        self.skills = skills
        self.last_result: SkillResult | None = None

    # -- decidir ------------------------------------------------------
    async def decide(self, text: str) -> Route:
        clean = text.strip()
        for pat, (name, _) in DIRECT.items():
            if re.match(pat, clean, re.I):
                return Route(name, 1.0, "direct", {})

        scores = {n: s.matches(clean) for n, s in self.skills.items()}
        best = max(scores, key=scores.get) if scores else ""
        if best and scores[best] >= FAST_THRESHOLD:
            return Route(best, scores[best], "fast", scores)

        # camino pensado: que el motor elija
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
            if name in self.skills:
                return Route(name, conf, "engine", scores)
            return Route("none", conf, "engine", scores)
        except Exception:
            return Route(best or "none", scores.get(best, 0.0), "fallback", scores)

    # -- ejecutar -----------------------------------------------------
    async def dispatch(self, text: str, route: Route | None = None) -> tuple[Route, SkillResult]:
        route = route or await self.decide(text)
        t0 = time.time()

        if route.skill.startswith("_"):
            res = await self._builtin(route.skill)
        elif route.skill in self.skills:
            ctx = SkillContext(cfg=self.cfg, vault=self.vault, graph=self.graph,
                               engine=self.engine, text=text)
            try:
                res = await self.skills[route.skill].run(ctx)
            except Exception as exc:
                res = SkillResult(ok=False, error=f"{type(exc).__name__}: {exc}",
                                  speak=f"La skill {route.skill} fallo.",
                                  display=f"# Error en `{route.skill}`\n\n```\n{exc}\n```")
        else:
            res = await self._freeform(text)

        res.data["_ms"] = int((time.time() - t0) * 1000)
        res.data["_route"] = {"skill": route.skill, "how": route.how,
                              "confidence": route.confidence}
        if res.ok and not route.skill.startswith("_"):
            self.last_result = res
        return route, res

    # -- conversacion libre -------------------------------------------
    async def _freeform(self, text: str) -> SkillResult:
        hits = self.vault.search(text, limit=3)
        ctxt = self.graph.context_for([h.title for h in hits], depth=1, max_chars=3500) \
            if hits else ""
        prompt = (
            (f"CONTEXTO DEL VAULT:\n{ctxt}\n\n" if ctxt else "") +
            f"El usuario dice: \"{text}\"\n\n"
            "Responde breve. Devuelve SOLO este JSON:\n"
            '{"speak": "1-2 frases para decir en voz alta", "display": "markdown para el HUD"}'
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

    # -- comandos internos --------------------------------------------
    async def _builtin(self, name: str) -> SkillResult:
        if name == "_repeat":
            last = self.last_result
            return last or SkillResult(speak="No hay nada que repetir.", display="—")
        if name == "_heal":
            created = self.graph.heal()
            return SkillResult(
                speak=f"Cree {len(created)} stubs. Grafo reparado." if created
                      else "No hay enlaces rotos.",
                display="# Reparacion del grafo\n\n" +
                        ("\n".join(f"- [[{c}]]" for c in created) or "Nada roto."),
                data={"created": created}, writes=created)
        return SkillResult(speak="", display="", data={"command": name})

    def catalog(self) -> list[dict[str, Any]]:
        return [s.spec() for s in self.skills.values()]
