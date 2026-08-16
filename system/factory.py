"""Fabrica de acceso al sistema.

El unico lugar del proyecto que sabe en que sistema operativo corre.
Todo lo demas habla con los Protocol de `ports.py`.

Si una capacidad no esta disponible queda en None: las skills lo detectan y
lo reportan, en vez de reventar a media peticion.
"""
from __future__ import annotations

import sys
from typing import Any

from core.policy import Policy
from system.files import LocalFileIndex, LocalFileOrganizer
from system.news import RssNewsReader
from system.pages import HttpPageReader
from system.ports import SystemAccess
from system.web import BrowserWebOpener


def build_system_access(cfg: Any, policy: Policy) -> SystemAccess:
    access = SystemAccess()

    # ── multiplataforma ───────────────────────────────────────────
    index = LocalFileIndex(policy, max_scan=int(cfg.get("system.max_scan", 40000)))
    access.files = index
    access.organizer = LocalFileOrganizer(policy, index)
    access.web = BrowserWebOpener(policy, cfg.get("system.search_engine", "default"))

    # ── red saliente ──────────────────────────────────────────────
    # Se construyen siempre, pero cada peticion pasa por `can_fetch`: con
    # `allow_web_fetch = false` el puerto existe y responde «denegado», que
    # es mas util que un None indistinguible de «esta plataforma no puede».
    contact = str(cfg.get("system.contact", "") or "")
    access.news = RssNewsReader(
        policy,
        sources=cfg.get("news.sources") or None,
        timeout_s=float(cfg.get("news.timeout_s", 10)),
        per_source=int(cfg.get("news.per_source", 8)),
        contact=contact,
    )
    access.pages = HttpPageReader(
        policy,
        max_chars=int(cfg.get("system.page_max_chars", 12000)),
        timeout_s=float(cfg.get("system.fetch_timeout_s", 12)),
        lang=str(cfg.get("identity.language", "es")),
        contact=contact,
    )

    # ── especifico de plataforma ──────────────────────────────────
    if sys.platform == "win32":
        _wire_windows(cfg, policy, access)

    return access


def _wire_windows(cfg: Any, policy: Policy, access: SystemAccess) -> None:
    try:
        from system.win32.apps import WindowsAppCatalog, WindowsAppLauncher
        access.apps = WindowsAppCatalog(ttl_s=float(cfg.get("system.app_cache_s", 120)))
        access.launcher = WindowsAppLauncher(policy)
    except ImportError:
        pass

    try:
        from system.win32.windows import WindowsWindowController, WindowsWindowReader
        reader = WindowsWindowReader()
        access.windows = reader
        access.window_ctl = WindowsWindowController()
    except ImportError:
        reader = None

    if reader is not None:
        try:
            from system.win32.screen import WindowsScreenReader
            access.screen = WindowsScreenReader(
                reader,
                allow_ocr=bool(cfg.get("system.allow_ocr", False)),
                max_chars=int(cfg.get("system.screen_max_chars", 4000)),
            )
        except ImportError:
            pass
