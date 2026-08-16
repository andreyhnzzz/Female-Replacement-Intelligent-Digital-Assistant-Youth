"""SKILL — sistema: abrir aplicaciones, enfocar ventanas, buscar en la web.

Es la mano de FRIDAY sobre la computadora. Depende solo de los puertos de
`system.ports`, nunca de win32: la skill no sabe en que SO corre.
"""
from __future__ import annotations

import re

from .base import Skill, SkillContext, SkillResult

OPEN = re.compile(
    r"\b(abre|abrir|abreme|lanza|lanzar|ejecuta|ejecutar|inicia|iniciar|"
    r"arranca|corre|pon|ponme)\b", re.I)
FOCUS = re.compile(r"\b(enfoca|enf[oó]came|cambia a|ve a|tr[aá]eme|muestra|pasa a)\b", re.I)
SEARCH = re.compile(r"\b(busca|b[uú]scame|buscar|investiga|google[a]?|averigua)\b", re.I)
LIST = re.compile(r"\b(qu[eé] tengo abierto|ventanas|qu[eé] hay abierto|"
                  r"programas abiertos|aplicaciones abiertas)\b", re.I)

# lo que sigue a "busca ... en <motor>"
ENGINE_IN = re.compile(r"\ben\s+(youtube|google|bing|wikipedia|github|maps|duckduckgo)\b", re.I)

_STOP = re.compile(
    r"^(la|el|los|las|un|una|mi|el programa|la app|la aplicaci[oó]n|"
    r"el navegador|por favor)\s+", re.I)


class SistemaSkill(Skill):
    name = "sistema"
    description = "Abre aplicaciones, cambia de ventana y busca en la web."
    triggers = [
        r"\babre\b", r"\babrir\b", r"\blanza\b", r"\bejecuta\b", r"\binicia\b",
        r"\barranca\b", r"\benfoca\b", r"\bcambia a\b", r"\bventanas\b",
        r"\bqu[eé] tengo abierto\b", r"\bbusca en\b", r"\bgooglea\b",
        r"\bab[rí]eme\b", r"\bprogramas abiertos\b",
    ]
    needs = ("apps", "launcher")

    async def run(self, ctx: SkillContext) -> SkillResult:
        text = ctx.text.strip()
        sys_ = ctx.system

        if sys_ is None:
            return SkillResult(ok=False, error="sin acceso al sistema",
                               speak="No tengo acceso al sistema en esta plataforma.")

        if LIST.search(text):
            return self._list_windows(ctx)
        if SEARCH.search(text):
            return self._web_search(ctx, text)
        if FOCUS.search(text) and not OPEN.search(text):
            return self._focus(ctx, text)
        return self._open(ctx, text)

    # ── abrir aplicacion ──────────────────────────────────────────
    def _open(self, ctx: SkillContext, text: str) -> SkillResult:
        sys_ = ctx.system
        if sys_.apps is None or sys_.launcher is None:
            return SkillResult(ok=False, error="sin catalogo de aplicaciones",
                               speak="No puedo lanzar aplicaciones aqui.")

        target = _STOP.sub("", OPEN.sub("", text, count=1).strip(" ,.:;¿?—-")).strip()
        if not target:
            return SkillResult(speak="¿Que abro?", display="# ¿Que abro?\n\nDime el nombre.")

        # si ya esta abierto, enfocar es mas rapido que lanzar otra instancia
        if sys_.windows is not None and sys_.window_ctl is not None:
            for w in sys_.windows.list_windows():
                blob = f"{w.title} {w.process}".lower()
                if target.lower() in blob:
                    if sys_.window_ctl.focus(w.handle):
                        return SkillResult(
                            speak=f"Ya estaba abierto. Frecuencia estable en {w.process or target}.",
                            display=f"# Enfocado\n\n**{w.title}**\n\n`{w.process}`",
                            data={"action": "focus", "window": w.title})
                    break

        hits = sys_.apps.find(target, limit=4)
        if not hits:
            return SkillResult(
                ok=False, error="no encontrada",
                speak=f"No encuentro «{target}» instalada.",
                display=f"# Sin coincidencia\n\nNo hay ninguna aplicacion que responda "
                        f"a **{target}**.\n\nPrueba con el nombre exacto del Menu Inicio.",
                data={"query": target})

        best = hits[0]
        ok = sys_.launcher.launch(best)
        alts = "\n".join(f"- {a.name}  ·  {a.score}" for a in hits[1:])

        if not ok:
            reason = getattr(sys_.launcher, "last_error", "") or "bloqueado por politica"
            return SkillResult(
                ok=False, error=reason,
                speak=f"No pude abrir {best.name}. {reason}",
                display=f"# Bloqueado\n\n**{best.name}**\n\n> {reason}",
                data={"app": best.name, "reason": reason})

        return SkillResult(
            speak=f"{best.name} en linea.",
            display=(f"# {best.name}\n\nLanzada.\n\n`{best.target}`\n"
                     + (f"\n### Otras coincidencias\n{alts}" if alts else "")),
            data={"action": "launch", "app": best.name, "score": best.score,
                  "alternatives": [a.name for a in hits[1:]]})

    # ── enfocar ventana ───────────────────────────────────────────
    def _focus(self, ctx: SkillContext, text: str) -> SkillResult:
        sys_ = ctx.system
        if sys_.windows is None or sys_.window_ctl is None:
            return SkillResult(ok=False, error="sin control de ventanas",
                               speak="No puedo manipular ventanas aqui.")

        target = _STOP.sub("", FOCUS.sub("", text, count=1).strip(" ,.:;¿?—-")).strip()
        wins = sys_.windows.list_windows()
        match = None
        for w in wins:
            if target.lower() in f"{w.title} {w.process}".lower():
                match = w
                break

        if match is None:
            return SkillResult(
                ok=False, error="ventana no encontrada",
                speak=f"No hay ninguna ventana que sea «{target}».",
                display="# Sin coincidencia\n\n### Abiertas ahora\n"
                        + "\n".join(f"- {w.label}" for w in wins[:12]))

        ok = sys_.window_ctl.focus(match.handle)
        return SkillResult(
            speak=f"{match.process or match.title} al frente." if ok
                  else f"Windows no me dejo enfocar {match.title}. La marque en la barra.",
            display=f"# {'Enfocado' if ok else 'Marcado'}\n\n**{match.title}**\n\n`{match.process}`",
            data={"action": "focus", "window": match.title, "ok": ok})

    # ── listar ventanas ───────────────────────────────────────────
    def _list_windows(self, ctx: SkillContext) -> SkillResult:
        sys_ = ctx.system
        if sys_.windows is None:
            return SkillResult(ok=False, error="sin lectura de ventanas",
                               speak="No puedo ver las ventanas aqui.")
        wins = sys_.windows.list_windows()
        active = sys_.windows.active()

        lines = ["# Ventanas abiertas", ""]
        if active:
            lines += [f"**Al frente:** {active.title}  ", f"`{active.process}`", ""]
        lines.append(f"### {len(wins)} en total")
        lines += [f"- {'○' if w.minimized else '●'} {w.title}"
                  f"{f'  `{w.process}`' if w.process else ''}" for w in wins[:18]]

        return SkillResult(
            speak=f"{len(wins)} ventanas. Al frente: {active.title[:60] if active else 'ninguna'}.",
            display="\n".join(lines),
            data={"count": len(wins), "active": active.title if active else "",
                  "windows": [w.title for w in wins[:18]]})

    # ── busqueda web ──────────────────────────────────────────────
    def _web_search(self, ctx: SkillContext, text: str) -> SkillResult:
        sys_ = ctx.system
        if sys_.web is None:
            return SkillResult(ok=False, error="sin navegador",
                               speak="No puedo abrir el navegador.")

        engine = "default"
        m = ENGINE_IN.search(text)
        if m:
            engine = m.group(1).lower()
            text = ENGINE_IN.sub("", text)

        query = _STOP.sub("", SEARCH.sub("", text, count=1).strip(" ,.:;¿?—-")).strip()
        if not query:
            return SkillResult(speak="¿Que busco?", display="# ¿Que busco?")

        url = sys_.web.search(query, engine)
        if not url:
            reason = getattr(sys_.web, "last_error", "") or "bloqueado por politica"
            return SkillResult(ok=False, error=reason,
                               speak=f"No pude abrir la busqueda. {reason}",
                               display=f"# Bloqueado\n\n> {reason}")

        return SkillResult(
            speak=f"Buscando {query}.",
            display=f"# Busqueda\n\n**{query}**\n\nmotor: `{engine}`\n\n{url}",
            data={"action": "search", "query": query, "engine": engine, "url": url})
