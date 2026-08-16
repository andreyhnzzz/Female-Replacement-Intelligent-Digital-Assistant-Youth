"""SKILL — archivos: buscar, organizar y renombrar.

Nada se toca sin plan previo. Toda operacion se planea, se describe, y solo
se aplica si la politica lo permite o si el usuario confirma en voz alta.
Es la unica forma responsable de dar automatizacion de archivos a un
sistema que escucha por microfono.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from .base import PendingAction, Skill, SkillContext, SkillResult

FIND = re.compile(r"\b(busca|b[uú]scame|encuentra|localiza|d[oó]nde est[aá])\b", re.I)
ORGANIZE = re.compile(r"\b(organiza|ordena|acomoda|clasifica|limpia)\b", re.I)
RENAME = re.compile(r"\b(renombra|renombrar|cambia el nombre)\b", re.I)

BY_DATE = re.compile(r"\bpor fecha\b", re.I)
_STOP = re.compile(r"^(el|la|los|las|un|una|mi|mis|archivo|archivos|carpeta|"
                   r"la carpeta|el archivo)\s+", re.I)

# nombres hablados de carpetas -> rutas reales
_FOLDERS = {
    "descargas": "~/Downloads", "downloads": "~/Downloads",
    "documentos": "~/Documents", "documents": "~/Documents",
    "escritorio": "~/Desktop", "desktop": "~/Desktop",
    "imagenes": "~/Pictures", "im[aá]genes": "~/Pictures", "fotos": "~/Pictures",
    "musica": "~/Music", "m[uú]sica": "~/Music", "videos": "~/Videos",
}


def _human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} GB"


def _folder_from(text: str) -> Path | None:
    low = text.lower()
    for spoken, target in _FOLDERS.items():
        if re.search(rf"\b{spoken}\b", low):
            return Path(os.path.expandvars(target)).expanduser()
    return None


class ArchivosSkill(Skill):
    name = "archivos"
    description = "Busca, organiza y renombra archivos con plan previo."
    triggers = [
        r"\barchivos?\b", r"\bcarpeta\b", r"\borganiza\b", r"\bordena\b",
        r"\brenombra\b", r"\bdescargas\b", r"\bd[oó]nde est[aá]\b",
        r"\bencuentra\b", r"\blocaliza\b", r"\bclasifica\b", r"\blimpia\b",
        # compuesto: desempata contra vault, que tambien reclama "busca"
        r"\b(busca|b[uú]scame|encuentra|localiza)\w*\s+"
        r"(el\s+|la\s+|los\s+|las\s+|mi\s+|mis\s+|un\s+|una\s+)?"
        r"(archivos?|carpetas?|documentos?|ficheros?|pdf|im[aá]genes?|fotos?)\b",
    ]
    needs = ("files",)

    async def run(self, ctx: SkillContext) -> SkillResult:
        missing = self.unavailable(ctx)
        if missing:
            return SkillResult(ok=False, error=missing, speak=missing.capitalize() + ".")

        text = ctx.text.strip()
        if ORGANIZE.search(text):
            return self._organize(ctx, text)
        if RENAME.search(text):
            return self._rename(ctx, text)
        return self._find(ctx, text)

    # ── buscar ────────────────────────────────────────────────────
    def _find(self, ctx: SkillContext, text: str) -> SkillResult:
        query = _STOP.sub("", FIND.sub("", text, count=1).strip(" ,.:;¿?—-")).strip()
        if not query:
            return SkillResult(speak="¿Que archivo busco?", display="# ¿Que busco?")

        root = _folder_from(text)
        roots = [root] if root else None
        hits = ctx.system.files.search(query, roots=roots,
                                       limit=int(self.opts.get("max_results", 15)))

        if not hits:
            where = f" en {root.name}" if root else ""
            return SkillResult(
                speak=f"Sin rastro de «{query}»{where}.",
                display=f"# Sin resultados\n\nBusque **{query}**{where}. Nada.",
                data={"query": query, "hits": 0})

        lines = [f"# {query}", "", f"### {len(hits)} coincidencias", ""]
        for f in hits[:12]:
            lines.append(f"- **{f.name}**  ·  {_human(f.size)}  \n"
                         f"  `{f.path.parent}`")

        return SkillResult(
            speak=f"{len(hits)} coincidencias. La mejor: {hits[0].name}.",
            display="\n".join(lines),
            data={"query": query, "hits": len(hits),
                  "files": [str(f.path) for f in hits[:12]],
                  "top": str(hits[0].path)})

    # ── organizar ─────────────────────────────────────────────────
    def _organize(self, ctx: SkillContext, text: str) -> SkillResult:
        root = _folder_from(text)
        if root is None:
            return SkillResult(
                speak="¿Que carpeta organizo? Puedo con descargas, documentos o escritorio.",
                display="# ¿Cual?\n\nDime: descargas, documentos, escritorio, "
                        "imagenes, musica o videos.")
        if not root.is_dir():
            return SkillResult(ok=False, error="no existe",
                               speak=f"La carpeta {root.name} no existe.")

        if ctx.system.organizer is None:
            return SkillResult(ok=False, error="sin organizador",
                               speak="No tengo permiso para mover archivos.")

        strategy = "date" if BY_DATE.search(text) else "extension"
        ops = ctx.system.organizer.plan_organize(root, strategy)

        if not ops:
            return SkillResult(
                speak=f"{root.name} ya esta ordenada. Nada que mover.",
                display=f"# {root.name}\n\nYa esta organizada. Cero movimientos.",
                data={"root": str(root), "ops": 0})

        buckets: dict[str, int] = {}
        for op in ops:
            b = op.dst.parent.name if op.dst else "?"
            buckets[b] = buckets.get(b, 0) + 1
        resumen = "\n".join(f"- **{k}** — {v} archivo{'s' if v > 1 else ''}"
                            for k, v in sorted(buckets.items(), key=lambda kv: -kv[1]))

        gate = ctx.policy.can_apply_batch(ops) if ctx.policy else None
        preview = "\n".join(f"- {op.describe()}" for op in ops[:8])
        display = (f"# Plan para {root.name}\n\n"
                   f"**{len(ops)}** movimientos, estrategia `{strategy}`\n\n"
                   f"### Destinos\n{resumen}\n\n### Muestra\n{preview}")

        organizer = ctx.system.organizer

        def _apply() -> SkillResult:
            res = organizer.apply(ops)
            return SkillResult(
                speak=f"Patron integrado. {res.summary()}.",
                display=f"# {root.name} organizada\n\n{res.summary()}\n\n### Destinos\n{resumen}",
                data={"root": str(root), "applied": len(res.done),
                      "failed": len(res.failed), "skipped": len(res.skipped)},
                ok=res.ok)

        if gate is not None and gate.needs_confirm:
            return SkillResult(
                speak=f"Voy a mover {len(ops)} archivos en {root.name}. ¿Confirmas?",
                display=display + f"\n\n---\n**Espera tu confirmacion.** {gate.reason}.\n\n"
                                  "Di **si** para aplicar, **cancela** para descartar.",
                data={"root": str(root), "planned": len(ops), "buckets": buckets},
                pending=PendingAction(
                    describe=f"organizar {root.name}: {len(ops)} movimientos", run=_apply))

        if gate is not None and not gate.allowed:
            return SkillResult(ok=False, error=gate.reason,
                               speak=f"No puedo. {gate.reason}.",
                               display=f"# Bloqueado\n\n> {gate.reason}\n\n{display}")
        return _apply()

    # ── renombrar ─────────────────────────────────────────────────
    def _rename(self, ctx: SkillContext, text: str) -> SkillResult:
        root = _folder_from(text)
        if root is None or not root.is_dir():
            return SkillResult(
                speak="¿En que carpeta renombro?",
                display="# ¿Cual?\n\nDime la carpeta: descargas, documentos, escritorio…")
        if ctx.system.organizer is None:
            return SkillResult(ok=False, error="sin organizador",
                               speak="No tengo permiso para renombrar.")

        files = [f for f in ctx.system.files.search("", roots=[root], limit=200)] \
            or [f for f in _list(ctx, root)]
        files = [f for f in files if not f.is_dir][:60]
        if not files:
            return SkillResult(speak=f"{root.name} esta vacia.",
                               display=f"# {root.name}\n\nVacia.")

        pattern = self.opts.get("rename_pattern", "{date} — {name}")
        ops = ctx.system.organizer.plan_rename(files, pattern)
        if not ops:
            return SkillResult(speak="Ya tienen el nombre correcto.",
                               display="# Sin cambios\n\nLos nombres ya siguen el patron.")

        preview = "\n".join(f"- `{op.src.name}`  →  `{op.dst.name}`" for op in ops[:10])
        organizer = ctx.system.organizer

        def _apply() -> SkillResult:
            res = organizer.apply(ops)
            return SkillResult(speak=f"Nucleo actualizado. {res.summary()}.",
                               display=f"# Renombrado\n\n{res.summary()}\n\n{preview}",
                               data={"applied": len(res.done)}, ok=res.ok)

        return SkillResult(
            speak=f"Voy a renombrar {len(ops)} archivos con el patron «{pattern}». ¿Confirmas?",
            display=(f"# Plan de renombrado\n\n**{len(ops)}** archivos en `{root.name}`\n\n"
                     f"patron: `{pattern}`\n\n### Muestra\n{preview}\n\n---\n"
                     "Di **si** para aplicar, **cancela** para descartar."),
            data={"planned": len(ops), "pattern": pattern, "root": str(root)},
            pending=PendingAction(describe=f"renombrar {len(ops)} archivos", run=_apply))


def _list(ctx: SkillContext, root: Path):
    idx = ctx.system.files
    return idx.list_dir(root) if hasattr(idx, "list_dir") else []
