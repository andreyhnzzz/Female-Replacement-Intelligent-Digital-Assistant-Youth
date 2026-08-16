"""Registro de skills. Agregar una skill = crear el archivo y ponerla en el toml."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .agenda import AgendaSkill
from .base import Skill, SkillContext, SkillResult
from .inbox import InboxSkill
from .metricas import MetricasSkill
from .plan import PlanSkill
from .vault import VaultSkill

if TYPE_CHECKING:
    from core.config import Config

ALL_SKILLS: dict[str, type[Skill]] = {
    "metricas": MetricasSkill,
    "inbox": InboxSkill,
    "plan": PlanSkill,
    "vault": VaultSkill,
    "agenda": AgendaSkill,
}


def build_skills(cfg: "Config") -> dict[str, Skill]:
    enabled = cfg.get("skills.enabled", list(ALL_SKILLS))
    out: dict[str, Skill] = {}
    for name in enabled:
        cls = ALL_SKILLS.get(name)
        if cls is None:
            print(f"[skills] desconocida, la ignoro: {name}")
            continue
        out[name] = cls(cfg)
    return out


__all__ = ["Skill", "SkillContext", "SkillResult", "ALL_SKILLS", "build_skills"]
