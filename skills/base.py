"""Contrato de skill. Una skill es una mano de FRIDAY: entra texto, sale SkillResult."""
from __future__ import annotations

import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from core.config import Config
    from core.engine import Engine
    from core.policy import Policy
    from memory.graph import Graph
    from memory.vault import Vault
    from system.ports import SystemAccess


@dataclass(slots=True)
class PendingAction:
    """Una accion planeada que espera el si del usuario.

    Existe porque el STT se equivoca. Antes de mover cuarenta archivos,
    FRIDAY describe lo que va a hacer y espera confirmacion explicita.

    `run` puede ser sincrona o devolver un awaitable. Casi todas son
    sincronas —mover archivos, bajar el volumen— pero la que rearranca un
    turno entero tras el eco de una transcripcion dudosa tiene que poder
    esperar al motor. Quien la ejecuta (`Router._builtin`) resuelve las dos.
    """
    describe: str
    run: Callable[[], "SkillResult | Any"]
    created: float = field(default_factory=time.time)
    ttl_s: float = 120.0

    @property
    def expired(self) -> bool:
        return (time.time() - self.created) > self.ttl_s


@dataclass
class SkillContext:
    """Todo lo que una skill puede tocar. Nada global, nada oculto.

    `system` llega como el agregado de puertos abstractos: la skill nunca
    sabe si corre sobre Windows o sobre otra cosa.
    """
    cfg: "Config"
    vault: "Vault"
    graph: "Graph"
    engine: "Engine"
    text: str = ""                                  # lo que dijo el usuario
    slots: dict[str, Any] = field(default_factory=dict)   # extraido por el router
    system: "SystemAccess | None" = None
    policy: "Policy | None" = None


@dataclass(frozen=True, slots=True)
class Entrega:
    """Lo que una skill **resolvio** y otra puede consumir.

    Es la pieza que permite que un turno cruce dos capacidades sin que
    ninguna de las dos sepa que existe la otra. `archivos` encuentra un PDF y
    lo entrega; `sistema` lo abre. Ni una importa a la otra (regla 5): el
    router es quien pasa el testigo.

    **Tipada a proposito.** La alternativa —pasar la frase entera a la
    segunda skill— es justo lo que no puede hacerse: «abrelo» enrutado solo
    haria que `sistema` buscara una aplicacion llamada «lo», que es la forma
    exacta del incidente del 17/08/2026. La segunda skill no reinterpreta
    nada: recibe un objeto ya resuelto o no se ejecuta.
    """
    kind: str                        # archivo | carpeta | url | texto
    valor: str                       # la ruta, la URL o el texto
    etiqueta: str = ""               # como se nombra en voz alta

    def __str__(self) -> str:
        return self.etiqueta or self.valor


@dataclass
class SkillResult:
    speak: str = ""                                  # voz: corto
    display: str = ""                                # panel: markdown
    data: dict[str, Any] = field(default_factory=dict)   # numeros para la UI
    writes: list[str] = field(default_factory=list)      # rutas escritas
    ok: bool = True
    error: str = ""
    pending: PendingAction | None = None                 # espera confirmacion
    entrega: Entrega | None = None                       # para encadenar

    def to_json(self) -> dict[str, Any]:
        return {"speak": self.speak, "display": self.display, "data": self.data,
                "writes": self.writes, "ok": self.ok, "error": self.error,
                "pending": self.pending.describe if self.pending else ""}


class Skill(ABC):
    name: str = "skill"
    description: str = ""
    triggers: list[str] = []          # patrones regex para el enrutado rapido
    needs: tuple[str, ...] = ()       # puertos de SystemAccess requeridos

    # ¿Que pasa si el enrutado se equivoca y llega aqui una frase que no era?
    #
    #   "inerte"  se lee algo y se contesta. El coste de fallar es una
    #             respuesta rara, y el usuario repite la frase.
    #   "efecto"  se lanza, se mueve, se apaga o se borra algo. El coste de
    #             fallar es que pasa.
    #
    # No es documentacion: `core/router.py` le exige mas confianza a las de
    # efecto antes de dejarlas actuar. El enrutado es probabilistico y
    # siempre lo sera; lo que no puede ser igual de probabilistico es lo que
    # pasa cuando acierta a medias. Ver el incidente del 17/08/2026 en el
    # CLAUDE.md — una frase sobre si misma acabo abriendo WinRAR.
    riesgo: str = "inerte"

    # Tipos de `Entrega` que esta skill sabe consumir cuando el turno viene
    # encadenado. Vacio = no participa como segunda mitad de una frase.
    #
    # Declararlo aqui y no adivinarlo es lo que hace que el encadenado falle
    # en seco en vez de a lo loco: si la segunda skill no acepta lo que la
    # primera resolvio, no se ejecuta y se dice. Nadie reinterpreta la frase.
    acepta: tuple[str, ...] = ()

    @property
    def tiene_efecto(self) -> bool:
        return self.riesgo == "efecto"

    def __init__(self, ctx_cfg: "Config"):
        self.cfg = ctx_cfg
        self.opts: dict[str, Any] = ctx_cfg.get(f"skills.{self.name}", {}) or {}

    def matches(self, text: str) -> float:
        """Confianza 0..1 de que esta skill debe atender el texto.

        Cuatro senales, en orden de peso:

          1. Nombrarme directo ("...en la agenda") gana casi siempre.
          2. **Especificidad del disparador**: cuanto texto literal reconoci.
             Se mide en absoluto, no como fraccion de la frase — si midieras
             cobertura, "recuerda que <parrafo largo>" perderia por diluirse,
             y "que tengo abierto" empataria con el "que tengo" de inbox.
          3. Empezar la frase: un imperativo al inicio es una orden.
          4. Cuantos patrones distintos pegan.
        """
        low = text.lower()
        hits = [m for m in (re.search(p, low) for p in self.triggers) if m]
        if not hits:
            return 0.0

        longest = max(len(m.group(0)) for m in hits)
        score = 0.55
        score += min(longest / 20.0, 1.0) * 0.30
        if any(m.start() <= 1 for m in hits):
            score += 0.08
        score += min(len(hits) - 1, 3) * 0.04
        if re.search(rf"\b{re.escape(self.name)}\b", low):
            score += 0.35          # me llamo por mi nombre: no hay ambiguedad
        return round(min(score, 1.0), 3)

    def unavailable(self, ctx: SkillContext) -> str:
        """Que puerto falta para poder trabajar. Cadena vacia = todo listo."""
        if not self.needs:
            return ""
        if ctx.system is None:
            return "no tengo acceso al sistema en esta plataforma"
        faltan = [n for n in self.needs if getattr(ctx.system, n, None) is None]
        return f"me falta acceso a: {', '.join(faltan)}" if faltan else ""

    @abstractmethod
    async def run(self, ctx: SkillContext) -> SkillResult:
        ...

    def spec(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description,
                "triggers": self.triggers, "needs": list(self.needs)}
