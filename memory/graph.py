"""El grafo de notas enlazadas.

Se construye en memoria a partir de los [[wikilinks]] de los archivos.
No se persiste: si borras el grafo, los archivos siguen intactos.
Eso es justo lo que lo hace confiable.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Any

from .vault import Note, Vault, slugify


class Graph:
    def __init__(self, vault: Vault, ttl_s: float = 3.0):
        self.vault = vault
        self.ttl = ttl_s
        self._built = 0.0
        self.notes: dict[str, Note] = {}          # titulo -> Note
        self.by_rel: dict[str, Note] = {}
        self.out: dict[str, set[str]] = defaultdict(set)
        self.inn: dict[str, set[str]] = defaultdict(set)
        self.dangling: dict[str, set[str]] = defaultdict(set)   # link roto -> quien lo cita

    # -- construccion -------------------------------------------------
    def build(self, force: bool = False) -> "Graph":
        if not force and (time.time() - self._built) < self.ttl:
            return self
        self.notes.clear(); self.by_rel.clear()
        self.out.clear(); self.inn.clear(); self.dangling.clear()

        for note in self.vault.all_notes():
            self.notes[note.title] = note
            self.by_rel[note.rel] = note

        for note in self.notes.values():
            for target in note.links:
                t = target.strip()
                if t in self.notes:
                    self.out[note.title].add(t)
                    self.inn[t].add(note.title)
                else:
                    self.dangling[t].add(note.title)
        self._built = time.time()
        return self

    # -- consultas ----------------------------------------------------
    def backlinks(self, title: str) -> list[str]:
        self.build()
        return sorted(self.inn.get(title, set()))

    def forward(self, title: str) -> list[str]:
        self.build()
        return sorted(self.out.get(title, set()))

    def neighbors(self, title: str, depth: int = 1) -> list[str]:
        """Vecindad no dirigida hasta `depth` saltos."""
        self.build()
        seen, frontier = {title}, deque([(title, 0)])
        out: list[str] = []
        while frontier:
            node, d = frontier.popleft()
            if d >= depth:
                continue
            for nb in self.out.get(node, set()) | self.inn.get(node, set()):
                if nb not in seen:
                    seen.add(nb)
                    out.append(nb)
                    frontier.append((nb, d + 1))
        return out

    def context_for(self, titles: list[str], depth: int = 1, max_chars: int = 6000) -> str:
        """Empaqueta notas + vecinos como contexto para el motor."""
        self.build()
        picked: list[str] = []
        for t in titles:
            if t in self.notes and t not in picked:
                picked.append(t)
            for nb in self.neighbors(t, depth):
                if nb not in picked:
                    picked.append(nb)
        chunks, total = [], 0
        for t in picked:
            n = self.notes.get(t)
            if not n:
                continue
            piece = f"### [[{n.title}]]  ({n.rel})\n{n.body.strip()[:1200]}\n"
            if total + len(piece) > max_chars:
                break
            chunks.append(piece); total += len(piece)
        return "\n".join(chunks)

    def orphans(self) -> list[str]:
        self.build()
        return sorted(t for t in self.notes
                      if not self.out.get(t) and not self.inn.get(t))

    def hubs(self, n: int = 8) -> list[tuple[str, int]]:
        self.build()
        deg = {t: len(self.out.get(t, ())) + len(self.inn.get(t, ())) for t in self.notes}
        return sorted(deg.items(), key=lambda kv: -kv[1])[:n]

    def broken(self) -> list[tuple[str, list[str]]]:
        self.build()
        return sorted(((k, sorted(v)) for k, v in self.dangling.items()), key=lambda x: x[0])

    def heal(self, limit: int = 25) -> list[str]:
        """Crea stubs para los enlaces rotos. El grafo se auto-repara."""
        created = []
        for target, sources in self.broken()[:limit]:
            path = self.vault.wiki / f"{slugify(target)}.md"
            if path.exists():
                continue
            refs = "\n".join(f"- [[{s}]]" for s in sources)
            self.vault.write(path, f"# {target}\n\n> Stub creado automaticamente.\n\n"
                                   f"## Citado por\n{refs}\n",
                             meta={"type": "stub", "tags": ["stub"]})
            created.append(target)
        if created:
            self.build(force=True)
        return created

    # -- para el HUD --------------------------------------------------
    def to_json(self, max_nodes: int = 220) -> dict[str, Any]:
        self.build()
        deg = {t: len(self.out.get(t, ())) + len(self.inn.get(t, ())) for t in self.notes}
        top = sorted(self.notes, key=lambda t: (-deg[t], -self.notes[t].mtime))[:max_nodes]
        keep = set(top)
        return {
            "nodes": [{"id": t, "zone": self.notes[t].zone, "deg": deg[t],
                       "mtime": self.notes[t].mtime} for t in top],
            "edges": [{"s": s, "t": d} for s in top for d in self.out.get(s, ()) if d in keep],
            "stats": {"total": len(self.notes), "shown": len(top),
                      "broken": len(self.dangling), "orphans": len(self.orphans())},
        }
