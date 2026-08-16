"""Abrir busquedas y URLs. Multiplataforma.

FRIDAY no navega ni raspa paginas: abre el navegador del usuario y le deja
el control. Menos codigo, menos formas de equivocarse, y la sesion y las
cookies siguen siendo del usuario.
"""
from __future__ import annotations

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


class BrowserWebOpener:
    """Implementa `WebOpener`."""

    def __init__(self, policy: Policy, default_engine: str = "default"):
        self.policy = policy
        self.default_engine = default_engine if default_engine in ENGINES else "default"
        self.last_error = ""

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
