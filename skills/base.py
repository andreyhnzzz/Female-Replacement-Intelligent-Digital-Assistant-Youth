"""Contrato de skill. Una skill es una mano de FRIDAY: entra texto, sale SkillResult."""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from core.config import Config
    from core.engine import Engine
    from memory.graph import Graph
    from memory.vault import Vault


@dataclass
class SkillContext:
    """Todo lo que una skill puede tocar. Nada global, nada oculto."""
    cfg: "Config"
    vault: "Vault"
    graph: "Graph"
    engine: "Engine"
    text: str = ""                                  # lo que dijo el usuario
    slots: dict[str, Any] = field(default_factory=dict)   # extraido por el router


@dataclass
class SkillResult:
    speak: str = ""                                  # voz: corto
    display: str = ""                                # HUD: markdown
    data: dict[str, Any] = field(default_factory=dict)   # numeros para los paneles
    writes: list[str] = field(default_factory=list)      # rutas escritas
    ok: bool = True
    error: str = ""

    def to_json(self) -> dict[str, Any]:
        return {"speak": self.speak, "display": self.display, "data": self.data,
                "writes": self.writes, "ok": self.ok, "error": self.error}


class Skill(ABC):
    name: str = "skill"
    description: str = ""
    triggers: list[str] = []          # patrones regex para el enrutado rapido

    def __init__(self, ctx_cfg: "Config"):
        self.cfg = ctx_cfg
        self.opts: dict[str, Any] = ctx_cfg.get(f"skills.{self.name}", {}) or {}

    def matches(self, text: str) -> float:
        """Confianza 0..1 de que esta skill debe atender el texto.

        Tres senales, en orden de peso:
          1. Nombrarme directo ("...en la agenda") gana casi siempre.
          2. Cobertura del patron sobre la frase.
          3. Cuantos patrones distintos pegan.
        """
        low = text.lower()
        hits = [m for m in (re.search(p, low) for p in self.triggers) if m]
        if not hits:
            return 0.0
        cover = max(len(m.group(0)) for m in hits) / max(len(low), 1)
        score = 0.55 + min(cover, 0.30) + min(len(hits) - 1, 3) * 0.04
        if re.search(rf"\b{re.escape(self.name)}\b", low):
            score += 0.35          # me llamo por mi nombre: no hay ambiguedad
        return round(min(score, 1.0), 3)

    @abstractmethod
    async def run(self, ctx: SkillContext) -> SkillResult:
        ...

    def spec(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description,
                "triggers": self.triggers}
