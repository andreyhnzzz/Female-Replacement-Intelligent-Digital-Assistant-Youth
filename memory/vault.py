"""El vault. Solo archivos markdown. Cero base de datos.

Estructura:
    vault/raw/      captura cruda (transcripciones, volcados)
    vault/wiki/     notas atomicas enlazadas -> el grafo
    vault/outputs/  lo que FRIDAY produce (planes, resumenes)
    vault/.trash/   lo retirado por la consolidacion, a la espera de caducar

Compatible con Obsidian sin plugins: frontmatter YAML + [[wikilinks]].
"""
from __future__ import annotations

import getpass
import re
import subprocess
import sys
import time
import unicodedata
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from core.proc import NO_WINDOW


def _restrict_to_owner(root: Path) -> None:
    """Quita herencia y deja el vault legible solo por el usuario actual.

    **Apagado de fabrica** (`[privacy] restrict_vault_permissions`, ver
    `Vault.__init__`). `/inheritance:r` no solo saca a "todos": tambien saca
    a SYSTEM y a Administradores, que es exactamente lo que un backup, un
    antivirus o una reinstalacion pueden necesitar para tocar la carpeta.
    Es un candado real pero de los que hay que pedir, no de los que se
    activan solos la primera vez que alguien instala FRIDAY — mover
    permisos de una carpeta que ya existia es la clase de accion que se
    confirma antes, no despues.

    Windows unicamente, y mejor esfuerzo: si `icacls` no esta o el volumen
    no soporta ACL (FAT32, unidad de red), no hay nada que romper — el
    vault sigue siendo el mismo directorio de markdown de siempre.
    """
    if sys.platform != "win32":
        return
    try:
        subprocess.run(
            ["icacls", str(root), "/inheritance:r",
             "/grant:r", f"{getpass.getuser()}:(OI)(CI)F"],
            capture_output=True, timeout=5, check=False,
            creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        pass

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
                 daily_format="%Y-%m-%d", cache_max: int = 512,
                 restrict_permissions: bool = False):
        self.root = Path(root)
        self.raw = self.root / raw
        self.wiki = self.root / wiki
        self.outputs = self.root / outputs
        self.daily_format = daily_format
        # Cache de notas parseadas, con (mtime, size) como clave de validez.
        # Sin indice (regla 1), cada busqueda abre y parsea el vault entero, y
        # un turno hablado hace varias pasadas: `search`, `stats`, el grafo.
        # Esto no persiste nada — se reconstruye leyendo archivos, que es
        # justo lo que la regla pide.
        #
        # Con techo, y en orden de uso: guarda el cuerpo entero de cada nota,
        # y FRIDAY corre el dia entero. Sin tope, un vault que crece no tiene
        # limite superior de RAM. La purga que habia solo corria dentro de
        # `all_notes()`, o sea que dependia de que llamaras a ese metodo.
        self._cache: OrderedDict[Path, tuple[float, int, Note]] = OrderedDict()
        self._cache_max = max(64, int(cache_max))
        # `files()` es un `rglob` sobre todo el vault, y un turno hablado lo
        # recorre varias veces (`search`, `stats`, el grafo). El cache de
        # notas ya amortigua el PARSEO; esto amortigua el LISTADO en si, que
        # sigue costando O(archivos) aunque cada nota este cacheada. TTL
        # corto y no infinito: una escritura de otro proceso (Obsidian
        # abierto a la vez) se nota en unos segundos, no nunca.
        self._files_cache: list[Path] | None = None
        self._files_ts = 0.0
        self._files_ttl = 3.0
        for d in (self.raw, self.wiki, self.outputs):
            d.mkdir(parents=True, exist_ok=True)
        # Apagado de fabrica (ver `_restrict_to_owner`): tocar permisos de
        # una carpeta que el usuario ya tenia no es una mejora silenciosa,
        # es un cambio que se pide. `[privacy] restrict_vault_permissions`
        # en el toml lo activa para quien lo quiera.
        if restrict_permissions:
            _restrict_to_owner(self.root)

    # -- lectura ------------------------------------------------------
    def files(self) -> Iterable[Path]:
        now = time.time()
        if self._files_cache is None or (now - self._files_ts) >= self._files_ttl:
            self._files_cache = [
                p for p in self.root.rglob("*.md")
                if ".obsidian" not in p.parts and ".trash" not in p.parts]
            self._files_ts = now
        yield from self._files_cache

    def _invalida_listado(self) -> None:
        """Un archivo se creo o se fue: el listado cacheado ya no vale.

        Sin esto, escribir una nota y buscarla en el mismo segundo podia no
        encontrarla — el TTL de `files()` la habria dejado fuera.
        """
        self._files_cache = None

    def read(self, path: Path | str) -> Note:
        p = self._resolve(path)
        st = p.stat()
        hit = self._cache.get(p)
        if hit is not None and hit[0] == st.st_mtime and hit[1] == st.st_size:
            self._cache.move_to_end(p)       # sigue siendo reciente
            return hit[2]
        note = self._parse(p, st)
        self._cache[p] = (st.st_mtime, st.st_size, note)
        self._cache.move_to_end(p)
        while len(self._cache) > self._cache_max:
            self._cache.popitem(last=False)  # cae la mas vieja sin usar
        return note

    def _parse(self, p: Path, st: Any) -> Note:
        meta, body = parse_frontmatter(
            p.read_text(encoding="utf-8", errors="replace"))
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
        # Invalidar antes de tocar el archivo, no despues: dos escrituras
        # dentro del mismo tick del reloj pueden dar igual (mtime, size) y la
        # relectura devolveria el contenido viejo.
        self._cache.pop(p, None)
        if not p.exists():
            self._invalida_listado()

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
        self._cache.pop(p, None)
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

    # -- retirada -----------------------------------------------------
    # Una nota consolidada no se borra de golpe. Va a `.trash/`, que
    # `files()` ya no mira, asi que desaparece de la busqueda y del grafo el
    # mismo dia; el disco se libera cuando caduca. Entre las dos cosas hay
    # semanas, y en esas semanas el resumen se puede comparar con el original.
    @property
    def trash_dir(self) -> Path:
        return self.root / ".trash"

    def trash(self, path: Path | str) -> Path:
        """Retira una nota a la papelera. Devuelve donde quedo."""
        p = self._resolve(path)
        self._cache.pop(p, None)
        self._invalida_listado()
        self.trash_dir.mkdir(parents=True, exist_ok=True)
        # El nombre lleva la zona: dos `2026-07-01.md` de zonas distintas se
        # pisarian, y la que se pierde es la que ya no esta en su sitio.
        rel = p.relative_to(self.root).as_posix().replace("/", "__")
        dest = self.trash_dir / rel
        n = 2
        while dest.exists():
            dest = self.trash_dir / f"{Path(rel).stem}-{n}.md"
            n += 1
        p.replace(dest)
        return dest

    def purge_trash(self, older_than_days: float) -> tuple[int, int]:
        """Vacia lo caducado. Devuelve (archivos, bytes liberados)."""
        if not self.trash_dir.is_dir():
            return 0, 0
        cutoff = (datetime.now() - timedelta(days=older_than_days)).timestamp()
        files = freed = 0
        for p in self.trash_dir.glob("*.md"):
            try:
                st = p.stat()
                if st.st_mtime < cutoff:
                    p.unlink()
                    files += 1
                    freed += st.st_size
            except OSError:
                continue
        return files, freed

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
        out, vivos = [], set()
        for p in self.files():
            try:
                out.append(self.read(p))
                vivos.add(p.resolve())
            except OSError:
                continue
        # Barrido: el cache no puede crecer con notas que ya no existen.
        for ido in set(self._cache) - vivos:
            self._cache.pop(ido, None)
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
