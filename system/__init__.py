"""Acceso al sistema operativo tras puertos abstractos.

Las skills dependen de `ports.py`, nunca de `win32/`. Ese es el punto.
"""
from .factory import build_system_access
from .ports import (
    AppInfo,
    FileInfo,
    FileOp,
    OpKind,
    OpResult,
    ScreenContext,
    SystemAccess,
    WindowInfo,
)

__all__ = [
    "build_system_access", "SystemAccess", "AppInfo", "WindowInfo",
    "FileInfo", "FileOp", "OpKind", "OpResult", "ScreenContext",
]
