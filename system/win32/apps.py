"""Catalogo y lanzador de aplicaciones para Windows.

El catalogo se arma del Menu Inicio (los .lnk son la fuente de verdad de lo
que el usuario considera "una aplicacion"), mas los ejecutables del PATH y
un puñado de URIs del sistema.

Se cachea en memoria y se refresca por mtime de las carpetas: escanear el
Menu Inicio en cada peticion costaria cientos de milisegundos.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
import unicodedata
from pathlib import Path

from core.policy import Policy
from system.ports import AppInfo

# URIs nativas: no son archivos pero el usuario las llama "aplicaciones"
_URIS: dict[str, str] = {
    "configuracion": "ms-settings:",
    "ajustes": "ms-settings:",
    "settings": "ms-settings:",
    "papelera": "shell:RecycleBinFolder",
    "explorador": "explorer.exe",
    "descargas": "shell:Downloads",
    "documentos": "shell:Personal",
    "escritorio": "shell:Desktop",
    "calculadora": "calc.exe",
    "bloc de notas": "notepad.exe",
    "terminal": "wt.exe",
    "administrador de tareas": "taskmgr.exe",
}

_START_MENUS = (
    r"%APPDATA%\Microsoft\Windows\Start Menu\Programs",
    r"%PROGRAMDATA%\Microsoft\Windows\Start Menu\Programs",
)


def _fold(s: str) -> str:
    """Normaliza para comparar: sin acentos, minusculas, sin ruido."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9 ]+", " ", s.lower()).strip()


def _score(query: str, name: str) -> float:
    """Puntua que tan bien `name` responde a `query`."""
    q, n = _fold(query), _fold(name)
    if not q or not n:
        return 0.0
    if q == n:
        return 1.0
    if n.startswith(q):
        return 0.9
    if q in n:
        return 0.75
    qt, nt = set(q.split()), set(n.split())
    if qt and qt <= nt:
        return 0.7
    common = qt & nt
    if common:
        return 0.4 + 0.3 * len(common) / len(qt)
    return 0.0


class WindowsAppCatalog:
    """Implementa `AppCatalog`."""

    def __init__(self, ttl_s: float = 120.0):
        self.ttl = ttl_s
        self._apps: list[AppInfo] = []
        self._built = 0.0

    # ── construccion ──────────────────────────────────────────────
    def refresh(self) -> int:
        apps: dict[str, AppInfo] = {}

        for raw in _START_MENUS:
            root = Path(os.path.expandvars(raw))
            if not root.is_dir():
                continue
            try:
                for lnk in root.rglob("*.lnk"):
                    name = lnk.stem
                    key = _fold(name)
                    if key and key not in apps:
                        apps[key] = AppInfo(name=name, target=str(lnk), kind="shortcut")
            except OSError:
                continue

        for label, uri in _URIS.items():
            key = _fold(label)
            if key not in apps:
                apps[key] = AppInfo(name=label, target=uri,
                                    kind="uri" if ":" in uri and not uri.endswith(".exe") else "exe")

        for exe in ("code", "chrome", "msedge", "firefox", "python", "git",
                    "obsidian", "spotify", "discord", "steam"):
            if shutil.which(exe):
                key = _fold(exe)
                if key not in apps:
                    apps[key] = AppInfo(name=exe, target=exe, kind="exe")

        self._apps = list(apps.values())
        self._built = time.time()
        return len(self._apps)

    def _ensure(self) -> None:
        if not self._apps or (time.time() - self._built) > self.ttl:
            self.refresh()

    # ── consulta ──────────────────────────────────────────────────
    def find(self, query: str, limit: int = 5) -> list[AppInfo]:
        self._ensure()
        hits = []
        for app in self._apps:
            s = _score(query, app.name)
            if s > 0.35:
                hits.append(AppInfo(app.name, app.target, app.kind, app.icon, round(s, 3)))
        hits.sort(key=lambda a: -a.score)
        return hits[:limit]


class WindowsAppLauncher:
    """Implementa `AppLauncher`. Todo lanzamiento pasa por la politica."""

    def __init__(self, policy: Policy):
        self.policy = policy
        self.last_error = ""

    def launch(self, app: AppInfo, args: list[str] | None = None) -> bool:
        decision = self.policy.can_launch(app.target)
        if not decision.allowed:
            self.last_error = decision.reason
            return False

        self.last_error = ""
        try:
            if app.kind in ("uri", "shortcut"):
                # os.startfile respeta el shell: abre .lnk y URIs correctamente
                os.startfile(app.target)  # noqa: S606
                return True
            cmd = [app.target, *(args or [])]
            subprocess.Popen(cmd, shell=False,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except OSError as exc:
            # ultimo recurso: dejar que el shell resuelva el nombre
            try:
                os.startfile(app.target)  # noqa: S606
                return True
            except OSError:
                self.last_error = str(exc)[:160]
                return False
