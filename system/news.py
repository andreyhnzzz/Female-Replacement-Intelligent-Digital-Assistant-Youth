"""Titulares por RSS. Implementa `NewsPort`.

Sin dependencias nuevas: `xml.etree` de la biblioteca estandar basta para
RSS 2.0 y Atom, que es el 99% de lo que publica un medio. Meter feedparser
por esto seria pagar una dependencia entera por cuatro etiquetas.

FRIDAY **no raspa portadas**. Lee los feeds que declares en el toml y nada
mas. Un raspador de portada se rompe cada vez que el medio cambia el HTML, y
peor: convierte «leeme las noticias» en trafico indistinguible de un bot.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from xml.etree import ElementTree

from core.policy import Policy
from system.net import fetch, user_agent
from system.ports import NewsItem

# Los feeds Atom viven en su namespace; RSS 2.0 no usa ninguno.
_NS = {"atom": "http://www.w3.org/2005/Atom",
       "dc": "http://purl.org/dc/elements/1.1/"}

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")

# Fuentes por defecto: solo si el toml no trae ninguna. Es un arranque
# razonable, no una recomendacion editorial — cambialas.
DEFAULT_SOURCES: tuple[dict[str, str], ...] = (
    {"name": "Xataka", "topic": "tecnologia",
     "url": "https://www.xataka.com/feedburner.xml"},
    {"name": "BBC Mundo", "topic": "mundo",
     "url": "https://feeds.bbci.co.uk/mundo/rss.xml"},
    {"name": "El Pais Portada", "topic": "general",
     "url": "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/portada"},
)


def _clean(text: str, limit: int = 400) -> str:
    """Quita etiquetas y colapsa espacios. Los feeds meten HTML en el sumario."""
    plain = _WS.sub(" ", _TAG.sub(" ", text or "")).strip()
    return plain[:limit]


def _when(raw: str) -> float:
    """Fecha de publicacion a epoch. Devuelve 0 si el feed no la dio o miente."""
    raw = (raw or "").strip()
    if not raw:
        return 0.0
    try:                                    # RSS 2.0: RFC 822
        return parsedate_to_datetime(raw).timestamp()
    except (TypeError, ValueError):
        pass
    try:                                    # Atom: ISO 8601
        iso = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        return 0.0


def _first(node: ElementTree.Element, *paths: str) -> str:
    for path in paths:
        found = node.find(path, _NS)
        if found is None:
            continue
        if found.text and found.text.strip():
            return found.text.strip()
        href = found.get("href")             # Atom pone el link en un atributo
        if href:
            return href.strip()
    return ""


def _repair(xml: str) -> str:
    """Cierra un XML cortado a media descarga.

    Un feed de portada puede pasar del megabyte y el tope de descarga lo
    parte por donde caiga. El resultado es XML invalido y `fromstring` lo
    rechaza entero: cien titulares perfectamente legibles perdidos porque el
    ultimo venia a medias.

    Se recorta hasta el ultimo elemento completo y se cierran las etiquetas
    de fuera. Se prefiere devolver los titulares que llegaron enteros a no
    devolver ninguno.
    """
    for closing, wrapper in (("</item>", "</channel></rss>"),
                             ("</entry>", "</feed>")):
        cut = xml.rfind(closing)
        if cut != -1:
            return xml[:cut + len(closing)] + wrapper
    return xml


def parse_feed(xml: str, source: str = "", topic: str = "") -> list[NewsItem]:
    """XML de un feed a titulares. Tolerante: un item roto no tumba el resto."""
    xml = xml.strip()
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        try:
            root = ElementTree.fromstring(_repair(xml))
        except ElementTree.ParseError:
            return []

    nodes = root.findall(".//item") or root.findall(".//atom:entry", _NS)
    items: list[NewsItem] = []
    for node in nodes:
        try:
            title = _clean(_first(node, "title", "atom:title"), 200)
            if not title:
                continue
            items.append(NewsItem(
                title=title,
                source=source,
                url=_first(node, "link", "atom:link"),
                summary=_clean(_first(node, "description", "atom:summary",
                                      "atom:content")),
                published=_when(_first(node, "pubDate", "atom:updated",
                                       "atom:published", "dc:date")),
                topic=topic,
            ))
        except Exception:
            continue
    return items


class RssNewsReader:
    """Implementa `NewsPort`. Los feeds se piden en paralelo."""

    def __init__(self, policy: Policy, sources: list[dict[str, Any]] | None = None,
                 timeout_s: float = 10.0, per_source: int = 8, contact: str = ""):
        self.policy = policy
        self.sources = [s for s in (sources or list(DEFAULT_SOURCES))
                        if isinstance(s, dict) and s.get("url")]
        self.timeout_s = timeout_s
        self.per_source = per_source
        self.ua = user_agent(contact)
        self.last_errors: list[str] = []

    def topics(self) -> list[str]:
        seen: list[str] = []
        for s in self.sources:
            t = str(s.get("topic", "")).strip().lower()
            if t and t not in seen:
                seen.append(t)
        return seen

    def _selected(self, topic: str) -> list[dict[str, Any]]:
        """Filtra por tema. Si el tema no existe en ninguna fuente, no se
        devuelve una lista vacia: se devuelven todas. Fallar en silencio ante
        un tema mal transcrito es peor que traer de mas."""
        want = (topic or "").strip().lower()
        if not want:
            return self.sources
        hit = [s for s in self.sources
               if want in str(s.get("topic", "")).lower()
               or want in str(s.get("name", "")).lower()]
        return hit or self.sources

    async def headlines(self, topic: str = "", limit: int = 12) -> list[NewsItem]:
        sources = self._selected(topic)
        self.last_errors = []
        if not sources:
            return []

        async def one(src: dict[str, Any]) -> list[NewsItem]:
            label = str(src.get("name") or src["url"])
            res = await fetch(str(src["url"]), self.policy,
                              timeout_s=self.timeout_s, ua=self.ua,
                              # Un feed de portada pasa del megabyte con
                              # facilidad; el tope por defecto lo partiria.
                              max_bytes=2 * 1024 * 1024,
                              accept="application/rss+xml,application/xml,text/xml")
            if not res.ok:
                self.last_errors.append(f"{label}: {res.error}")
                return []
            got = parse_feed(res.body, str(src.get("name", "")),
                             str(src.get("topic", "")))
            if not got:
                # Descargar y no entender es un fallo distinto de no poder
                # descargar, y se arregla distinto. Decirlo ahorra media hora.
                self.last_errors.append(f"{label}: respondio pero no es un feed legible")
            return got[:self.per_source]

        batches = await asyncio.gather(*(one(s) for s in sources),
                                       return_exceptions=True)

        clean: list[list[NewsItem]] = []
        seen: set[str] = set()
        for batch in batches:
            if isinstance(batch, BaseException):
                self.last_errors.append(str(batch)[:120])
                continue
            keep: list[NewsItem] = []
            for it in batch:
                # La misma agencia reaparece en varios medios: dedup por titular
                fingerprint = _WS.sub(" ", it.title.lower()).strip()
                if fingerprint in seen:
                    continue
                seen.add(fingerprint)
                keep.append(it)
            # Dentro de cada medio, lo mas nuevo primero.
            keep.sort(key=lambda i: i.published or 0.0, reverse=True)
            if keep:
                clean.append(keep)

        return self._interleave(clean, limit)

    @staticmethod
    def _interleave(batches: list[list[NewsItem]], limit: int) -> list[NewsItem]:
        """Un titular de cada medio por ronda.

        Ordenar la mezcla entera por fecha parece lo correcto y no lo es: el
        medio que publica cada diez minutos copa la lista y el briefing acaba
        siendo un solo periodico. Lo que se pide con «las noticias» es
        amplitud, no las ultimas doce entradas del feed mas rapido.

        Dentro de cada medio si manda la fecha, asi que la primera ronda son
        las portadas de todos.
        """
        out: list[NewsItem] = []
        round_ = 0
        while len(out) < limit and any(len(b) > round_ for b in batches):
            for batch in batches:
                if round_ < len(batch):
                    out.append(batch[round_])
                    if len(out) >= limit:
                        break
            round_ += 1
        return out
