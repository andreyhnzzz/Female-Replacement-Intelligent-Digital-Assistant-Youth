"""SKILL 2 — inbox: el resumen matutino.

Junta todo lo que cayo en el vault desde ayer (raw/, notas tocadas, pendientes
sueltos), se lo pasa al motor y escribe un briefing en outputs/.
"""
from __future__ import annotations

import re
from datetime import datetime

from .base import Skill, SkillContext, SkillResult

TODO = re.compile(r"^\s*[-*]\s*\[( |x|X)\]\s+(.{2,200})$", re.M)


class InboxSkill(Skill):
    name = "inbox"
    description = "Resumen matutino: que cayo, que quedo abierto, que urge."
    triggers = [
        r"\binbox\b", r"\bresumen\b", r"\bbriefing\b", r"\bbuenos d[ií]as\b",
        r"\bque hay\b", r"\bqu[eé] tengo\b", r"\bponme al d[ií]a\b",
        r"\bnovedades\b", r"\bmatutin[oa]\b", r"\bdame el d[ií]a\b",
    ]

    async def run(self, ctx: SkillContext) -> SkillResult:
        hours = int(self.opts.get("lookback_h", 24))
        max_items = int(self.opts.get("max_items", 12))

        recent = ctx.vault.recent(hours=hours, limit=max_items * 2)
        open_todos: list[tuple[str, str]] = []
        done_today: list[str] = []
        for note in ctx.vault.all_notes():
            for state, text in TODO.findall(note.body):
                if state == " ":
                    open_todos.append((note.title, text.strip()))
                elif note.mtime >= datetime.now().timestamp() - hours * 3600:
                    done_today.append(text.strip())

        # --- material crudo para el motor ---
        digest = []
        for n in recent[:max_items]:
            digest.append(f"- [[{n.title}]] ({n.zone}, {n.excerpt(160)})")
        todo_txt = "\n".join(f"- [ ] {t}  <- [[{src}]]" for src, t in open_todos[:20]) or "(ninguno)"

        prompt = (
            f"Genera el briefing matutino de {ctx.cfg.get('identity.user_title', 'Boss')}.\n\n"
            f"NOTAS TOCADAS EN LAS ULTIMAS {hours}H:\n" + ("\n".join(digest) or "(nada)") +
            f"\n\nPENDIENTES ABIERTOS:\n{todo_txt}\n"
            f"\nCERRADOS HOY: {len(done_today)}\n\n"
            "Devuelve markdown con exactamente estas secciones:\n"
            "## Lo que importa hoy  (max 3 vinetas, cada una con su [[enlace]])\n"
            "## Se movio  (max 4 vinetas)\n"
            "## Se esta enfriando  (pendientes viejos, max 3)\n"
            "Sin preambulo. Sin despedida. Usa [[wikilinks]] con los titulos reales de arriba."
        )

        try:
            body = (await ctx.engine.complete(prompt, system=ctx.cfg.persona())).strip()
        except Exception as exc:
            body = ("## Lo que importa hoy\n" +
                    "\n".join(f"- [ ] {t} — [[{s}]]" for s, t in open_todos[:3]) +
                    f"\n\n## Se movio\n" + ("\n".join(digest[:4]) or "- (nada)") +
                    f"\n\n> motor no disponible: {exc}")

        today = datetime.now().strftime("%Y-%m-%d")
        path = f"{self.opts.get('write_to', 'outputs')}/Briefing {today}.md"
        note = ctx.vault.write(
            path,
            f"# Briefing — {datetime.now().strftime('%A %d de %B')}\n\n{body}\n",
            meta={"type": "briefing", "date": today, "tags": ["briefing", "inbox"]},
            mode="create",
        )
        ctx.vault.log(f"Briefing generado → [[{note.title}]]", kind="inbox")

        speak = (f"Briefing listo. {len(open_todos)} pendientes abiertos, "
                 f"{len(recent)} notas se movieron en {hours} horas.")
        return SkillResult(
            speak=speak,
            display=f"# Inbox\n\n{body}",
            data={"open_todos": len(open_todos), "closed_today": len(done_today),
                  "touched": len(recent), "briefing": note.rel},
            writes=[note.rel],
        )
