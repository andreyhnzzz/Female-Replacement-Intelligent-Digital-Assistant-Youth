"""Dos candados de privacidad: el audio y lo que queda por escrito.

El primero: mientras STT o TTS procesan, este guardia intercepta
socket.connect y revienta cualquier intento de salir a una IP que no sea
loopback. Si un dia una dependencia intenta "telemetria", lo vas a ver en
el HUD, no en un blog seis meses despues.

El segundo: `redact()` tacha del texto lo que `[privacy] redact_in_logs`
declare antes de que llegue a la bitacora o a un aviso reenviado a un
tercero (`notify.mirror_say`). Sin esto, esa lista del toml es una promesa
sin cablear — cualquiera puede escribirla y nada la lee.
"""
from __future__ import annotations

import ipaddress
import re
import socket
import threading
from contextlib import contextmanager
from typing import Callable

_orig_connect = socket.socket.connect
_orig_connect_ex = socket.socket.connect_ex
_local = threading.local()
_installed = False
_reporter: Callable[[str], None] | None = None


class AudioLeak(RuntimeError):
    """El pipeline de audio intento salir a la red."""


def _is_loopback(addr) -> bool:
    try:
        host = addr[0] if isinstance(addr, tuple) else str(addr)
        if host in ("localhost", "::1", ""):
            return True
        return ipaddress.ip_address(host).is_loopback
    except (ValueError, IndexError, TypeError):
        return False   # sockets unix / lo que no reconozcamos: no lo permitimos


def install(reporter: Callable[[str], None] | None = None) -> None:
    global _installed, _reporter
    _reporter = reporter
    if _installed:
        return

    def guarded(self, address):
        if getattr(_local, "sealed", False) and not _is_loopback(address):
            msg = f"BLOQUEADO: el pipeline de audio intento conectar a {address}"
            if _reporter:
                _reporter(msg)
            raise AudioLeak(msg)
        return _orig_connect(self, address)

    def guarded_ex(self, address):
        if getattr(_local, "sealed", False) and not _is_loopback(address):
            if _reporter:
                _reporter(f"BLOQUEADO (connect_ex): {address}")
            return 1
        return _orig_connect_ex(self, address)

    socket.socket.connect = guarded          # type: ignore[method-assign]
    socket.socket.connect_ex = guarded_ex    # type: ignore[method-assign]
    _installed = True


def uninstall() -> None:
    global _installed
    socket.socket.connect = _orig_connect          # type: ignore[method-assign]
    socket.socket.connect_ex = _orig_connect_ex    # type: ignore[method-assign]
    _installed = False


@contextmanager
def sealed():
    """Dentro de este bloque, el hilo actual no puede salir del equipo."""
    prev = getattr(_local, "sealed", False)
    _local.sealed = True
    try:
        yield
    finally:
        _local.sealed = prev


def redact(text: str, patterns: list[str] | tuple[str, ...]) -> str:
    """Tacha cada patron de `patterns` en `text` por `[REDACTADO]`.

    Coincidencia literal (no regex) e insensible a mayusculas: la lista la
    escribe el usuario a mano en el toml, y una regex mal formada ahi no
    puede tumbar el logueo de cada evento del bus. Sin patrones o sin
    texto, devuelve tal cual — el caso comun (`redact_in_logs = []`) no
    paga ningun costo.
    """
    if not patterns or not text:
        return text
    out = text
    for pat in patterns:
        pat = str(pat).strip()
        if not pat:
            continue
        out = re.sub(re.escape(pat), "[REDACTADO]", out, flags=re.IGNORECASE)
    return out
