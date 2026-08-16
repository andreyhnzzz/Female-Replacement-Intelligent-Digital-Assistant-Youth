"""Leer una pagina y dejarla en texto. Implementa `PageReaderPort`.

Dos caminos distintos a proposito:

- `read(url)` — ya sabes la direccion. Se descarga, se le quitan script,
  style y nav, y queda texto.
- `lookup(tema)` — no sabes la direccion. Aqui NO se raspa la pagina de
  resultados de ningun buscador: ese HTML cambia cada pocas semanas, muchos
  buscadores lo bloquean y el resultado seria un asistente que miente cuando
  se rompe. Se usa la API REST de Wikipedia, que es publica, estable y
  versionada.

Para «abre una busqueda de X» sigue estando `system/web.py`, que se lo pasa
al navegador del usuario. Son cosas distintas: una la lee FRIDAY, la otra la
lees tu.
"""
from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser
from urllib.parse import quote, urlparse

from core.policy import Policy
from system.net import fetch, user_agent
from system.ports import PageText

_WS = re.compile(r"[ \t\r\f\v]+")
_BLANK = re.compile(r"\n{3,}")

# Lo que nunca es contenido. Sin esto, el «texto» de un articulo son
# cuatrocientas palabras de menu de navegacion y avisos de cookies.
_SKIP = {"script", "style", "noscript", "svg", "canvas", "template",
         "nav", "footer", "header", "aside", "form", "button", "iframe"}
_BREAK = {"p", "div", "section", "article", "br", "li", "tr",
          "h1", "h2", "h3", "h4", "h5", "h6", "blockquote"}


class _Extractor(HTMLParser):
    """HTML a texto con la libreria estandar.

    No pretende ser un lector de articulos: pretende no mentir. Conserva los
    saltos estructurales para que el motor vea parrafos y no una sopa.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._depth = 0            # dentro de una etiqueta a ignorar
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP:
            self._depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag in _BREAK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in _SKIP:
            self._depth = max(0, self._depth - 1)
        elif tag == "title":
            self._in_title = False
        elif tag in _BREAK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._depth:
            return
        if self._in_title:
            self.title += data
            return
        text = _WS.sub(" ", data)
        if text.strip():
            self.parts.append(text)

    def result(self) -> tuple[str, str]:
        body = _BLANK.sub("\n\n", "".join(self.parts))
        lines = [ln.strip() for ln in body.split("\n")]
        return unescape(self.title).strip(), "\n".join(ln for ln in lines if ln)


def html_to_text(html: str) -> tuple[str, str]:
    """Devuelve (titulo, texto). Nunca lanza: HTML roto es la norma."""
    parser = _Extractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        pass
    return parser.result()


class HttpPageReader:
    """Implementa `PageReaderPort`."""

    WIKI_SUMMARY = "https://{lang}.wikipedia.org/api/rest_v1/page/summary/{t}"
    WIKI_SEARCH = ("https://{lang}.wikipedia.org/w/api.php?action=query&list=search"
                   "&srsearch={t}&format=json&srlimit=1")
    DDG_ANSWER = ("https://api.duckduckgo.com/?q={t}&format=json"
                  "&no_html=1&skip_disambig=1")

    def __init__(self, policy: Policy, max_chars: int = 12000,
                 timeout_s: float = 12.0, lang: str = "es", contact: str = ""):
        self.policy = policy
        self.max_chars = max_chars
        self.timeout_s = timeout_s
        self.lang = lang or "es"
        self.ua = user_agent(contact)
        self.last_error = ""

    # ── leer una URL ──────────────────────────────────────────────
    async def read(self, url: str) -> PageText:
        url = url.strip()
        if not url.lower().startswith(("http://", "https://")):
            url = "https://" + url

        res = await fetch(url, self.policy, timeout_s=self.timeout_s, ua=self.ua)
        if not res.ok:
            self.last_error = res.error
            return PageText(url=url, source=urlparse(url).netloc)

        self.last_error = ""
        title, text = html_to_text(res.body)
        clipped = text[:self.max_chars]
        return PageText(
            url=res.url,
            title=title,
            text=clipped,
            source=urlparse(res.url).netloc,
            truncated=res.truncated or len(text) > self.max_chars,
        )

    # ── buscar un tema ────────────────────────────────────────────
    async def lookup(self, topic: str) -> PageText | None:
        topic = topic.strip()
        if not topic:
            return None

        # Si lo que dieron ya es una direccion, no hay nada que buscar.
        if re.match(r"^(https?://|www\.)", topic, re.I) or \
                re.match(r"^[\w.-]+\.(com|org|net|es|mx|io|dev)(/|$)", topic, re.I):
            page = await self.read(topic)
            return page if not page.empty else None

        import json

        # 1. Titulo exacto en Wikipedia.
        direct = await self._json(
            self.WIKI_SUMMARY.format(lang=self.lang, t=quote(topic.replace(" ", "_"))))
        if direct.ok:
            page = self._from_summary(direct.body)
            if page is not None:
                return page

        # 2. Sin coincidencia exacta —tildes perdidas por el STT, plurales—:
        #    que el buscador de Wikipedia elija el titulo bueno.
        found = await self._json(self.WIKI_SEARCH.format(lang=self.lang, t=quote(topic)))
        if found.ok:
            try:
                hits = json.loads(found.body)["query"]["search"]
            except (ValueError, KeyError, TypeError):
                hits = []
            if hits:
                best = str(hits[0].get("title", ""))
                again = await self._json(self.WIKI_SUMMARY.format(
                    lang=self.lang, t=quote(best.replace(" ", "_"))))
                if again.ok:
                    page = self._from_summary(again.body)
                    if page is not None:
                        return page
        else:
            self.last_error = found.error

        # 3. Respuesta instantanea de DuckDuckGo. Cubre lo que Wikipedia no
        #    tiene y, sobre todo, los ratos en que Wikimedia limita el trafico:
        #    una sola fuente convierte cualquier bloqueo temporal en «FRIDAY
        #    no sabe investigar».
        ddg = await self._json(self.DDG_ANSWER.format(t=quote(topic)))
        if ddg.ok:
            try:
                data = json.loads(ddg.body)
            except ValueError:
                data = {}
            abstract = str(data.get("AbstractText", "")).strip()
            if abstract:
                self.last_error = ""
                return PageText(
                    url=str(data.get("AbstractURL", "")) or "https://duckduckgo.com/",
                    title=str(data.get("Heading", "")) or topic,
                    text=abstract[:self.max_chars],
                    source=str(data.get("AbstractSource", "")) or "duckduckgo",
                )

        if not self.last_error:
            self.last_error = f"sin resultados para «{topic}»"
        return None

    async def _json(self, url: str):
        return await fetch(url, self.policy, timeout_s=self.timeout_s,
                           accept="application/json", ua=self.ua)

    def _from_summary(self, body: str) -> PageText | None:
        import json
        try:
            data = json.loads(body)
        except ValueError:
            return None
        if data.get("type", "").endswith("not_found"):
            return None
        extract = str(data.get("extract", "")).strip()
        if not extract:
            return None
        url = (data.get("content_urls", {}).get("desktop", {}).get("page")
               or f"https://{self.lang}.wikipedia.org/")
        return PageText(url=url, title=str(data.get("title", "")),
                        text=extract[:self.max_chars],
                        source="wikipedia", truncated=False)
