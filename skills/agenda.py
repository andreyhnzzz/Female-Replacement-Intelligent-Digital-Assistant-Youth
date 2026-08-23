"""SKILL 5 — agenda: el horizonte.

Lee eventos de markdown. Dos sintaxis, ambas legibles a ojo:
    - 2026-08-15 09:30 | Revision de sprint | #trabajo
    - [ ] 2026-08-16 Entrega del informe

Sin Google Calendar, sin API, sin nube. Un archivo.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from core.bus import BUS
from core.engine import ask_json

from .base import Skill, SkillContext, SkillResult

PIPE_EVENT = re.compile(
    r"^\s*[-*]?\s*(\d{4}-\d{2}-\d{2})(?:[ T](\d{1,2}:\d{2}))?\s*\|\s*([^|\n]{2,120})(?:\|\s*(.*))?$", re.M)
INLINE_EVENT = re.compile(
    r"^\s*[-*]\s*\[( |x|X)\]\s*(\d{4}-\d{2}-\d{2})(?:[ T](\d{1,2}:\d{2}))?\s+(.{2,120})$", re.M)

ADD_CUE = re.compile(r"\b(agenda|agenda[rm]e|apunta|programa|recu[eé]rdame|cita|reuni[oó]n)\b.*"
                     r"\b(el|para|ma[ñn]ana|hoy|lunes|martes|mi[eé]rcoles|jueves|viernes|"
                     r"s[aá]bado|domingo|\d{1,2})\b", re.I)


def _mk(date: str, time_: str, title: str, source: str, done: bool,
        tags: str) -> dict:
    stamp = f"{date} {time_ or '00:00'}"
    try:
        dt = datetime.strptime(stamp, "%Y-%m-%d %H:%M")
    except ValueError:
        dt = datetime.strptime(date, "%Y-%m-%d")
    return {"when": dt.isoformat(timespec="minutes"), "date": date,
            "time": time_ or "", "title": title.strip(), "source": source,
            "done": done, "tags": [t for t in re.findall(r"#([\w\-/]+)", tags or "")],
            "ts": dt.timestamp()}


def recolectar(vault) -> list[dict]:
    """Todos los eventos del vault, ordenados y sin duplicados.

    Funcion de modulo y no solo metodo de la skill porque tiene **dos**
    llamadores que no se parecen: la skill, dentro de un turno y con su
    `SkillContext`, y el reloj de `friday.py`, cada minuto y sin turno
    ninguno. Pedirle al reloj que fabrique un contexto entero —motor,
    politica, sistema— para leer unas lineas de markdown seria construir el
    mundo para mirar un archivo.
    """
    events: list[dict] = []
    for note in vault.all_notes():
        for date, time_, title, tags in PIPE_EVENT.findall(note.body):
            events.append(_mk(date, time_, title, note.title, False, tags))
        for state, date, time_, title in INLINE_EVENT.findall(note.body):
            events.append(_mk(date, time_, title, note.title,
                              state.lower() == "x", ""))
    seen, out = set(), []
    for e in sorted(events, key=lambda e: e["when"]):
        key = (e["when"], e["title"].lower())
        if key not in seen:
            seen.add(key)
            out.append(e)
    return out


class AgendaSkill(Skill):
    name = "agenda"
    description = "Que viene: eventos y vencimientos del vault en el horizonte."
    triggers = [
        r"\bagenda\b", r"\bcalendario\b", r"\bqu[eé] sigue\b", r"\bpr[oó]xim[oa]s?\b",
        r"\bhoy tengo\b", r"\breuni[oó]n\b", r"\bcita\b",
        # «mañana» tiene dos significados y solo uno es una fecha. Con
        # articulo delante es un momento del dia —«toda la mañana», «por la
        # mañana»— y esas frases no piden la agenda: «llevo toda la mañana
        # dandole vueltas» se enrutaba aqui y contestaba con el calendario.
        r"(?<!la )(?<!las )(?<!una )\bma[ñn]ana\b",
        r"\bvence\b", r"\bdeadline\b", r"\bqu[eé] viene\b", r"\besta semana\b",
    ]

    def collect(self, ctx: SkillContext) -> list[dict]:
        return recolectar(ctx.vault)

    async def run(self, ctx: SkillContext) -> SkillResult:
        horizon = int(self.opts.get("horizon_days", 7))
        agenda_file = self.opts.get("file", "wiki/Agenda.md")

        # dictado -> agendar
        if ADD_CUE.search(ctx.text) and len(ctx.text.split()) > 3:
            added = await self._add(ctx, agenda_file)
            if added:
                return added

        now = datetime.now()
        limit = now + timedelta(days=horizon)
        events = self.collect(ctx)

        overdue = [e for e in events if e["ts"] < now.timestamp() and not e["done"]]
        upcoming = [e for e in events
                    if now.timestamp() <= e["ts"] <= limit.timestamp() and not e["done"]]
        today = [e for e in upcoming if e["date"] == now.strftime("%Y-%m-%d")]

        def fmt(e: dict) -> str:
            when = datetime.fromtimestamp(e["ts"])
            label = when.strftime("%H:%M") if e["time"] else "todo el dia"
            return f"- `{when.strftime('%d/%m')} {label}` **{e['title']}** — [[{e['source']}]]"

        lines = [f"# Agenda · proximos {horizon} dias", ""]
        if overdue:
            lines += [f"### Vencido ({len(overdue)})"] + [fmt(e) for e in overdue[-5:]] + [""]
        lines += [f"### Hoy ({len(today)})"] + ([fmt(e) for e in today] or ["- despejado"]) + [""]
        rest = [e for e in upcoming if e not in today]
        lines += [f"### Por venir ({len(rest)})"] + ([fmt(e) for e in rest[:10]] or ["- nada en el horizonte"])

        if today:
            nxt = today[0]
            speak = (f"{len(today)} en el dia. Lo siguiente: {nxt['title']}"
                     f"{' a las ' + nxt['time'] if nxt['time'] else ''}.")
        elif upcoming:
            n = upcoming[0]
            speak = f"Hoy despejado. Lo proximo: {n['title']}, {n['date'][8:10]} del {n['date'][5:7]}."
        else:
            speak = "No hay nada agendado en el horizonte."
        if overdue:
            speak += f" Ojo: {len(overdue)} vencidos."

        return SkillResult(
            speak=speak,
            display="\n".join(lines),
            data={"today": today, "upcoming": upcoming[:12], "overdue": len(overdue),
                  "total": len(events)},
        )

    async def _add(self, ctx: SkillContext, agenda_file: str) -> SkillResult | None:
        prompt = (
            f"Hoy es {datetime.now().strftime('%Y-%m-%d (%A)')}. "
            f"El usuario dijo: \"{ctx.text}\"\n\n"
            "Si esto agenda un evento, responde SOLO:\n"
            '{"add": true, "date": "YYYY-MM-DD", "time": "HH:MM o vacio", '
            '"title": "titulo corto", "tags": ["#tag"]}\n'
            'Si NO agenda nada, responde exactamente: {"add": false}'
        )
        try:
            data = await ask_json(ctx.engine, prompt) or {}
        except Exception as exc:
            # `None` aqui se lee como «esto no agenda nada», que es
            # exactamente lo que NO paso: el motor fallo. Sin avisar, un
            # timeout se confundia con «no detecte una fecha».
            BUS.report(f"agenda no pudo consultar al motor: {exc}",
                      origen="agenda")
            return None
        if not data.get("add") or not data.get("date"):
            return None

        line = (f"- {data['date']}"
                f"{' ' + data['time'] if data.get('time') else ''} | "
                f"{data.get('title', 'evento')} | {' '.join(data.get('tags', []))}".rstrip(" |"))
        note = ctx.vault.append_section(agenda_file, "Eventos", [line])
        ctx.vault.log(f"Agendado: {data.get('title')} el {data['date']}", kind="agenda")

        when = data["date"] + (f" {data['time']}" if data.get("time") else "")
        return SkillResult(
            speak=f"Agendado: {data.get('title')} el {when}.",
            display=f"# Agendado\n\n`{line}`\n\n→ [[{note.title}]]",
            data={"added": data}, writes=[note.rel],
        )
