"""Candado de privacidad del audio.

No basta con decir "es local". Mientras STT o TTS procesan, este guardia
intercepta socket.connect y revienta cualquier intento de salir a una IP
que no sea loopback. Si un dia una dependencia intenta "telemetria",
lo vas a ver en el HUD, no en un blog seis meses despues.
"""
from __future__ import annotations

import ipaddress
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
