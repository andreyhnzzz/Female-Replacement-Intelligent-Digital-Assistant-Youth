"""SKILL — motor: cambiar de modelo hablando, y saber cual esta pensando.

«Cambia a Sonnet» no reconstruye nada: el Router sostiene un `EngineSwitch`,
y lo unico que cambia es a que adaptador delega. Por eso se puede saltar de
Opus a un modelo local a media conversacion sin reiniciar FRIDAY.

Esta skill no sabe que existe Claude. Lee el roster del toml y resuelve lo
que oyo contra sus alias; si mañana el roster trae Mixtral, funciona igual.
"""
from __future__ import annotations

import re

from core.engine import load_roster, resolve_model

from .base import Skill, SkillContext, SkillResult

SWITCH = re.compile(
    r"\b(cambia(te)?\s+(a|al?)|c[aá]mbiate|usa|utiliza|pasa\s+a|salta\s+a|"
    r"ponte\s+(en|con)|conmuta\s+a|quiero|dame|prueba\s+con|mete)\b", re.I)

ASK = re.compile(
    r"\b(qu[eé]\s+(modelo|motor|cerebro)|con\s+qu[eé]\s+(est[aá]s\s+)?"
    r"(pensando|piensas)|qui[eé]n\s+(est[aá]\s+)?piensa|modelo\s+actual)\b", re.I)

LIST = re.compile(
    r"\b((qu[eé]|cu[aá]les)\s+modelos|modelos\s+(disponibles|tienes|hay)|"
    r"lista\s+de\s+modelos|cat[aá]logo\s+de\s+modelos|roster)\b", re.I)


class MotorSkill(Skill):
    name = "motor"
    description = ("Cambia el modelo de IA que piensa, lista los disponibles "
                   "y dice cual esta activo.")
    triggers = [
        r"\bqu[eé] modelo\b", r"\bqu[eé] motor\b", r"\bmodelo actual\b",
        r"\bmodelos disponibles\b", r"\bqu[eé] modelos\b", r"\bcu[aá]les modelos\b",
        r"\blista de modelos\b", r"\bcambia de modelo\b", r"\bcambia de motor\b",
    ]
    needs = ()

    def __init__(self, ctx_cfg) -> None:
        super().__init__(ctx_cfg)
        # El roster se lee una vez: `matches` corre en cada peticion y no
        # puede permitirse tocar disco.
        self._roster = load_roster(ctx_cfg)

    # ── enrutado ──────────────────────────────────────────────────
    def matches(self, text: str) -> float:
        """Puntaje propio, porque el generico no basta aqui.

        «cambia a Chrome» y «cambia a Sonnet» comparten el mismo verbo. Lo
        que decide no es el verbo sino el **objeto**: si lo que sigue es un
        alias del roster, es mio; si no, es de `sistema`. Por eso esta skill
        devuelve 0 en vez de competir, en lugar de robarle ventanas.
        """
        low = text.lower()
        if LIST.search(low):
            return 0.95
        if ASK.search(low):
            return 0.94
        if SWITCH.search(low) and self._named(low) is not None:
            return 0.96
        # nombrar un modelo a secas («opus», «ponme el rapido») tambien vale
        if self._named(low) is not None and re.search(
                r"\b(modelo|motor|cerebro|opus|sonnet|haiku|local)\b", low):
            return 0.72
        return super().matches(text)

    def _named(self, text: str):
        return resolve_model(self._roster, text)

    # ── ejecucion ─────────────────────────────────────────────────
    async def run(self, ctx: SkillContext) -> SkillResult:
        engine = ctx.engine
        text = ctx.text.strip()

        if not hasattr(engine, "roster"):
            return SkillResult(
                ok=False, error="motor sin roster",
                speak="Este motor no admite cambio de modelo.",
                display="# Sin conmutador\n\nEl motor activo no es un `EngineSwitch`.")

        if LIST.search(text):
            return self._list(engine)

        target = engine.find(text)
        if target is None or (ASK.search(text) and not SWITCH.search(text)):
            return self._current(engine)

        ok, detail = await engine.switch(target)
        if not ok:
            return SkillResult(
                ok=False, error=detail,
                speak=f"No pude cambiar a {target.label}. {detail}",
                display=f"# Cambio rechazado\n\n**{target.label}**\n\n> {detail}")

        return SkillResult(
            speak=f"Listo, Jefe. Pensando con {target.label}.",
            display=(f"# {target.label}\n\n"
                     f"`{target.backend}` · `{target.model}`\n\n"
                     + (f"> {target.note}\n\n" if target.note else "")
                     + self._table(engine)),
            data={"action": "switch", "key": target.key, "backend": target.backend,
                  "model": target.model})

    # ── lecturas ──────────────────────────────────────────────────
    def _current(self, engine) -> SkillResult:
        spec = engine.spec
        if spec is None:
            return SkillResult(speak="No tengo ningun modelo en el roster.",
                               display="# Roster vacio")
        return SkillResult(
            speak=f"{spec.label}.",
            display=(f"# Motor activo\n\n**{spec.label}**\n\n"
                     f"`{spec.backend}` · `{spec.model}`\n\n"
                     + (f"> {spec.note}\n\n" if spec.note else "")
                     + self._table(engine)),
            data={"action": "current", "key": spec.key, "backend": spec.backend})

    def _list(self, engine) -> SkillResult:
        specs = engine.available()
        return SkillResult(
            speak=f"{len(specs)} modelos en el roster.",
            display="# Modelos disponibles\n\n" + self._table(engine),
            data={"action": "list", "models": [s.key for s in specs]})

    @staticmethod
    def _table(engine) -> str:
        active = engine.spec.key if engine.spec else ""
        rows = ["| | modelo | backend | di |", "|---|---|---|---|"]
        for s in engine.available():
            mark = "●" if s.key == active else "○"
            say = ", ".join(f"«{a}»" for a in s.say[:2]) or f"«{s.key}»"
            rows.append(f"| {mark} | **{s.label}** | `{s.backend}` | {say} |")
        return "\n".join(rows)
