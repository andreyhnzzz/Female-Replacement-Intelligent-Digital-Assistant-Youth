"""Generar documentos hablando: «hazme un PDF con...», «pasa esto a Excel».

Reparto de trabajo, que es la regla 4: el motor **redacta** (devuelve markdown
o filas) y `system/documents.py` **escribe**. Aqui no se escribe un byte sin
pasar por `policy.can_write` (regla 6).

Por que `matches()` es propio y no el generico: «documentos» es una palabra
corriente. Sale en «busca en mis documentos» (de `archivos`) y en «abre la
carpeta Documentos» (de `sistema`), y el puntaje base regala 0.35 a la skill
que se llama como una palabra de la frase. Aqui manda el par **verbo de
crear + formato**, y los verbos de abrir o buscar devuelven 0 aunque la frase
diga «pdf»: querer abrir un PDF no es querer fabricar uno.

Y no hay rama por defecto que actue: si no se reconoce el formato, se dice.
Un error de enrutado no puede acabar en un archivo escrito en tu disco.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

from core.engine import ask_json

from .base import PendingAction, Skill, SkillContext, SkillResult

# ── senales de enrutado ────────────────────────────────────────────
# Los verbos van sueltos a proposito: `matches()` ya exige ademas una palabra
# de formato, asi que «pasa a la siguiente cancion» no llega aqui (no hay
# formato) y no hace falta atar el verbo a su complemento. Atarlo era peor:
# «pasa esto a excel» se escapaba por tener un objeto en medio.
CREAR = re.compile(
    r"\b(haz|hazme|genera|generame|crea|creame|escribe|escribeme|prepara|"
    r"preparame|exporta|exportame|guarda|guardame|pasa|pasalo|pasame|"
    r"convierte|conviertelo|saca|sacame|monta|montame)\b")
# Abrir o buscar NO es crear. Va aparte y gana: es lo que deja «abre el pdf»
# en `sistema` y «busca mis pdf» en `archivos`.
# Ojo con `lista`: es sustantivo mas veces que verbo («hazme una lista»,
# «exportame la lista a xlsx»). Como veto solo vale `listame`, o `lista` en
# posicion de imperativo (al principio). Un veto ancho no es prudente: cuesta
# peticiones buenas y el sintoma es que la skill «no hace nada».
ABRIR = re.compile(r"(\b(abre|abreme|busca|buscame|encuentra|localiza|"
                   r"listame|enseñame|muestrame)\b"
                   r"|\bdonde\s+(?:esta|tengo)\b|^\s*lista\b)")

FORMATOS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("pdf", re.compile(r"\bpdf\b")),
    ("xlsx", re.compile(r"\b(excel|xlsx|hoja\s+de\s+calculo|hoja\s+de\s+cálculo)\b")),
    ("csv", re.compile(r"\bcsv\b")),
)


class DocumentosSkill(Skill):
    name = "documentos"
    description = "Genera un PDF o una hoja de calculo con lo que le pidas."
    triggers = [r"\bpdf\b", r"\bexcel\b", r"\bxlsx\b", r"\bhoja de c[aá]lculo\b"]
    needs = ("documents",)

    # ── enrutado ──────────────────────────────────────────────────
    def matches(self, text: str) -> float:
        low = text.lower()
        formato = self._formato(low)
        if formato is None:
            return 0.0
        if ABRIR.search(low):
            return 0.0                      # abrir o buscar es de otra skill
        if CREAR.search(low):
            return 0.95
        return 0.0

    @staticmethod
    def _formato(low: str) -> str | None:
        for nombre, patron in FORMATOS:
            if patron.search(low):
                return nombre
        return None

    # ── ejecucion ─────────────────────────────────────────────────
    async def run(self, ctx: SkillContext) -> SkillResult:
        escritor = getattr(ctx.system, "documents", None)
        if escritor is None:
            return SkillResult(speak="No puedo escribir documentos aqui.", ok=False)

        low = ctx.text.lower()
        formato = self._formato(low)
        if formato is None:
            # Sin rama por defecto: no se adivina el formato.
            return SkillResult(
                speak="No me quedo claro si lo quieres en PDF o en hoja de calculo.",
                ok=False)

        puede = escritor.formats()
        if formato not in puede:
            falta = ("la interfaz abierta" if formato == "pdf"
                     else "openpyxl instalado")
            return SkillResult(
                speak=f"No puedo generar {formato} ahora mismo: necesito {falta}.",
                display=f"Formatos disponibles: {', '.join(puede)}.", ok=False)

        asunto = self._asunto(ctx.text)
        destino = self._destino(asunto, formato)

        if ctx.policy is not None:
            d = ctx.policy.can_write(destino)
            if not d.allowed and not d.needs_confirm:
                return SkillResult(
                    speak=f"No puedo escribir ahi: {d.reason}.", ok=False)
            if d.needs_confirm:
                return SkillResult(
                    speak=f"¿Creo {destino.name} en {destino.parent.name}?",
                    pending=PendingAction(
                        describe=f"crear {destino}",
                        run=lambda: SkillResult(
                            speak="Confirmado, pero pidemelo otra vez para redactarlo.")))

        if formato == "pdf":
            return await self._pdf(ctx, escritor, destino, asunto)
        return await self._hoja(ctx, escritor, destino, asunto)

    # ── PDF: el motor redacta markdown ────────────────────────────
    async def _pdf(self, ctx: SkillContext, escritor: Any,
                   destino: Path, asunto: str) -> SkillResult:
        prompt = (
            "Escribe el contenido de un documento en markdown sencillo: "
            "subtitulos con ##, listas con -, tablas con | si hacen falta. "
            "Sin preambulo y sin cerca de codigo: solo el documento.\n"
            # El titulo lo pone Python encima; si el motor escribe otro sale
            # dos veces y el PDF empieza repitiendose.
            "NO escribas el titulo principal: ya va puesto. Empieza por el "
            "primer apartado.\n\n"
            # La peticion AL FINAL, pegada a la respuesta (ver CLAUDE.md).
            f"EL USUARIO PIDIO:\n\"{ctx.text.strip()}\"\n\n"
            "El documento:")
        cuerpo = (await ctx.engine.complete(prompt, system=ctx.cfg.persona())).strip()
        if not cuerpo:
            return SkillResult(speak="No consegui redactar el documento.", ok=False)

        import asyncio
        ok = await asyncio.to_thread(escritor.write_pdf, destino, asunto, cuerpo)
        if not ok:
            return SkillResult(speak="No pude escribir el PDF.", ok=False)
        return SkillResult(
            speak=f"Listo, {destino.name} en {destino.parent.name}.",
            display=f"**{destino.name}**\n\n{cuerpo[:1200]}",
            writes=[str(destino)])

    # ── hoja: el motor devuelve filas, Python las escribe ──────────
    async def _hoja(self, ctx: SkillContext, escritor: Any,
                    destino: Path, asunto: str) -> SkillResult:
        tope = int(self.opts.get("max_filas", 200))
        prompt = (
            "Devuelve una tabla como JSON: `cabeceras` es una lista de textos "
            "y `filas` una lista de listas, cada una con tantos valores como "
            "cabeceras. Los numeros van como numero, no como texto.\n\n"
            f"EL USUARIO PIDIO:\n\"{ctx.text.strip()}\"\n\n"
            "Responde SOLO este JSON, sin nada mas:\n"
            '{"cabeceras": ["Mes", "Gasto"], '
            '"filas": [["Enero", 120], ["Febrero", 95]]}')
        esquema = {
            "type": "object",
            "properties": {
                "cabeceras": {"type": "array", "items": {"type": "string"}},
                "filas": {"type": "array", "items": {"type": "array"}},
            },
            "required": ["cabeceras", "filas"],
        }
        datos = await ask_json(ctx.engine, prompt, schema=esquema) or {}
        cabeceras = [str(c) for c in (datos.get("cabeceras") or [])]
        filas = [list(f) for f in (datos.get("filas") or []) if isinstance(f, list)]
        if not cabeceras or not filas:
            return SkillResult(speak="No consegui armar la tabla.", ok=False)
        filas = filas[:tope]

        import asyncio
        real = await asyncio.to_thread(escritor.write_sheet, destino, cabeceras, filas)
        # `write_sheet` devuelve la ruta REAL: si no habia openpyxl es un .csv.
        nota = "" if real.suffix == destino.suffix else " (en CSV, que Excel abre igual)"
        return SkillResult(
            speak=f"Listo, {real.name} con {len(filas)} filas{nota}.",
            display=f"**{real.name}** — {len(filas)} filas\n\n"
                    + " · ".join(cabeceras),
            writes=[str(real)])

    # ── nombre y destino ──────────────────────────────────────────
    @staticmethod
    def _asunto(texto: str) -> str:
        """Lo que va como titulo: la peticion sin el andamiaje de la orden."""
        t = CREAR.sub(" ", texto.lower())
        for _, patron in FORMATOS:
            t = patron.sub(" ", t)
        # `para` y `sobre` NO se quitan: son las que sostienen un titulo.
        # Sin ellas «tres consejos para dormir mejor» quedaba en «tres
        # consejos dormir mejor», que no es español.
        t = re.sub(r"\b(un|una|el|la|los|las|de|con|en|me|"
                   r"documento|archivo|fichero)\b", " ", t)
        t = re.sub(r"\s+", " ", t).strip(" .,;:")
        return (t[:70] or "Documento").capitalize()

    def _destino(self, asunto: str, formato: str) -> Path:
        carpeta = Path(str(self.opts.get("write_to", "~/Documents"))).expanduser()
        limpio = re.sub(r"[^\w\s-]", "", asunto).strip() or "Documento"
        limpio = re.sub(r"\s+", " ", limpio)[:60]
        ext = "xlsx" if formato == "xlsx" else formato
        return carpeta / f"{date.today():%Y-%m-%d} {limpio}.{ext}"
