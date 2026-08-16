"""SKILL — web: investigar un tema o leer una pagina, y responder.

La diferencia con `sistema`, que tambien toca la web:

    «busca gatos en google»   -> sistema: te ABRE el navegador. Lees tu.
    «investiga que es un TPU» -> web:     FRIDAY lo lee y te lo cuenta.

Son dos capacidades distintas y por eso son dos skills. Mezclarlas obligaria
a adivinar la intencion en cada frase, y adivinar mal significa abrir seis
pestañas cuando solo querias una respuesta.

Lo que esta skill **no** hace: raspar la pagina de resultados de un buscador.
Ese HTML cambia constantemente y muchos buscadores lo bloquean; un asistente
que se apoya en eso miente en cuanto se rompe. Para temas usa la API de
Wikipedia; para URLs concretas, la pagina que le des.
"""
from __future__ import annotations

import re

from .base import Skill, SkillContext, SkillResult

URL = re.compile(r"(https?://\S+|\bwww\.\S+|\b[\w-]+\.(?:com|org|net|es|mx|io|dev)\S*)",
                 re.I)

ASKS = re.compile(
    r"\b(investiga|aver[ií]gua|indaga|documenta|res[uú]me(me)?|"
    r"l[eé]e(me)?|qu[eé] dice|qu[eé] es|qui[eé]n es|explicame|"
    r"busca informaci[oó]n|busca en la web)\b", re.I)

_NOISE = re.compile(
    r"\b(investiga|aver[ií]gua|indaga|documentate|documenta|res[uú]meme|res[uú]me|"
    r"l[eé]eme|l[eé]e|busca informaci[oó]n( sobre| de)?|busca en la web|"
    r"por favor|para m[ií]|esta p[aá]gina|la p[aá]gina|el art[ií]culo|esta url|"
    r"en internet|en la web|sobre|acerca de)\b", re.I)

# El interrogativo se quita ANTES de consultar. «que es una TPU» buscado tal
# cual hace que el buscador puntue las palabras «que» y «es»; buscando «TPU»
# encuentra lo que se le pidio. Solo se recorta al principio: «la historia de
# que es esto» no es una pregunta sobre «esto».
_LEAD = re.compile(
    r"^\s*(?:(qu[eé]|cu[aá]l(es)?|qui[eé]n(es)?|c[oó]mo|d[oó]nde|cu[aá]ndo|por\s+qu[eé])"
    r"\s+(es|son|era|fue|significa|hace|funciona)?\s*)?"
    r"(?:(el|la|los|las|un|una|unos|unas)\s+)?", re.I)


class WebSkill(Skill):
    name = "web"
    description = ("Investiga un tema o lee una pagina de internet y responde "
                   "con lo que encontro, citando la fuente.")
    triggers = [
        r"\binvestiga\b", r"\baver[ií]gua\b", r"\bindaga\b",
        r"\bbusca informaci[oó]n\b", r"\bbusca en la web\b",
        r"\bres[uú]me(me)? (la p[aá]gina|el art[ií]culo|esta p[aá]gina|esta url)\b",
        r"\bl[eé]e(me)? (la p[aá]gina|el art[ií]culo|esta url|este enlace)\b",
        r"\bqu[eé] dice (la p[aá]gina|el art[ií]culo|esta url|este enlace)\b",
        r"\bqu[eé] hay en (esta p[aá]gina|este enlace)\b",
    ]
    needs = ("pages",)

    async def run(self, ctx: SkillContext) -> SkillResult:
        gap = self.unavailable(ctx)
        if gap:
            return SkillResult(ok=False, error=gap,
                               speak=f"No puedo leer la web: {gap}.",
                               display=f"# Sin acceso\n\n{gap}")

        reader = ctx.system.pages
        text = ctx.text.strip()

        url_hit = URL.search(text)
        if url_hit:
            page = await reader.read(url_hit.group(0).rstrip(".,;)"))
            asked = _NOISE.sub("", URL.sub("", text)).strip(" ,.:;¿?—-")
        else:
            topic = self._topic(text)
            if not topic:
                return SkillResult(speak="¿Que investigo?",
                                   display="# ¿Que investigo?\n\nDime el tema o la URL.")
            page = await reader.lookup(topic)
            asked = topic

        if page is None or page.empty:
            why = getattr(reader, "last_error", "") or "no encontre nada legible"
            return SkillResult(
                ok=False, error=why,
                speak=f"No pude leerlo. {why}.",
                display=f"# Sin lectura\n\n> {why}\n\n"
                        "Si la pagina exige sesion o javascript, no la puedo leer: "
                        "pideme que te la **abra** en el navegador.")

        answer = await self._answer(ctx, page, asked)
        cite = f"[{page.title or page.source}]({page.url})" if page.url else page.source

        return SkillResult(
            speak=self._first_lines(answer),
            display=(f"# {page.title or asked}\n\n{answer}\n\n---\n\n"
                     f"**Fuente:** {cite}"
                     + ("\n\n> Lectura parcial: la pagina era mas larga de lo que leo."
                        if page.truncated else "")),
            data={"action": "read", "url": page.url, "source": page.source,
                  "chars": len(page.text), "truncated": page.truncated})

    # ── extraer el tema ───────────────────────────────────────────
    def _topic(self, text: str) -> str:
        cleaned = _NOISE.sub(" ", ASKS.sub(" ", text, count=1))
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ,.:;¿?¡!—-")
        stripped = _LEAD.sub("", cleaned, count=1).strip(" ,.:;¿?¡!—-")
        # Si quitar el interrogativo no deja nada, la pregunta ERA el tema.
        return stripped or cleaned

    # ── redactar la respuesta ─────────────────────────────────────
    async def _answer(self, ctx: SkillContext, page, asked: str) -> str:
        prompt = (
            f"TEXTO LEIDO DE {page.url}:\n\n{page.text}\n\n"
            f"---\n\nEl usuario pregunto: \"{asked or page.title}\"\n\n"
            "Responde SOLO con markdown, en este orden:\n"
            "1. Dos frases directas que respondan la pregunta.\n"
            "2. Una seccion `## Detalle` con 3-5 vinetas.\n\n"
            "Reglas duras: usa unicamente lo que esta en el texto de arriba. "
            "Si el texto no responde la pregunta, dilo en la primera frase en "
            "vez de rellenar. No inventes cifras, fechas ni nombres."
        )
        try:
            out = (await ctx.engine.complete(prompt, system=ctx.cfg.persona())).strip()
            return out or page.text[:1200]
        except Exception as exc:
            # Sin motor, el texto crudo sigue siendo mas util que un error
            return (f"> El motor no respondio ({str(exc)[:80]}). Texto leido:\n\n"
                    + page.text[:1500])

    @staticmethod
    def _first_lines(markdown: str, limit: int = 280) -> str:
        """Lo hablado son las primeras frases, sin markdown ni encabezados."""
        for block in markdown.split("\n"):
            plain = re.sub(r"[#*`_>\[\]()]", "", block).strip()
            if len(plain) > 30:
                return plain[:limit]
        return re.sub(r"\s+", " ", markdown)[:limit]
