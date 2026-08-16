"""Abrir busquedas y URLs. Multiplataforma.

FRIDAY no navega ni raspa paginas: abre el navegador del usuario y le deja
el control. Menos codigo, menos formas de equivocarse, y la sesion y las
cookies siguen siendo del usuario.
"""
from __future__ import annotations

import re
import webbrowser
from urllib.parse import quote_plus

from core.policy import Policy

ENGINES: dict[str, str] = {
    "default": "https://duckduckgo.com/?q={q}",
    "duckduckgo": "https://duckduckgo.com/?q={q}",
    "google": "https://www.google.com/search?q={q}",
    "bing": "https://www.bing.com/search?q={q}",
    "youtube": "https://www.youtube.com/results?search_query={q}",
    "github": "https://github.com/search?q={q}",
    "wikipedia": "https://es.wikipedia.org/w/index.php?search={q}",
    "maps": "https://www.google.com/maps/search/{q}",
}

# Sitios que la gente pide por nombre como si fueran programas. «Abre
# YouTube» no es una busqueda ni una aplicacion instalada: es un destino.
# Sin esta tabla, la skill `sistema` contesta «no encuentro YouTube
# instalada», que es tecnicamente cierto y practicamente inutil.
SITES: dict[str, str] = {
    "youtube": "https://www.youtube.com/",
    "gmail": "https://mail.google.com/",
    "correo": "https://mail.google.com/",
    "drive": "https://drive.google.com/",
    "calendario": "https://calendar.google.com/",
    "maps": "https://www.google.com/maps",
    "mapas": "https://www.google.com/maps",
    "github": "https://github.com/",
    "chatgpt": "https://chat.openai.com/",
    "claude": "https://claude.ai/",
    "wikipedia": "https://es.wikipedia.org/",
    "traductor": "https://translate.google.com/",
    "whatsapp": "https://web.whatsapp.com/",
    "netflix": "https://www.netflix.com/",
    "twitch": "https://www.twitch.tv/",
    "reddit": "https://www.reddit.com/",
    "x": "https://x.com/",
    "twitter": "https://x.com/",
    "instagram": "https://www.instagram.com/",
    "linkedin": "https://www.linkedin.com/feed/",
    "spotify web": "https://open.spotify.com/",
    "amazon": "https://www.amazon.com/",
    "mercado libre": "https://www.mercadolibre.com/",
    "stack overflow": "https://stackoverflow.com/",
}


def resolve_site(name: str) -> str:
    """Nombre hablado a URL. Cadena vacia si no es un sitio conocido.

    Se exige coincidencia por palabra completa: sin eso, «abre x» pegaria
    dentro de cualquier cosa que contenga una x.
    """
    key = name.strip().lower().strip(" .,")
    if key in SITES:
        return SITES[key]
    for site, url in SITES.items():
        if re.search(rf"(?<!\w){re.escape(site)}(?!\w)", key):
            return url
    return ""


class BrowserWebOpener:
    """Implementa `WebOpener`."""

    def __init__(self, policy: Policy, default_engine: str = "default"):
        self.policy = policy
        self.default_engine = default_engine if default_engine in ENGINES else "default"
        self.last_error = ""

    def open_site(self, name: str) -> str:
        """Abre un sitio conocido por su nombre. Devuelve la URL, o vacio."""
        url = resolve_site(name)
        if not url:
            self.last_error = f"«{name}» no esta en la tabla de sitios"
            return ""
        return url if self.open_url(url) else ""

    def search(self, query: str, engine: str = "default") -> str:
        tpl = ENGINES.get(engine if engine in ENGINES else self.default_engine,
                          ENGINES["default"])
        url = tpl.format(q=quote_plus(query.strip()))
        return url if self.open_url(url) else ""

    def open_url(self, url: str) -> bool:
        decision = self.policy.can_web(url)
        if not decision.allowed:
            self.last_error = decision.reason
            return False
        if not url.lower().startswith(("http://", "https://")):
            self.last_error = "solo se abren URLs http/https"
            return False
        self.last_error = ""
        try:
            return bool(webbrowser.open(url))
        except Exception as exc:
            self.last_error = str(exc)[:140]
            return False
