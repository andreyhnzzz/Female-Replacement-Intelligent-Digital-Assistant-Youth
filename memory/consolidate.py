"""Consolidacion de la memoria: muchas diarias viejas -> un solo markdown.

Sin indice (regla 1), el coste de cada lectura del vault lo marca el numero de
archivos: `Vault.search` abre y puntua uno por uno. Las notas diarias crecen a
una por dia y casi todas sus lineas caducan al cumplirse, asi que consolidarlas
es a la vez menos disco y menos trabajo por busqueda.

    raw/2026-07-*.md  ->  clasificar  ->  comprimir  ->  raw/Memoria consolidada.md
                            (regex)       (motor)         + originales a .trash/

Las tres fases estan separadas a proposito, y no es estetica: `plan` y
`summarize` son consultas —lentas, sin efecto— y `commit` es el unico comando.
Quien lo llama puede tomar el candado del turno solo para el ultimo paso; si
envuelve los tres, FRIDAY deja de responder mientras el motor resume.

Invariantes:

1. Python clasifica, el motor comprime. Si el motor falla, los apuntes
   esenciales pasan tal cual: peor resumen, pero no es perdida.
2. Nada se retira antes de releer el consolidado del disco.
3. Solo diarias de `raw/`. `wiki/` y `outputs/` son notas con nombre propio.
4. Retirar pasa por `policy.can_prune()`, y no borra: mueve a `.trash/`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from core.engine import ask_json

from .vault import Note, Vault

# Ordenes que se agotan al cumplirse: describen un momento, no un hecho.
_RUTINA = re.compile(
    r"\b(abre|abrir|abri|cierra|cerrar|lanza|ejecuta|arranca|minimiza|"
    r"maximiza|enfoca|ocultar?|oculta|sube|subir|baja|bajar|silencia|"
    r"mutea|desmutea|pausa|pausar|reanuda|reproduce|siguiente|anterior|"
    r"pon(?:me)? (?:musica|el?\s|la\s)|volumen|captura|pantallazo|"
    r"que hora|la hora|que dia es|copia|pega|portapapeles|"
    r"cambia a|cambiate a|metricas|memoria|cpu|bateria|"
    r"busca en (?:google|youtube|internet)|buscalo|"
    r"que tengo abierto|hola|gracias|adios|hasta luego|prueba|test)\b",
    re.I)

# Rastros de una skill cuyo resultado ya vive en su propio archivo.
_KIND_RUTINA = frozenset({"inbox", "plan", "noticias", "pantalla"})

# Lo dicho para ser recordado (`vault`) y lo que tiene fecha (`agenda`).
_KIND_ESENCIAL = frozenset({"vault", "agenda"})

# `- \`09:14\` **voz** — texto`
_APUNTE = re.compile(r"^\s*-\s*`(\d{1,2}:\d{2})`\s*\*\*([\w-]+)\*\*\s*—\s*(.+)$")

# Solo `esencial` es obligatorio: un campo requerido no se piensa, se rellena.
_ESQUEMA = {
    "type": "object",
    "properties": {
        "titulo": {"type": "string"},
        "esencial": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["esencial"],
}


@dataclass(frozen=True, slots=True)
class Apunte:
    fecha: str
    kind: str
    text: str

    def __str__(self) -> str:
        return f"{self.fecha} · {self.text}"


@dataclass
class Plan:
    """Que se consolidaria. Se puede mirar sin ejecutar nada."""
    sources: list[Path] = field(default_factory=list)
    esencia: list[Apunte] = field(default_factory=list)
    rutina: int = 0
    desde: str = ""
    hasta: str = ""
    bytes: int = 0

    def __bool__(self) -> bool:
        return bool(self.sources)

    @property
    def rango(self) -> str:
        return self.desde if self.desde == self.hasta else f"{self.desde} → {self.hasta}"


@dataclass(frozen=True, slots=True)
class Resumen:
    """Lo que devolvio la fase lenta. Sin efectos: es solo texto."""
    lineas: list[str]
    titulo: str = ""
    by_engine: bool = False


@dataclass
class Report:
    ok: bool = True
    reason: str = ""
    rango: str = ""
    notes: int = 0            # diarias consolidadas
    kept: int = 0             # apuntes que sobrevivieron
    dropped: int = 0          # rutinas omitidas o fundidas
    retired: int = 0          # notas movidas a la papelera
    freed: int = 0            # bytes liberados al vaciar lo caducado
    shrunk: int = 0           # bytes fuera del vault vivo
    target: str = ""
    by_engine: bool = False
    confirm: str = ""         # la politica pide un si antes de retirar

    def to_json(self) -> dict[str, Any]:
        return {"ok": self.ok, "rango": self.rango, "notes": self.notes,
                "kept": self.kept, "dropped": self.dropped,
                "retired": self.retired, "freed": self.freed,
                "shrunk": self.shrunk, "target": self.target,
                "by_engine": self.by_engine, "reason": self.reason}


class Consolidator:
    """Resume las diarias viejas en un solo archivo y retira los originales."""

    def __init__(self, vault: Vault, keep_days: int = 14, min_notes: int = 3,
                 target: str = "raw/Memoria consolidada.md",
                 trash_days: int = 30, max_apuntes: int = 400):
        self.vault = vault
        self.keep_days = max(1, int(keep_days))
        self.min_notes = max(1, int(min_notes))
        self.target = target
        self.trash_days = max(1, int(trash_days))
        self.max_apuntes = max(20, int(max_apuntes))

    @classmethod
    def from_config(cls, cfg: Any, vault: Vault) -> "Consolidator":
        o = cfg.get("vault.consolidate", {}) or {}
        return cls(vault,
                   keep_days=int(o.get("keep_days", 14)),
                   min_notes=int(o.get("min_notes", 3)),
                   target=str(o.get("target", "raw/Memoria consolidada.md")),
                   trash_days=int(o.get("trash_days", 30)),
                   max_apuntes=int(o.get("max_apuntes", 400)))

    # ══════════════════════════════ consulta: que tocaria (lento, sin efecto)
    def plan(self, now: datetime | None = None) -> Plan:
        corte = ((now or datetime.now()) -
                 timedelta(days=self.keep_days)).strftime("%Y-%m-%d")

        viejas = [(f, n) for f, n in
                  ((self._fecha(n), n) for n in self.vault.all_notes())
                  if f and f < corte]
        if len(viejas) < self.min_notes:
            return Plan()

        viejas.sort(key=lambda x: x[0])
        p = Plan(desde=viejas[0][0], hasta=viejas[-1][0])
        for fecha, note in viejas:
            p.sources.append(note.path)
            p.bytes += note.size
            for kind, text in self._apuntes(note.body):
                if self._es_rutina(kind, text):
                    p.rutina += 1
                else:
                    p.esencia.append(Apunte(fecha, kind, text))

        # El tope corta por lo mas viejo: lo reciente es lo que sigue importando.
        if len(p.esencia) > self.max_apuntes:
            p.rutina += len(p.esencia) - self.max_apuntes
            p.esencia = p.esencia[-self.max_apuntes:]
        return p

    # ══════════════════════════════ consulta: el resumen (lento, sin efecto)
    async def summarize(self, engine: Any, p: Plan) -> Resumen:
        """Funde los apuntes esenciales. Sin motor, pasan tal cual.

        No toca disco ni candados: es la fase que puede tardar segundos y la
        que por eso corre fuera del turno.
        """
        crudo = [str(a) for a in p.esencia]
        if engine is None or not crudo:
            return Resumen(crudo)

        try:
            data = await ask_json(engine, self._prompt(p, crudo), schema=_ESQUEMA)
        except Exception:
            data = None
        if not isinstance(data, dict):
            return Resumen(crudo)

        lineas = [str(x).strip() for x in (data.get("esencial") or [])
                  if str(x).strip()]
        if not lineas:
            return Resumen(crudo)
        # Un resumen mas largo que el original no es un resumen: los modelos
        # pequeños repiten la entrada y le añaden glosa.
        return Resumen(lineas[:len(crudo)], str(data.get("titulo", "")).strip(), True)

    # ══════════════════════════════ comando: escribir y retirar (rapido)
    def commit(self, p: Plan, res: Resumen, policy: Any = None) -> Report:
        nota = self.vault.write(
            self.target, self._render(p, res),
            meta={"type": "consolidado", "tags": ["memoria", "consolidado"]},
            mode="append")

        rep = Report(rango=p.rango, notes=len(p.sources), kept=len(res.lineas),
                     dropped=p.rutina + max(0, len(p.esencia) - len(res.lineas)),
                     target=nota.rel, by_engine=res.by_engine)

        # Releer del disco antes de retirar: entre devolver el texto y tenerlo
        # escrito hay un disco que puede fallar, y del otro lado esta el unico
        # ejemplar.
        if p.rango not in self.vault.read(self.target).body:
            rep.ok = False
            rep.reason = "el consolidado no llego al disco; no retiro nada"
            return rep

        # Sin guardia no se retira: si nadie puede autorizar, la respuesta no
        # es «adelante», es «solo resumo» (regla 6).
        if policy is None or not hasattr(policy, "can_prune"):
            rep.reason = "sin politica: resumo pero no retiro"
            return rep

        decision = policy.can_prune(p.sources)
        if not decision.allowed:
            rep.confirm = decision.reason if decision.needs_confirm else ""
            rep.reason = decision.reason
            return rep

        rep.retired, rep.shrunk = self.retirar(p.sources)
        _, rep.freed = self.vault.purge_trash(self.trash_days)
        return rep

    async def run(self, engine: Any = None, policy: Any = None,
                  now: datetime | None = None) -> Report:
        """Las tres fases seguidas. Comodo para una orden hablada; el ciclo
        autonomo las separa para no bloquear el turno mientras el motor piensa."""
        p = self.plan(now)
        if not p:
            _, freed = self.vault.purge_trash(self.trash_days)
            return Report(reason="no hay diarias que consolidar", freed=freed)
        return self.commit(p, await self.summarize(engine, p), policy)

    def retirar(self, sources: list[Path]) -> tuple[int, int]:
        """Manda los originales a la papelera. Devuelve (notas, bytes)."""
        retired = shrunk = 0
        for src in sources:
            try:
                size = src.stat().st_size
                self.vault.trash(src)
                retired += 1
                shrunk += size
            except OSError:
                continue
        return retired, shrunk

    # ══════════════════════════════ texto
    @staticmethod
    def _prompt(p: Plan, crudo: list[str]) -> str:
        # La peticion va al final, pegada a la respuesta: arriba del material,
        # los modelos pequeños se quedan con las primeras entradas de la lista.
        return (
            "Estas comprimiendo el diario de una asistente de escritorio para "
            "que ocupe menos y siga sirviendo.\n\n"
            f"APUNTES DEL {p.rango} (las ordenes rutinarias ya se quitaron "
            "antes de llegar aqui):\n" + "\n".join(f"- {c}" for c in crudo) +
            "\n\nQuedate con lo que seguiria importando dentro de seis meses: "
            "decisiones, hechos sobre personas, proyectos o sistemas, y "
            "compromisos con fecha. Funde en una sola linea los apuntes que "
            "digan lo mismo y descarta lo que solo describa un momento ya "
            "pasado. Conserva los [[enlaces]] que aparezcan.\n\n"
            "Devuelve un objeto JSON con este formato:\n"
            '{"titulo": "La quincena del cambio de proveedor",\n'
            ' "esencial": ["El staging se cae los martes por el cron de '
            'respaldos",\n'
            '              "Ana lleva el despliegue de la API desde el 8 de '
            'julio"]}')

    @staticmethod
    def _render(p: Plan, res: Resumen) -> str:
        cabecera = f"## {p.rango}" + (f" — {res.titulo}" if res.titulo else "")
        cuerpo = "\n".join(f"- {l}" for l in res.lineas) or "- (nada que retener)"
        return (f"{cabecera}\n\n{cuerpo}\n\n"
                f"> {len(p.sources)} notas diarias · {len(res.lineas)} apuntes "
                f"retenidos · {p.rutina} rutinas omitidas · "
                f"{p.bytes // 1024} KB de origen\n")

    # ══════════════════════════════ clasificacion
    def _fecha(self, note: Note) -> str:
        """La fecha de una diaria de `raw/`, o vacio si no lo es.

        Se exige tipo **y** zona: solo el tipo dejaria entrar una nota marcada
        a mano como `daily` en `wiki/`, y eso es reescribirle sus notas.
        """
        if note.zone != self.vault.raw.name or note.meta.get("type") != "daily":
            return ""
        fecha = str(note.meta.get("date", "")).strip()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", fecha):
            return fecha
        try:
            return datetime.strptime(
                note.path.stem, self.vault.daily_format).strftime("%Y-%m-%d")
        except ValueError:
            return ""

    @staticmethod
    def _apuntes(body: str) -> list[tuple[str, str]]:
        return [(m.group(2).lower(), m.group(3).strip())
                for m in (_APUNTE.match(l) for l in body.splitlines()) if m]

    @staticmethod
    def _es_rutina(kind: str, text: str) -> bool:
        """El tipo manda sobre el texto: «recuerda que hay que abrir el puerto
        8080» lleva un verbo de rutina y es justo lo contrario."""
        if kind in _KIND_ESENCIAL:
            return False
        if kind in _KIND_RUTINA:
            return True
        if len(text) < 12:          # «si», «gracias», ruido del STT
            return True
        return bool(_RUTINA.search(text))
