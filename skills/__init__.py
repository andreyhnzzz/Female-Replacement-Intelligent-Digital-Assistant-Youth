"""Registro de skills. Agregar una skill = crear el archivo y ponerla en el toml."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .agenda import AgendaSkill
from .archivos import ArchivosSkill
from .base import PendingAction, Skill, SkillContext, SkillResult
from .inbox import InboxSkill
from .metricas import MetricasSkill
from .motor import MotorSkill
from .noticias import NoticiasSkill
from .ordenador import OrdenadorSkill
from .pantalla import PantallaSkill
from .plan import PlanSkill
from .sistema import SistemaSkill
from .vault import VaultSkill
from .web import WebSkill

if TYPE_CHECKING:
    from core.config import Config

ALL_SKILLS: dict[str, type[Skill]] = {
    # memoria y planeacion
    "metricas": MetricasSkill,
    "inbox": InboxSkill,
    "plan": PlanSkill,
    "vault": VaultSkill,
    "agenda": AgendaSkill,
    # manos sobre la computadora
    "sistema": SistemaSkill,
    "archivos": ArchivosSkill,
    "pantalla": PantallaSkill,
    "ordenador": OrdenadorSkill,
    # el mundo de fuera
    "noticias": NoticiasSkill,
    "web": WebSkill,
    # sobre si misma
    "motor": MotorSkill,
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


__all__ = ["Skill", "SkillContext", "SkillResult", "PendingAction",
           "ALL_SKILLS", "build_skills"]
