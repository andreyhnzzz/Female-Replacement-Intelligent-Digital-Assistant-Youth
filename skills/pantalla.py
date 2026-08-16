"""SKILL — pantalla: leer el contexto de lo que el usuario tiene delante.

Solo lee cuando se le pide. No hay captura de fondo, no hay vigilancia.
Cada lectura se anuncia y queda registrada en el log del dia.
"""
from __future__ import annotations

import re

from .base import Skill, SkillContext, SkillResult

EXPLAIN = re.compile(r"\b(explica|expl[ií]came|qu[eé] dice|qu[eé] significa|"
                     r"res[uú]meme|resume|traduce|ay[uú]dame con)\b", re.I)


class PantallaSkill(Skill):
    name = "pantalla"
    description = "Lee lo que tienes en pantalla y responde sobre ello."
    triggers = [
        r"\bpantalla\b", r"\bqu[eé] estoy viendo\b", r"\bqu[eé] ves\b",
        r"\bmira esto\b", r"\bqu[eé] dice (aqu[ií]|esto|la pantalla)\b",
        r"\bexpl[ií]came esto\b", r"\bqu[eé] hay en pantalla\b",
        r"\ben qu[eé] estoy\b", r"\bl[eé]e la pantalla\b", r"\bcontexto\b",
    ]
    needs = ("screen",)

    async def run(self, ctx: SkillContext) -> SkillResult:
        missing = self.unavailable(ctx)
        if missing:
            return SkillResult(ok=False, error=missing, speak=missing.capitalize() + ".")

        snap = ctx.system.screen.context(with_text=True)

        if not snap.active_title and not snap.text:
            return SkillResult(
                speak="No alcanzo a leer nada en pantalla.",
                display="# Sin lectura\n\nNo hay ventana activa legible.",
                data={"source": snap.source})

        # registro: toda lectura de pantalla queda anotada
        try:
            ctx.vault.log(f"Lectura de pantalla — {snap.active_title[:70]} "
                          f"({snap.source})", kind="pantalla")
        except Exception:
            pass

        question = ctx.text.strip()
        wants_answer = bool(EXPLAIN.search(question)) or len(question.split()) > 4

        base = (f"# En pantalla\n\n**{snap.active_title or '(sin titulo)'}**  \n"
                f"`{snap.active_process}` · fuente `{snap.source}`\n")
        if snap.windows:
            base += "\n### Tambien abierto\n" + \
                    "\n".join(f"- {w}" for w in snap.windows[:8]) + "\n"

        if not wants_answer or not snap.text:
            speak = f"Estas en {snap.active_process or snap.active_title[:50]}."
            extract = f"\n### Texto leido\n```\n{snap.text[:1500]}\n```" if snap.text else ""
            return SkillResult(speak=speak, display=base + extract,
                               data={"title": snap.active_title,
                                     "process": snap.active_process,
                                     "source": snap.source,
                                     "chars": len(snap.text)})

        prompt = (
            f"El usuario tiene esto en pantalla y pregunta: \"{question}\"\n\n"
            f"CONTEXTO DE PANTALLA:\n{snap.brief(2500)}\n\n"
            "Responde en 2-4 lineas de markdown, concreto y util. Si el contexto "
            "no alcanza para responder, dilo en una linea en vez de inventar."
        )

        try:
            answer = (await ctx.engine.complete(prompt, system=ctx.cfg.persona())).strip()
        except Exception as exc:
            answer = f"> El motor no respondio: {exc}"

        speak = re.sub(r"[*_`#\[\]]", "", answer.split("\n")[0])[:220]
        return SkillResult(
            speak=speak or "Leido.",
            display=base + f"\n---\n{answer}",
            data={"title": snap.active_title, "process": snap.active_process,
                  "source": snap.source, "chars": len(snap.text)})
