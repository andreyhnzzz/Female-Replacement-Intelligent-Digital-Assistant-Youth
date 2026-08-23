"""El reloj: lo que FRIDAY hace sin que se lo pidas.

Hasta ahora FRIDAY solo hablaba cuando le hablabas. Sabia que tienes un quiz
el martes y se lo callaba hasta que preguntaras. Un asistente que solo
contesta es una consola con voz; lo que lo convierte en acompañante es que
levante la vista a las nueve menos cuarto.

    -- Puro a proposito --

Aqui no hay asyncio, ni bus, ni vault, ni motor. `due()` recibe un instante y
devuelve que toca; no ejecuta nada. Es la misma division que en
`memory/consolidate.py` (`plan` / `commit`) y por la misma razon: lo que se
puede probar sin reloj, sin red y sin efectos se prueba de verdad. El bucle
que si tiene efectos vive en `friday.py::_programador`, donde estan el
candado y la boca.

    -- Dos clases de disparo --

- **Trabajos** (`[[schedule.jobs]]`): una hora del dia o un intervalo. El
  briefing de las ocho y media, el repaso de la agenda cada seis horas.
- **Recordatorios**: no se declaran, salen de la agenda del vault. Cada
  evento con hora dispara una vez, `lead_min` antes.

    -- Por que un trabajo dice una FRASE y no llama a una skill --

`do = "dame el briefing de la mañana"` se enruta como si lo hubieras dicho tu.
Cuesta un turno de motor, que es irrelevante en algo que corre dos veces al
dia, y a cambio cualquier capacidad que exista es programable el dia que
existe, sin tocar este archivo ni el toml de nadie. La alternativa —una tabla
de nombres de skill— habria que ampliarla en cada skill nueva.

Lo que **no** hace es confirmar sola: si la frase programada acaba en una
accion que espera un «si», se queda esperandolo. El reloj no es una excusa
para saltarse el guardia (regla 6).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Iterable

# ── dias de la semana, como los escribe la gente ──────────────────
_DIAS: dict[str, int] = {}
for _i, _nombres in enumerate((
    ("lun", "lunes", "mon", "monday"),
    ("mar", "martes", "tue", "tuesday"),
    ("mie", "mié", "miercoles", "miércoles", "wed", "wednesday"),
    ("jue", "jueves", "thu", "thursday"),
    ("vie", "viernes", "fri", "friday"),
    ("sab", "sáb", "sabado", "sábado", "sat", "saturday"),
    ("dom", "domingo", "sun", "sunday"),
)):
    for _n in _nombres:
        _DIAS[_n] = _i

_GRUPOS = {
    "laborables": (0, 1, 2, 3, 4), "entresemana": (0, 1, 2, 3, 4),
    "semana": (0, 1, 2, 3, 4), "weekdays": (0, 1, 2, 3, 4),
    "finde": (5, 6), "fin de semana": (5, 6), "weekend": (5, 6),
    "diario": (0, 1, 2, 3, 4, 5, 6), "todos": (0, 1, 2, 3, 4, 5, 6),
}

_INTERVALO = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*(s|seg|m|min|h|hora?s?|d|dias?)\s*$", re.I)

# Cada cuanto mira el reloj, como minimo. Mirar cuesta recorrer y parsear el
# vault entero —no hay indice, regla 1— y aunque va en un hilo, hacerlo cada
# segundo es gastar un nucleo en preguntar si ya son las nueve. Es constante
# de modulo y no un numero suelto dentro del bucle para que las pruebas
# puedan bajarlo sin esperar un minuto real por comprobacion.
TICK_MINIMO_S = 15.0


def parse_dias(items: Iterable[str] | str | None) -> tuple[int, ...]:
    """`["lun","vie"]`, `"laborables"` o vacio (= todos) a indices 0-6."""
    if items is None:
        return (0, 1, 2, 3, 4, 5, 6)
    if isinstance(items, str):
        items = [items]
    out: set[int] = set()
    for raw in items:
        clave = str(raw).strip().lower()
        if clave in _GRUPOS:
            out.update(_GRUPOS[clave])
        elif clave in _DIAS:
            out.add(_DIAS[clave])
    return tuple(sorted(out)) or (0, 1, 2, 3, 4, 5, 6)


def parse_intervalo(texto: str) -> float:
    """«30m», «2h», «45 min» a segundos. 0 si no se entiende."""
    m = _INTERVALO.match(str(texto or ""))
    if not m:
        return 0.0
    cantidad = float(m.group(1).replace(",", "."))
    unidad = m.group(2).lower()
    # El orden importa: «seg» y «s» empiezan igual, y «m» y «min» tambien.
    # Se mira la inicial una sola vez, de la unidad mas grande a la mas
    # pequeña, en vez de encadenar `if` que se pisan entre si.
    for inicial, factor in (("d", 86400.0), ("h", 3600.0),
                            ("m", 60.0), ("s", 1.0)):
        if unidad.startswith(inicial):
            return cantidad * factor
    return 0.0


def parse_hora(texto: str) -> tuple[int, int] | None:
    """«08:30», «8:30», «8» a (hora, minuto). None si no es una hora."""
    m = re.match(r"^\s*(\d{1,2})(?::(\d{2}))?\s*$", str(texto or ""))
    if not m:
        return None
    hora, minuto = int(m.group(1)), int(m.group(2) or 0)
    if not (0 <= hora <= 23 and 0 <= minuto <= 59):
        return None
    return hora, minuto


# ══════════════════════════════════════════════ lo que se dispara
@dataclass(frozen=True, slots=True)
class Job:
    """Un trabajo programado, declarado como dato en el toml."""
    name: str
    do: str                              # la frase que se enruta
    at: tuple[int, int] | None = None    # (hora, minuto) del dia
    every_s: float = 0.0                 # o cada tantos segundos
    days: tuple[int, ...] = (0, 1, 2, 3, 4, 5, 6)
    speak: bool = True                   # en voz alta, o solo al panel
    notify: bool = False                 # ademas, fuera del equipo
    enabled: bool = True

    @property
    def valido(self) -> bool:
        return bool(self.name and self.do and (self.at or self.every_s > 0))

    def describe(self) -> str:
        cuando = (f"{self.at[0]:02d}:{self.at[1]:02d}" if self.at
                  else f"cada {int(self.every_s // 60)} min")
        return f"{self.name} — {cuando}"


@dataclass(frozen=True, slots=True)
class Disparo:
    """Algo que toca hacer AHORA. Lo devuelve `due()`; no lo ejecuta."""
    clave: str                           # identidad estable, para no repetir
    kind: str                            # job | recordatorio
    texto: str                           # frase a enrutar, o aviso a decir
    titulo: str = ""
    speak: bool = True
    notify: bool = False
    urgencia: str = "normal"


# ══════════════════════════════════════════════ el reloj
class Scheduler:
    """Decide que toca. No hace nada.

    `ya_disparado` es la unica memoria y se la inyecta quien lo usa: en
    `friday.py` sale de leer la nota diaria, asi que reiniciar a media
    mañana **no** repite el recordatorio de las nueve. Guardar esa marca en
    markdown y no en un archivo de estado es deliberado (regla 1): ademas de
    servir de tope, deja en el diario que FRIDAY te aviso, que es
    exactamente lo que querrias leer al repasar el dia.
    """

    def __init__(self, jobs: list[Job], *, lead_min: int = 15,
                 gracia_min: int = 10):
        self.jobs = [j for j in jobs if j.valido and j.enabled]
        # Cuanto antes se avisa de un evento con hora.
        self.lead_min = max(0, int(lead_min))
        # Y cuanto despues sigue teniendo sentido avisar. Sin gracia, un
        # equipo dormido durante el minuto exacto se come el aviso; con una
        # gracia larga, te enteras de la reunion cuando ya termino.
        self.gracia_min = max(1, int(gracia_min))
        self._ultimo: dict[str, float] = {}

    # ── trabajos ──────────────────────────────────────────────────
    def _toca_job(self, job: Job, ahora: datetime) -> str:
        """La clave del disparo si toca, o cadena vacia.

        La clave lleva el dia y la hora prevista, no el instante real: dos
        ticks dentro de la misma ventana producen la misma clave y el
        segundo se descarta solo.
        """
        if job.every_s > 0:
            anterior = self._ultimo.get(job.name)
            if anterior is not None and (ahora.timestamp() - anterior) < job.every_s:
                return ""
            # El primer tick tras arrancar no dispara los intervalos: si
            # no, encender FRIDAY lanzaria de golpe todo lo que estuviera
            # declarado «cada seis horas».
            if anterior is None:
                self._ultimo[job.name] = ahora.timestamp()
                return ""
            return f"job:{job.name}:{int(ahora.timestamp() // max(1, job.every_s))}"

        if ahora.weekday() not in job.days:
            return ""
        hora, minuto = job.at                       # type: ignore[misc]
        previsto = ahora.replace(hour=hora, minute=minuto, second=0, microsecond=0)
        retraso = (ahora - previsto).total_seconds()
        if 0 <= retraso <= self.gracia_min * 60:
            return f"job:{job.name}:{previsto:%Y-%m-%d %H:%M}"
        return ""

    # ── recordatorios de la agenda ────────────────────────────────
    def _toca_evento(self, evento: dict, ahora: datetime) -> str:
        """Un evento con hora avisa una vez, `lead_min` antes.

        Los de todo el dia (`time` vacio) no disparan aqui: avisar a las
        00:00 de algo que es «el jueves» es ruido. De esos habla el briefing
        del dia, que es donde tienen sentido.
        """
        if evento.get("done") or not evento.get("time"):
            return ""
        try:
            falta = float(evento["ts"]) - ahora.timestamp()
        except (KeyError, TypeError, ValueError):
            return ""
        if not (-self.gracia_min * 60 <= falta <= self.lead_min * 60):
            return ""
        return f"evt:{evento.get('when', '')}:{str(evento.get('title', ''))[:40]}"

    @staticmethod
    def _frase_evento(evento: dict, ahora: datetime) -> str:
        faltan = int((float(evento["ts"]) - ahora.timestamp()) // 60)
        titulo = str(evento.get("title", "")).strip()
        if faltan <= 0:
            return f"Es la hora: {titulo}."
        if faltan == 1:
            return f"En un minuto: {titulo}."
        return f"En {faltan} minutos: {titulo}."

    # ── la decision ───────────────────────────────────────────────
    def due(self, ahora: datetime | None = None, *,
            eventos: list[dict] | None = None,
            ya_disparado: set[str] | frozenset[str] = frozenset()) -> list[Disparo]:
        """Que toca en este instante. Puro: mismas entradas, misma salida.

        Los recordatorios van **antes** que los trabajos: si a las 08:30
        coinciden el briefing y una reunion, la reunion es la que no puede
        esperar al siguiente tick.
        """
        ahora = ahora or datetime.now()
        salida: list[Disparo] = []

        for evento in eventos or []:
            clave = self._toca_evento(evento, ahora)
            if not clave or clave in ya_disparado:
                continue
            salida.append(Disparo(
                clave=clave, kind="recordatorio",
                texto=self._frase_evento(evento, ahora),
                titulo=str(evento.get("title", "")),
                speak=True, notify=True, urgencia="alta"))

        for job in self.jobs:
            clave = self._toca_job(job, ahora)
            if not clave or clave in ya_disparado:
                continue
            self._ultimo[job.name] = ahora.timestamp()
            salida.append(Disparo(clave=clave, kind="job", texto=job.do,
                                  titulo=job.name, speak=job.speak,
                                  notify=job.notify))
        return salida

    def marca(self, job_name: str, cuando: datetime | None = None) -> None:
        """Anota que un trabajo por intervalo acaba de correr."""
        self._ultimo[job_name] = (cuando or datetime.now()).timestamp()

    def proximo(self, ahora: datetime | None = None) -> str:
        """El siguiente trabajo que va a correr. Informativo, para el panel.

        Mira una semana por delante y no solo hasta mañana: un briefing de
        laborables consultado un sabado no tiene su proxima cita mañana, la
        tiene el lunes, y contestar «ninguno» a eso es contestar mal.
        """
        ahora = ahora or datetime.now()
        candidatos: list[tuple[datetime, Job]] = []
        for job in self.jobs:
            if not job.at:
                continue
            for adelanto in range(8):          # hoy + una semana
                previsto = (ahora + timedelta(days=adelanto)).replace(
                    hour=job.at[0], minute=job.at[1], second=0, microsecond=0)
                if previsto > ahora and previsto.weekday() in job.days:
                    candidatos.append((previsto, job))
                    break
        if not candidatos:
            return ""
        cuando, job = min(candidatos, key=lambda c: c[0])
        dia = "" if cuando.date() == ahora.date() else f" del {cuando:%d/%m}"
        return f"{job.name} a las {cuando:%H:%M}{dia}"

    def snapshot(self) -> dict[str, Any]:
        return {"jobs": [j.describe() for j in self.jobs],
                "lead_min": self.lead_min, "gracia_min": self.gracia_min}


# ══════════════════════════════════════════════ desde el toml
def load_jobs(cfg: Any) -> list[Job]:
    """Los trabajos de `[[schedule.jobs]]`. Lo mal escrito se ignora, no
    revienta: un typo en el toml no puede impedir que FRIDAY arranque."""
    out: list[Job] = []
    for item in cfg.get("schedule.jobs", []) or []:
        if not isinstance(item, dict):
            continue
        out.append(Job(
            name=str(item.get("name", "")).strip(),
            do=str(item.get("do", "")).strip(),
            at=parse_hora(item.get("at", "")),
            every_s=parse_intervalo(item.get("every", "")),
            days=parse_dias(item.get("days")),
            speak=bool(item.get("speak", True)),
            notify=bool(item.get("notify", False)),
            enabled=bool(item.get("enabled", True)),
        ))
    return [j for j in out if j.valido]


def build_scheduler(cfg: Any) -> Scheduler:
    return Scheduler(
        load_jobs(cfg),
        lead_min=int(cfg.get("schedule.lead_min", 15)),
        gracia_min=int(cfg.get("schedule.gracia_min", 10)),
    )
