"""SKILL 3 — plan: escribir el top 3 del dia.

Tres cosas. No cinco, no diez. El motor elige y justifica; FRIDAY lo escribe
en outputs/ y lo espeja en la nota diaria.
"""
from __future__ import annotations

import re
from datetime import datetime

from .base import Skill, SkillContext, SkillResult

TODO_OPEN = re.compile(r"^\s*[-*]\s*\[ \]\s+(.{2,200})$", re.M)
BULLET = re.compile(r"^\s*(?:\d+[.)]|[-*])\s+(.{3,200})$", re.M)


class PlanSkill(Skill):
    name = "plan"
    description = "Escribe el top 3 del dia y lo fija en el vault."
    triggers = [
        r"\bplan\b", r"\btop\s*3\b", r"\bprioridades?\b", r"\bqu[eé] hago\b",
        r"\bplanear\b", r"\bplanifica\b", r"\benf[oó]ca\b", r"\bagenda del d[ií]a\b",
        r"\borganiza\b", r"\bpor d[oó]nde empiezo\b",
    ]

    async def run(self, ctx: SkillContext) -> SkillResult:
        top_n = int(self.opts.get("top_n", 3))

        candidates: list[tuple[str, str, float]] = []
        for note in ctx.vault.all_notes():
            for text in TODO_OPEN.findall(note.body):
                candidates.append((text.strip(), note.title, note.mtime))
        candidates.sort(key=lambda c: -c[2])

        pool = "\n".join(f"- {t}   (de [[{src}]])" for t, src, _ in candidates[:30]) or "(sin pendientes)"
        hubs = ", ".join(f"[[{t}]]" for t, _ in ctx.graph.build().hubs(5))
        extra = ctx.text.strip()

        prompt = (
            f"Elige las {top_n} cosas que {ctx.cfg.get('identity.user_title', 'Boss')} "
            f"debe hacer HOY ({datetime.now().strftime('%A %d de %B')}).\n\n"
            f"PENDIENTES DISPONIBLES:\n{pool}\n\n"
            f"TEMAS CENTRALES DEL VAULT: {hubs or '(ninguno)'}\n"
            + (f"\nLO QUE ACABA DE DECIR EL USUARIO: \"{extra}\"\n" if extra else "")
            + f"\nDevuelve EXACTAMENTE {top_n} lineas numeradas, formato:\n"
            f"1. **Titulo corto** — por que hoy (una frase). [[Nota relacionada]]\n"
            f"Despues una linea final que empiece con 'Primer movimiento:' con la "
            f"accion concreta de 15 minutos para arrancar. Nada mas."
        )

        try:
            body = (await ctx.engine.complete(prompt, system=ctx.cfg.persona())).strip()
        except Exception as exc:
            picks = candidates[:top_n]
            body = "\n".join(f"{i}. **{t}** — pendiente reciente. [[{src}]]"
                             for i, (t, src, _) in enumerate(picks, 1))
            body += f"\n\nPrimer movimiento: abrir [[{picks[0][1]}]].\n> motor no disponible: {exc}" \
                if picks else f"\n> motor no disponible: {exc}"

        items = BULLET.findall(body)[:top_n]
        today = datetime.now().strftime("%Y-%m-%d")
        path = f"{self.opts.get('write_to', 'outputs')}/Plan {today}.md"
        checklist = "\n".join("- [ ] " + it.replace("**", "").strip() for it in items)

        note = ctx.vault.write(
            path,
            f"# Top {top_n} — {datetime.now().strftime('%A %d de %B')}\n\n{body}\n\n"
            f"## Checklist\n{checklist}\n",
            meta={"type": "plan", "date": today, "tags": ["plan", "top3"]},
            mode="create",
        )

        if self.opts.get("mirror_to_daily", True):
            ctx.vault.daily()
            ctx.vault.append_section(ctx.vault.daily_path(), f"Top {top_n}",
                                     [checklist, f"\n→ [[{note.title}]]"])
        ctx.vault.log(f"Top {top_n} fijado → [[{note.title}]]", kind="plan")

        first = items[0] if items else "sin objetivo"
        speak = f"Top {top_n} escrito. Empiezas por: {re.sub(r'[*_\[\]]', '', first)[:110]}"
        return SkillResult(
            speak=speak,
            display=f"# Plan del dia\n\n{body}",
            data={"top": items, "count": len(items), "plan": note.rel,
                  "candidates": len(candidates)},
            writes=[note.rel],
        )
