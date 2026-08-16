"""SKILL 4 — vault: leer y escribir memoria.

Es la unica skill que toca archivos por dictado directo:
  "recuerda que ..."          -> escribe nota atomica en wiki/ + enlaza
  "que sabes de X"            -> busca, arma contexto del grafo, responde
  "abre / lee la nota X"      -> lee y muestra
"""
from __future__ import annotations

import re
from datetime import datetime

from .base import Skill, SkillContext, SkillResult
from memory.vault import slugify

WRITE_CUES = re.compile(
    r"\b(recuerda|anota|apunta|guarda|registra|toma nota|escribe|agrega|a[ñn]ade)\b", re.I)
READ_CUES = re.compile(
    r"\b(qu[eé] sabes|qu[eé] ten[ií]a|b[uú]scame|busca|rec[uú]perame|recuerdas|"
    r"muestra|abre|lee|d[oó]nde dice|consulta)\b", re.I)


class VaultSkill(Skill):
    name = "vault"
    description = "Lee y escribe la memoria en markdown enlazado."
    triggers = [
        r"\brecuerda\b", r"\banota\b", r"\bapunta\b", r"\bguarda\b", r"\bregistra\b",
        r"\bqu[eé] sabes\b", r"\bbusca\b", r"\bb[uú]scame\b", r"\bnota\b",
        r"\bvault\b", r"\bmemoria\b", r"\benlaza\b", r"\brecuerdas\b",
    ]

    async def run(self, ctx: SkillContext) -> SkillResult:
        text = ctx.text.strip()
        if WRITE_CUES.search(text) and not READ_CUES.search(text):
            return await self._write(ctx, text)
        return await self._read(ctx, text)

    # ------------------------------------------------------------ write
    async def _write(self, ctx: SkillContext, text: str) -> SkillResult:
        if not self.opts.get("allow_write", True):
            return SkillResult(ok=False, error="escritura deshabilitada",
                               speak="Tengo la escritura bloqueada en la config.")

        payload = WRITE_CUES.sub("", text, count=1).strip(" ,.:;—-") or text
        existing = [n.title for n in ctx.vault.recent(hours=24 * 14, limit=40)][:25]

        prompt = (
            "Convierte esto en una nota atomica de Obsidian.\n\n"
            f"DICHO POR EL USUARIO: \"{payload}\"\n\n"
            f"NOTAS QUE YA EXISTEN (enlaza a las relevantes): {', '.join(existing) or '(vault vacio)'}\n\n"
            "Responde SOLO con este JSON:\n"
            '{"title": "Titulo corto y especifico", "tags": ["t1","t2"], '
            '"body": "markdown, 2-6 lineas, con [[enlaces]] a las notas relevantes de arriba", '
            '"links": ["Nota A"]}'
        )

        title, body, tags, links = None, None, [], []
        degraded = ""
        try:
            raw = await ctx.engine.complete(prompt, system=ctx.cfg.persona())
            data = ctx.engine.extract_json(raw) or {}
            title = (data.get("title") or "").strip() or None
            body = (data.get("body") or "").strip() or None
            tags = [str(t) for t in (data.get("tags") or [])][:6]
            links = [str(t) for t in (data.get("links") or [])][:8]
            if not title:
                degraded = "el motor no devolvio el JSON esperado"
        except Exception as exc:
            degraded = f"motor no disponible: {type(exc).__name__}"

        if not title:
            title = slugify(" ".join(payload.split()[:7]))
        if not body:
            body = payload

        rel = f"{ctx.vault.wiki.name}/{slugify(title)}.md"
        mode = "append" if ctx.vault.exists(rel) else "create"
        note = ctx.vault.write(
            rel,
            (body if mode == "create" else
             f"### {datetime.now().strftime('%Y-%m-%d %H:%M')}\n{body}"),
            meta={"type": "nota", "tags": tags or ["captura"],
                  "source": "voz", "title": title},
            mode=mode,
        )

        ctx.vault.log(f"«{payload[:80]}» → [[{note.title}]]", kind="vault")
        ctx.graph.build(force=True)
        back = ctx.graph.backlinks(note.title)

        verb = "Actualice" if mode == "append" else "Guarde"
        return SkillResult(
            speak=f"{verb} {note.title}. {len(note.links)} enlaces.",
            display=(f"# {note.title}\n\n`{note.rel}` · {mode}\n\n{note.body.strip()}\n\n"
                     f"---\n**Enlaces salientes:** {', '.join(note.links) or '—'}  \n"
                     f"**Backlinks:** {', '.join(back) or '—'}"
                     + (f"\n\n> Guardado en modo crudo: {degraded}." if degraded else "")),
            data={"note": note.rel, "title": note.title, "mode": mode,
                  "links": note.links, "backlinks": back, "tags": note.tags,
                  "degraded": degraded},
            writes=[note.rel],
        )

    # ------------------------------------------------------------- read
    async def _read(self, ctx: SkillContext, text: str) -> SkillResult:
        query = READ_CUES.sub("", text, count=1).strip(" ¿?,.:;—-")
        # "que sabes del HUD" -> "HUD", no "del HUD"
        query = re.sub(r"^(?:de[l]?|sobre|acerca de|la|el|los|las)\s+", "", query, flags=re.I)
        query = query.strip() or text
        hits = ctx.vault.search(query, limit=6)

        if not hits:
            return SkillResult(
                speak="No hay registro de eso en el vault.",
                display=f"# Sin resultados\n\nBusque **{query}** en {ctx.vault.stats()['notes']} notas. Nada.",
                data={"query": query, "hits": 0},
            )

        context = ctx.graph.context_for([h.title for h in hits[:3]], depth=1,
                                        max_chars=int(self.opts.get("max_read_kb", 256)) * 40)
        prompt = (
            f"El usuario pregunta: \"{query}\"\n\n"
            f"CONTENIDO DEL VAULT (unica fuente de verdad):\n{context}\n\n"
            "Responde en 2-4 lineas de markdown citando las notas con [[wikilinks]]. "
            "Si el vault no lo dice, responde exactamente: 'No hay registro de eso.' "
            "No inventes nada."
        )

        try:
            answer = (await ctx.engine.complete(prompt, system=ctx.cfg.persona())).strip()
        except Exception as exc:
            answer = "\n".join(f"- [[{h.title}]] — {h.excerpt(140)}" for h in hits) + \
                     f"\n\n> motor no disponible: {exc}"

        listing = "\n".join(
            f"- [[{h.title}]] `{h.rel}` · {len(h.links)} enlaces · "
            f"{datetime.fromtimestamp(h.mtime).strftime('%d/%m %H:%M')}" for h in hits)

        speak = re.sub(r"[*_`#\[\]]", "", answer.split("\n")[0])[:200]
        return SkillResult(
            speak=speak or f"Encontre {len(hits)} notas.",
            display=f"# {query}\n\n{answer}\n\n---\n### Fuentes\n{listing}",
            data={"query": query, "hits": len(hits),
                  "notes": [h.rel for h in hits]},
        )
