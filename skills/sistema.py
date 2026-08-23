"""SKILL — sistema: abrir aplicaciones, enfocar ventanas, buscar en la web.

Es la mano de FRIDAY sobre la computadora. Depende solo de los puertos de
`system.ports`, nunca de win32: la skill no sabe en que SO corre.
"""
from __future__ import annotations

import re
from pathlib import Path

from core.lang import ENCLITICO

from .base import Skill, SkillContext, SkillResult

# El pronombre pegado importa aqui mas que en ningun sitio: «abrelo» es la
# forma natural de pedir que se abra lo que se acaba de encontrar, y sin
# `ENCLITICO` no entraba en esta rama (ver `core/lang.py`).
#
# Y con el pronombre pegado el imperativo **lleva tilde** —«ábrelo»,
# «lánzalo», «ejecútalo»—, que es justo lo que transcribe el STT. Sin las
# clases de acento, la mitad de las formas naturales seguian sin casar.
OPEN = re.compile(
    r"\b([aá]bre|abrir|l[aá]nza|lanzar|ejec[uú]ta|ejecutar|inicia|iniciar|"
    r"arranca|corre|pon)" + ENCLITICO + r"\b", re.I)
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
        # Con enclitico y con tilde: «abrelo» y «ábrelo» tienen que llegar
        # aqui igual que «abre». Es como se pide abrir lo que se acaba de
        # encontrar, y era la forma que no enrutaba a ninguna parte.
        r"\b[aá]bre" + ENCLITICO + r"\b", r"\babrir\b",
        r"\bl[aá]nza" + ENCLITICO + r"\b", r"\bejec[uú]ta" + ENCLITICO + r"\b",
        r"\binicia" + ENCLITICO + r"\b",
        r"\barranca\b", r"\benfoca\b", r"\bcambia a\b", r"\bventanas\b",
        r"\bqu[eé] tengo abierto\b", r"\bbusca en\b", r"\bgooglea\b",
        r"\bprogramas abiertos\b",
        # «busca gatos en google» tiene el motor al final, no pegado al verbo.
        # Sin este patron el `\bbusca\b` suelto de `vault` se lo lleva y la
        # peticion acaba buscando gatos en tus notas.
        r"\bb[uú]sca(me)?\b.{0,50}\ben (google|youtube|bing|wikipedia|github|"
        r"maps|duckduckgo)\b",
    ]
    needs = ("apps", "launcher")
    riesgo = "efecto"        # lanza aplicaciones y enfoca ventanas
    # «Busca el informe y abrelo»: la primera mitad resuelve una ruta y esta
    # skill la abre. Sin declararlo, el router no encadena — y hace bien,
    # porque «abrelo» a secas es una frase sin objeto.
    acepta = ("archivo", "carpeta")

    async def run(self, ctx: SkillContext) -> SkillResult:
        text = ctx.text.strip()
        sys_ = ctx.system

        if sys_ is None:
            return SkillResult(ok=False, error="sin acceso al sistema",
                               speak="No tengo acceso al sistema en esta plataforma.")

        # Turno encadenado: la mitad anterior ya resolvio QUE abrir, asi que
        # no hay nada que interpretar en «abrelo». Va antes de todas las
        # ramas: con un objeto concreto en la mano, releer la frase solo
        # puede empeorar la decision.
        entregado = ctx.slots.get("entrega")
        if entregado is not None and OPEN.search(text):
            return self._open_entregado(ctx, entregado)

        if LIST.search(text):
            return self._list_windows(ctx)
        if SEARCH.search(text):
            return self._web_search(ctx, text)
        if FOCUS.search(text) and not OPEN.search(text):
            return self._focus(ctx, text)
        if OPEN.search(text):
            return self._open(ctx, text)

        # Sin verbo de abrir, esto NO es una peticion para esta skill.
        #
        # Lanzar era la rama por defecto, y eso convertia cualquier error de
        # enrutado en un programa abierto. Paso de verdad el 17/08/2026 con
        # un modelo local: «Descríbete a ti misma en dos palabras» se enruto
        # aqui con confianza 0.85 y FRIDAY abrio el changelog de WinRAR,
        # porque su acceso directo compartia la palabra «en».
        #
        # El enrutado es probabilistico y siempre lo sera. Lo que no puede
        # ser probabilistico es lo que ocurre cuando se equivoca: una skill
        # con efecto sobre la maquina tiene que reconocer lo suyo, no
        # quedarse con todo lo que le caiga.
        return SkillResult(
            ok=False, error="no es una peticion de sistema",
            speak="No te segui, Jefe. ¿Quieres que abra algo?",
            display=("# No lo tengo claro\n\nEso me llego como si fuera una "
                     "orden para la computadora, pero no dice que abrir, que "
                     "enfocar ni que buscar.\n\nPrueba con **«abre X»**, "
                     "**«cambia a X»** o **«busca X en google»**."),
            data={"texto": text[:120], "motivo": "sin verbo de accion"})

    # ── abrir lo que otra skill resolvio ──────────────────────────
    def _open_entregado(self, ctx: SkillContext, entrega) -> SkillResult:
        """Abre un archivo o carpeta que llego resuelto de la mitad anterior.

        No pasa por `apps.find`: no se busca una aplicacion que se llame como
        el archivo, se le da la ruta al shell y que abra lo que el usuario
        tenga asociado. Y va por `can_open`, no por `can_launch` — la ruta
        salio de rastrear el disco, y ahi aparece cualquier cosa.
        """
        sys_ = ctx.system
        if sys_.launcher is None:
            return SkillResult(ok=False, error="sin lanzador",
                               speak="No puedo abrir archivos aqui.")

        ruta = Path(entrega.valor)
        if not sys_.launcher.open_path(ruta):
            razon = getattr(sys_.launcher, "last_error", "") or "bloqueado por politica"
            return SkillResult(
                ok=False, error=razon,
                speak=f"No pude abrir {entrega.etiqueta or ruta.name}. {razon}.",
                display=f"# No lo abri\n\n**{ruta.name}**\n\n> {razon}",
                data={"path": str(ruta), "motivo": razon})

        return SkillResult(
            speak=f"Abierto {entrega.etiqueta or ruta.name}.",
            display=f"# Abierto\n\n**{ruta.name}**\n\n`{ruta.parent}`",
            data={"action": "open_path", "path": str(ruta)})

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
            # No esta instalada, pero puede ser un destino. «Abre YouTube» no
            # es una aplicacion: contestar «no la encuentro» seria cierto e
            # inutil. Se intenta como sitio antes de rendirse.
            if sys_.web is not None:
                url = sys_.web.open_site(target)
                if url:
                    donde = getattr(sys_.web, "browser_name", "") or "el navegador"
                    return SkillResult(
                        speak=f"{target} en {donde}.",
                        display=f"# {target.title()}\n\nAbierto en **{donde}**.\n\n{url}",
                        data={"action": "open_site", "site": target, "url": url,
                              "browser": donde})

            return SkillResult(
                ok=False, error="no encontrada",
                speak=f"No encuentro «{target}» ni instalada ni como sitio.",
                display=f"# Sin coincidencia\n\nNo hay ninguna aplicacion que responda "
                        f"a **{target}**, y tampoco es un sitio que conozca.\n\n"
                        f"Prueba con el nombre exacto del Menu Inicio, o pideme "
                        f"que **busque** «{target}».",
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

        # El navegador no lo elige FRIDAY: usa el que tengas marcado como
        # predeterminado en Windows, y lo nombra para que sepas donde mirar.
        donde = getattr(sys_.web, "browser_name", "")
        return SkillResult(
            speak=f"Buscando {query}" + (f" en {donde}." if donde else "."),
            display=(f"# Busqueda\n\n**{query}**\n\nmotor: `{engine}`"
                     + (f"  ·  navegador: **{donde}**" if donde else "")
                     + f"\n\n{url}"),
            data={"action": "search", "query": query, "engine": engine,
                  "url": url, "browser": donde})
