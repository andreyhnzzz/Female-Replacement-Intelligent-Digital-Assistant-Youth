"""SKILL — noticias: titulares reales, resumidos y archivados.

Trae los feeds declarados en `[news]`, los deduplica, se los pasa al motor
para que los ordene por lo que importa, dice dos frases y deja el briefing
completo en `outputs/`. La voz no lee doce titulares: eso es ruido.

Si el motor esta caido, la skill **no falla**: cae a la lista cruda. Un
asistente de noticias que no dice nada porque el resumidor no arranco es
peor que uno que lee los titulares tal cual.
"""
from __future__ import annotations

import re
from datetime import datetime

from .base import Skill, SkillContext, SkillResult

# «las noticias de tecnologia» -> tecnologia
TOPIC = re.compile(
    r"\b(?:de|sobre|acerca de|en)\s+"
    r"(tecnolog[ií]a|ciencia|mundo|internacional|nacional|local|deportes?|"
    r"econom[ií]a|negocios|pol[ií]tica|cultura|videojuegos|general)\b", re.I)

_STRIP = re.compile(r"\b(las|los|unas|unos|de hoy|de la mañana|por favor)\b", re.I)


class NoticiasSkill(Skill):
    name = "noticias"
    description = "Lee los titulares del dia de fuentes RSS y los resume."
    triggers = [
        # Los disparadores largos existen para ganarle a `inbox`, que tambien
        # reconoce «ponme al dia». El puntaje pesa cuanto texto literal
        # reconoci, asi que la frase completa gana al fragmento.
        r"\bponme al d[ií]a (con|de|en) las noticias\b",
        r"\b(dame|l[eé]e(me)?|cu[eé]ntame|res[uú]meme) (las |los )?(noticias|titulares)\b",
        r"\bqu[eé] (est[aá] )?pasando en el mundo\b",
        r"\bqu[eé] hay de nuevo en el mundo\b",
        r"\bnoticias\b", r"\btitulares\b", r"\bactualidad\b",
        r"\bnoticiero\b", r"\bprensa\b",
    ]
    needs = ("news",)

    async def run(self, ctx: SkillContext) -> SkillResult:
        gap = self.unavailable(ctx)
        if gap:
            return SkillResult(ok=False, error=gap,
                               speak=f"No puedo traer noticias: {gap}.",
                               display=f"# Sin noticias\n\n{gap}")

        news = ctx.system.news
        limit = int(self.opts.get("max_items", 12))
        topic = self._topic(ctx.text)

        items = await news.headlines(topic, limit=limit)
        errors = list(getattr(news, "last_errors", []))

        if not items:
            detail = "\n".join(f"- {e}" for e in errors) or "- los feeds no devolvieron nada"
            return SkillResult(
                ok=False, error="sin titulares",
                speak="No pude traer titulares. Los feeds no contestaron.",
                display=f"# Sin titulares\n\n### Que fallo\n{detail}\n\n"
                        "Revisa `[news] sources` y `[policy] allow_web_fetch`.")

        raw = "\n".join(
            f"- [{i.source}] {i.title}" + (f" — {i.summary[:180]}" if i.summary else "")
            for i in items)

        body = await self._digest(ctx, raw, topic, len(items))
        note = self._archive(ctx, body, items, topic)

        head = items[0].title
        speak = (f"{len(items)} titulares" + (f" de {topic}" if topic else "") +
                 f". El que abre: {head[:110]}.")

        return SkillResult(
            speak=speak,
            display=f"# Noticias{f' · {topic}' if topic else ''}\n\n{body}\n\n"
                    + self._sources_block(items, errors),
            data={"count": len(items), "topic": topic,
                  "sources": sorted({i.source for i in items if i.source}),
                  "errors": errors, "briefing": note.rel if note else ""},
            writes=[note.rel] if note else [])

    # ── tema ──────────────────────────────────────────────────────
    def _topic(self, text: str) -> str:
        m = TOPIC.search(text or "")
        if not m:
            return ""
        return _STRIP.sub("", m.group(1)).strip().lower()

    # ── resumen ───────────────────────────────────────────────────
    async def _digest(self, ctx: SkillContext, raw: str, topic: str, n: int) -> str:
        prompt = (
            f"Estos son {n} titulares reales de hoy"
            + (f", del area de {topic}" if topic else "") + ":\n\n" + raw +
            "\n\nAgrupalos y devuelve SOLO markdown con este formato:\n"
            "## Lo que abre el dia\n"
            "- **titular en tus palabras** — una linea de por que importa (fuente)\n"
            "(maximo 3)\n\n"
            "## Tambien\n"
            "- titular (fuente)\n"
            "(maximo 5)\n\n"
            "Reglas: no inventes ni un dato que no este arriba. No añadas "
            "analisis que no se deduzca del titular. Sin preambulo ni despedida."
        )
        try:
            out = (await ctx.engine.complete(prompt, system=ctx.cfg.persona())).strip()
            if out:
                return out
        except Exception as exc:
            return (f"> El resumidor no respondio ({str(exc)[:80]}). "
                    "Titulares en crudo:\n\n" + raw)
        return raw

    # ── archivo ───────────────────────────────────────────────────
    def _archive(self, ctx: SkillContext, body: str, items, topic: str):
        if not bool(self.opts.get("archive", True)):
            return None
        today = datetime.now().strftime("%Y-%m-%d")
        label = f"Noticias {today}" + (f" · {topic}" if topic else "")
        full = (f"# {label}\n\n{body}\n\n## Titulares completos\n\n" +
                "\n".join(
                    f"- [{i.title}]({i.url})" if i.url else f"- {i.title}"
                    for i in items) + "\n")
        try:
            note = ctx.vault.write(
                f"{self.opts.get('write_to', 'outputs')}/{label}.md", full,
                meta={"type": "noticias", "date": today,
                      "tags": ["noticias"] + ([topic] if topic else [])},
                mode="create")
            ctx.vault.log(f"Noticias archivadas → [[{note.title}]]", kind="noticias")
            return note
        except Exception:
            return None          # que no se archive no invalida la respuesta

    @staticmethod
    def _sources_block(items, errors: list[str]) -> str:
        names = sorted({i.source for i in items if i.source})
        out = "---\n\n**Fuentes:** " + (", ".join(names) or "—")
        if errors:
            out += "\n\n**No contestaron:** " + "; ".join(errors[:4])
        return out
