"""Registro de skills. Agregar una skill = crear el archivo y ponerla en el toml."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .agenda import AgendaSkill
from .archivos import ArchivosSkill
from core.bus import BUS

from .base import (Entrega, PendingAction, Skill, SkillContext,
                   SkillResult)
from .documentos import DocumentosSkill
from .inbox import InboxSkill
from .memoria import MemoriaSkill
from .metricas import MetricasSkill
from .motor import MotorSkill
from .noticias import NoticiasSkill
from .ordenador import OrdenadorSkill
from .pantalla import PantallaSkill
from .plan import PlanSkill
from .sistema import SistemaSkill
from .taller import TallerSkill
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
    "memoria": MemoriaSkill,
    # manos sobre la computadora
    "sistema": SistemaSkill,
    "archivos": ArchivosSkill,
    "pantalla": PantallaSkill,
    "ordenador": OrdenadorSkill,
    "taller": TallerSkill,
    "documentos": DocumentosSkill,
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
            # Una skill mal escrita en `skills.enabled` es un error de
            # configuracion silencioso: la capacidad simplemente no esta.
            BUS.report(f"skill desconocida en skills.enabled, la ignoro: "
                       f"{name}", origen="skills")
            continue
        out[name] = cls(cfg)
    return out


__all__ = ["Skill", "SkillContext", "SkillResult", "PendingAction",
           "Entrega", "ALL_SKILLS", "build_skills"]
