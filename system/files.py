"""Busqueda y organizacion de archivos. Multiplataforma (solo pathlib).

Separado en dos clases por segregacion de interfaces:
  - `LocalFileIndex`   solo lee. Ni un metodo puede modificar nada.
  - `LocalFileOrganizer` planea y aplica. Todo pasa por la politica.

La separacion plan/apply es deliberada: `plan_*` es puro y se le puede
enseñar al usuario antes de tocar un solo byte.
"""
from __future__ import annotations

import os
import re
import shutil
import time
import unicodedata
from datetime import datetime
from pathlib import Path

from core.policy import Policy
from system.ports import FileInfo, FileOp, OpKind, OpResult

_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv",
              "AppData", "$RECYCLE.BIN", "System Volume Information", ".cache"}

# Familias para organizar por tipo
_FAMILIES: dict[str, set[str]] = {
    "Imagenes": {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg", ".heic", ".tiff"},
    "Documentos": {".pdf", ".doc", ".docx", ".txt", ".md", ".rtf", ".odt", ".epub"},
    "Hojas": {".xls", ".xlsx", ".csv", ".ods"},
    "Presentaciones": {".ppt", ".pptx", ".odp"},
    "Video": {".mp4", ".mkv", ".avi", ".mov", ".webm", ".wmv"},
    "Audio": {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac"},
    "Comprimidos": {".zip", ".rar", ".7z", ".tar", ".gz", ".xz"},
    "Instaladores": {".exe", ".msi", ".appx"},
    "Codigo": {".py", ".js", ".ts", ".java", ".c", ".cpp", ".cs", ".go", ".rs", ".html", ".css"},
}


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower()


def family_of(ext: str) -> str:
    ext = ext.lower()
    for fam, exts in _FAMILIES.items():
        if ext in exts:
            return fam
    return "Otros"


class LocalFileIndex:
    """Implementa `FileIndex`. Solo lectura, por construccion."""

    def __init__(self, policy: Policy, max_scan: int = 40_000):
        self.policy = policy
        self.max_scan = max_scan

    def _roots(self, roots: list[Path] | None) -> list[Path]:
        if roots:
            return [r for r in roots if self.policy.can_read(r).allowed]
        return list(self.policy.read_roots)

    def search(self, query: str, roots: list[Path] | None = None,
               limit: int = 20) -> list[FileInfo]:
        terms = [t for t in _fold(query).split() if len(t) > 1]
        if not terms:
            return []

        hits: list[FileInfo] = []
        scanned = 0
        now = time.time()

        for root in self._roots(roots):
            if not root.is_dir():
                continue
            for dirpath, dirnames, filenames in os.walk(root, topdown=True):
                dirnames[:] = [d for d in dirnames
                               if d not in _SKIP_DIRS and not d.startswith(".")]
                for fn in filenames:
                    scanned += 1
                    if scanned > self.max_scan:
                        hits.sort(key=lambda f: -f.score)
                        return hits[:limit]

                    name = _fold(fn)
                    score = 0.0
                    for t in terms:
                        if t == Path(name).stem:
                            score += 5.0
                        elif name.startswith(t):
                            score += 3.0
                        elif t in name:
                            score += 1.5
                    if score <= 0:
                        continue

                    p = Path(dirpath) / fn
                    try:
                        st = p.stat()
                    except OSError:
                        continue
                    if now - st.st_mtime < 86400 * 7:
                        score += 1.0
                    hits.append(FileInfo(path=p, name=fn, size=st.st_size,
                                         mtime=st.st_mtime, is_dir=False,
                                         score=round(score, 2)))

        hits.sort(key=lambda f: (-f.score, -f.mtime))
        return hits[:limit]

    def list_dir(self, path: Path) -> list[FileInfo]:
        if not self.policy.can_read(path).allowed or not path.is_dir():
            return []
        out: list[FileInfo] = []
        try:
            for p in path.iterdir():
                try:
                    st = p.stat()
                except OSError:
                    continue
                out.append(FileInfo(path=p, name=p.name, size=st.st_size,
                                    mtime=st.st_mtime, is_dir=p.is_dir()))
        except OSError:
            return []
        return sorted(out, key=lambda f: (not f.is_dir, f.name.lower()))


class LocalFileOrganizer:
    """Implementa `FileOrganizer`. Unico que escribe en disco."""

    def __init__(self, policy: Policy, index: LocalFileIndex | None = None):
        self.policy = policy
        self.index = index or LocalFileIndex(policy)

    # ── planeacion (pura, no toca nada) ───────────────────────────
    def plan_organize(self, root: Path, strategy: str = "extension") -> list[FileOp]:
        ops: list[FileOp] = []
        if not root.is_dir():
            return ops

        for item in self.index.list_dir(root):
            if item.is_dir:
                continue
            if strategy == "date":
                bucket = datetime.fromtimestamp(item.mtime).strftime("%Y-%m")
                reason = "por fecha de modificacion"
            else:
                bucket = family_of(item.ext)
                reason = f"tipo {item.ext or 'sin extension'}"

            dst_dir = root / bucket
            dst = dst_dir / item.name
            if dst == item.path or item.path.parent == dst_dir:
                continue
            ops.append(FileOp(OpKind.MOVE, item.path, dst, reason))

        return ops

    def plan_rename(self, files: list[FileInfo], pattern: str) -> list[FileOp]:
        """Patron con marcadores: {n} {name} {ext} {date} {fam}"""
        ops: list[FileOp] = []
        for i, f in enumerate(files, 1):
            stem = pattern.format(
                n=f"{i:03d}",
                name=f.path.stem,
                ext=f.ext.lstrip("."),
                date=datetime.fromtimestamp(f.mtime).strftime("%Y-%m-%d"),
                fam=family_of(f.ext),
            )
            stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", stem).strip() or f.path.stem
            dst = f.path.with_name(stem + f.path.suffix)
            if dst != f.path:
                ops.append(FileOp(OpKind.RENAME, f.path, dst, f"patron «{pattern}»"))
        return ops

    # ── aplicacion (la unica escritura) ───────────────────────────
    def apply(self, ops: list[FileOp], dry_run: bool = False) -> OpResult:
        res = OpResult()
        if not ops:
            return res

        gate = self.policy.can_apply_batch(ops)
        if gate.verdict.value == "deny":
            res.skipped = [(op, gate.reason) for op in ops]
            return res

        for op in ops:
            target = op.dst or op.src
            d = self.policy.can_write(Path(target))
            if not d.allowed:
                res.skipped.append((op, d.reason))
                continue
            if dry_run:
                res.done.append(op)
                continue
            try:
                self._execute(op)
                res.done.append(op)
            except OSError as exc:
                res.failed.append((op, str(exc)[:140]))
        return res

    @staticmethod
    def _execute(op: FileOp) -> None:
        if op.kind is OpKind.MKDIR:
            (op.dst or op.src).mkdir(parents=True, exist_ok=True)
            return

        if op.kind is OpKind.TRASH:
            trash = op.src.parent / "_papelera_friday"
            trash.mkdir(exist_ok=True)
            shutil.move(str(op.src), str(_unique(trash / op.src.name)))
            return

        if op.dst is None:
            raise OSError("operacion sin destino")
        op.dst.parent.mkdir(parents=True, exist_ok=True)
        dst = _unique(op.dst)

        if op.kind is OpKind.COPY:
            shutil.copy2(str(op.src), str(dst))
        else:                                    # MOVE y RENAME
            shutil.move(str(op.src), str(dst))


def _unique(path: Path) -> Path:
    """Nunca sobrescribe: si existe, agrega un sufijo."""
    if not path.exists():
        return path
    stem, suffix, parent = path.stem, path.suffix, path.parent
    for i in range(1, 1000):
        cand = parent / f"{stem} ({i}){suffix}"
        if not cand.exists():
            return cand
    return parent / f"{stem} ({int(time.time())}){suffix}"
