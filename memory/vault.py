"""El vault. Solo archivos markdown. Cero base de datos.

Estructura:
    vault/raw/      captura cruda (transcripciones, volcados)
    vault/wiki/     notas atomicas enlazadas -> el grafo
    vault/outputs/  lo que FRIDAY produce (planes, resumenes)

Compatible con Obsidian sin plugins: frontmatter YAML + [[wikilinks]].
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

# Palabras que aparecen en todas las notas y por tanto no distinguen ninguna.
# La lista es corta a proposito: solo lo estructural del castellano hablado.
# Recortarla de mas convertiria la busqueda en algo que falla en silencio.
_VACIAS = frozenset("""
que qué de la el los las un una unos unas y o pero si no me te se le lo nos
en con por para del al es son era eran ser estar esta este esto estos estas
ese esa eso mi tu su sus mis tus como cuando donde porque pues ya muy mas más
hay ha he has han sobre entre desde hasta tambien también todo toda todos
todas algo alguien nada cual cuales quien quienes yo tu él ella ellos ellas
""".split())

WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:[#|][^\]]*)?\]\]")
TAG = re.compile(r"(?<![\w/])#([A-Za-zÁÉÍÓÚÜÑáéíóúüñ][\w\-/]*)")
FM_FENCE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.S)


def slugify(text: str) -> str:
    """Nombre de archivo seguro conservando legibilidad."""
    text = unicodedata.normalize("NFC", text).strip()
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", text)
    text = re.sub(r"\s+", " ", text)
    return text[:120].strip(" .") or "sin-titulo"


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parser YAML minimo: escalares, listas inline y listas con guion.

    Deliberadamente sin PyYAML — una dependencia menos y el formato que
    escribimos siempre es plano.
    """
    m = FM_FENCE.match(text)
    if not m:
        return {}, text
    meta: dict[str, Any] = {}
    key = None
    for line in m.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.lstrip().startswith("- ") and key:
            meta.setdefault(key, [])
            if isinstance(meta[key], list):
                meta[key].append(_coerce(line.lstrip()[2:].strip()))
            continue
        if ":" in line:
            key, _, val = line.partition(":")
            key, val = key.strip(), val.strip()
            if not val:
                meta[key] = []
            elif val.startswith("[") and val.endswith("]"):
                meta[key] = [_coerce(v.strip()) for v in val[1:-1].split(",") if v.strip()]
            else:
                meta[key] = _coerce(val)
    return meta, text[m.end():]


def _coerce(v: str) -> Any:
    v = v.strip().strip('"').strip("'")
    low = v.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        pass
    return v


def render_frontmatter(meta: dict[str, Any]) -> str:
    if not meta:
        return ""
    out = ["---"]
    for k, v in meta.items():
        if isinstance(v, (list, tuple)):
            out.append(f"{k}: [{', '.join(str(x) for x in v)}]")
        elif isinstance(v, bool):
            out.append(f"{k}: {'true' if v else 'false'}")
        else:
            out.append(f"{k}: {v}")
    out.append("---\n")
    return "\n".join(out)


@dataclass
class Note:
    path: Path
    rel: str                       # p.ej. "wiki/Proyecto X.md"
    title: str
    meta: dict[str, Any] = field(default_factory=dict)
    body: str = ""
    links: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    mtime: float = 0.0
    size: int = 0

    @property
    def zone(self) -> str:
        return self.rel.split("/", 1)[0] if "/" in self.rel else ""

    def excerpt(self, n: int = 220) -> str:
        clean = re.sub(r"\s+", " ", self.body.strip())
        return clean[:n] + ("…" if len(clean) > n else "")

    def to_json(self) -> dict[str, Any]:
        return {"rel": self.rel, "title": self.title, "zone": self.zone,
                "tags": self.tags, "links": self.links, "meta": self.meta,
                "mtime": self.mtime, "size": self.size}


class Vault:
    """Lectura/escritura del vault. Todo es un archivo, siempre."""

    def __init__(self, root: Path | str, raw="raw", wiki="wiki", outputs="outputs",
                 daily_format="%Y-%m-%d"):
        self.root = Path(root)
        self.raw = self.root / raw
        self.wiki = self.root / wiki
        self.outputs = self.root / outputs
        self.daily_format = daily_format
        for d in (self.raw, self.wiki, self.outputs):
            d.mkdir(parents=True, exist_ok=True)

    # -- lectura ------------------------------------------------------
    def files(self) -> Iterable[Path]:
        for p in self.root.rglob("*.md"):
            if ".obsidian" not in p.parts and ".trash" not in p.parts:
                yield p

    def read(self, path: Path | str) -> Note:
        p = self._resolve(path)
        text = p.read_text(encoding="utf-8", errors="replace")
        meta, body = parse_frontmatter(text)
        st = p.stat()
        return Note(
            path=p,
            rel=p.relative_to(self.root).as_posix(),
            title=str(meta.get("title") or p.stem),
            meta=meta,
            body=body,
            links=sorted({m.group(1).strip() for m in WIKILINK.finditer(body)}),
            tags=sorted({m.group(1) for m in TAG.finditer(body)} |
                        set(map(str, meta.get("tags", []) or []))),
            mtime=st.st_mtime,
            size=st.st_size,
        )

    def exists(self, path: Path | str) -> bool:
        try:
            return self._resolve(path).exists()
        except ValueError:
            return False

    # -- escritura ----------------------------------------------------
    def write(self, path: Path | str, content: str, meta: dict[str, Any] | None = None,
              mode: str = "create") -> Note:
        """mode: create (sobrescribe) | append | prepend"""
        p = self._resolve(path)
        p.parent.mkdir(parents=True, exist_ok=True)

        if mode in ("append", "prepend") and p.exists():
            old = p.read_text(encoding="utf-8", errors="replace")
            old_meta, old_body = parse_frontmatter(old)
            merged = {**old_meta, **(meta or {})}
            merged["updated"] = datetime.now().isoformat(timespec="seconds")
            body = (old_body.rstrip() + "\n\n" + content.strip() + "\n") if mode == "append" \
                else (content.strip() + "\n\n" + old_body.lstrip())
            p.write_text(render_frontmatter(merged) + body, encoding="utf-8")
        else:
            m = dict(meta or {})
            m.setdefault("created", datetime.now().isoformat(timespec="seconds"))
            m["updated"] = m["created"]
            p.write_text(render_frontmatter(m) + content.strip() + "\n", encoding="utf-8")
        return self.read(p)

    def append_section(self, path: Path | str, heading: str, lines: list[str]) -> Note:
        """Anade lineas bajo un encabezado; lo crea si no existe."""
        p = self._resolve(path)
        block = "\n".join(lines).rstrip()
        if p.exists():
            text = p.read_text(encoding="utf-8", errors="replace")
            meta, body = parse_frontmatter(text)
            pat = re.compile(rf"^(#{{1,6}}\s*{re.escape(heading)}\s*)$", re.M)
            m = pat.search(body)
            if m:
                nxt = re.search(r"^#{1,6}\s", body[m.end():], re.M)
                cut = m.end() + (nxt.start() if nxt else len(body) - m.end())
                body = body[:cut].rstrip() + "\n" + block + "\n\n" + body[cut:].lstrip()
            else:
                body = body.rstrip() + f"\n\n## {heading}\n{block}\n"
            meta["updated"] = datetime.now().isoformat(timespec="seconds")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(render_frontmatter(meta) + body.strip() + "\n", encoding="utf-8")
            return self.read(p)
        return self.write(p, f"## {heading}\n{block}", mode="create")

    # -- notas diarias ------------------------------------------------
    def daily_path(self, when: datetime | None = None) -> Path:
        d = (when or datetime.now()).strftime(self.daily_format)
        return self.raw / f"{d}.md"

    def daily(self, when: datetime | None = None) -> Note:
        p = self.daily_path(when)
        if not p.exists():
            d = (when or datetime.now())
            self.write(p, f"# {d.strftime('%A %d de %B, %Y')}\n\n## Log\n",
                       meta={"type": "daily", "date": d.strftime("%Y-%m-%d"),
                             "tags": ["daily"]})
        return self.read(p)

    def log(self, text: str, kind: str = "nota") -> Note:
        """Escribe una linea con hora en el log del dia. La memoria caliente."""
        self.daily()
        stamp = datetime.now().strftime("%H:%M")
        return self.append_section(self.daily_path(), "Log", [f"- `{stamp}` **{kind}** — {text}"])

    # -- busqueda -----------------------------------------------------
    def search(self, query: str, limit: int = 12, zone: str | None = None) -> list[Note]:
        """Escaneo directo con puntuacion. Sin indice externo: son solo archivos.

        Las palabras vacias no puntuan. Parece un detalle de calidad y es un
        problema de correccion: con «que», «los» y «una» contando, casi
        cualquier nota coincidia con casi cualquier pregunta, y esas notas
        acaban inyectadas como contexto en la conversacion libre. Un modelo
        grande ignora el ruido; uno pequeño lo toma por bueno y responde
        sobre una nota que no venia al caso. Devolver **nada** cuando no hay
        coincidencia real es mejor que devolver lo primero que pegue.
        """
        terms = [t for t in (w.lower() for w in re.split(r"\s+", query.strip()))
                 if len(t) > 1 and t not in _VACIAS]
        if not terms:
            return []
        hits: list[tuple[float, Note]] = []
        for p in self.files():
            try:
                note = self.read(p)
            except OSError:
                continue
            if zone and note.zone != zone:
                continue
            hay_title = note.title.lower()
            hay_body = note.body.lower()
            score = 0.0
            for t in terms:
                if t in hay_title:
                    score += 5.0
                score += min(hay_body.count(t), 8) * 1.0
                if any(t in tag.lower() for tag in note.tags):
                    score += 2.0
            if score > 0:
                score += 1.5 if (datetime.now().timestamp() - note.mtime) < 86400 * 3 else 0
                hits.append((score, note))
        hits.sort(key=lambda x: (-x[0], -x[1].mtime))
        return [n for _, n in hits[:limit]]

    def recent(self, hours: int = 24, limit: int = 20, zone: str | None = None) -> list[Note]:
        cutoff = (datetime.now() - timedelta(hours=hours)).timestamp()
        out = []
        for p in self.files():
            try:
                if p.stat().st_mtime >= cutoff:
                    n = self.read(p)
                    if not zone or n.zone == zone:
                        out.append(n)
            except OSError:
                continue
        out.sort(key=lambda n: -n.mtime)
        return out[:limit]

    def all_notes(self) -> list[Note]:
        out = []
        for p in self.files():
            try:
                out.append(self.read(p))
            except OSError:
                continue
        return out

    def stats(self) -> dict[str, Any]:
        notes = self.all_notes()
        links = sum(len(n.links) for n in notes)
        return {
            "notes": len(notes),
            "links": links,
            "tags": len({t for n in notes for t in n.tags}),
            "words": sum(len(n.body.split()) for n in notes),
            "raw": sum(1 for n in notes if n.zone == self.raw.name),
            "wiki": sum(1 for n in notes if n.zone == self.wiki.name),
            "outputs": sum(1 for n in notes if n.zone == self.outputs.name),
            "bytes": sum(n.size for n in notes),
        }

    # -- interno ------------------------------------------------------
    def _resolve(self, path: Path | str) -> Path:
        p = Path(path)
        if not p.is_absolute():
            p = self.root / p
        p = p if p.suffix == ".md" else p.with_suffix(".md")
        p = p.resolve()
        root = self.root.resolve()
        if root not in p.parents and p != root:
            raise ValueError(f"Ruta fuera del vault: {p}")
        return p
