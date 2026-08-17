"""Aplicaciones predeterminadas de Windows.

Que abre un `https://`, que abre un `mailto:`. Lo decide el usuario en
Configuracion y Windows lo guarda en el registro; aqui solo se lee.

Por que existe en vez de dejarselo a `webbrowser.open`: ese modulo abre el
predeterminado, si, pero no sabe **cual** es. Y FRIDAY tiene que poder
decir «te lo abro en Brave» en vez de «te lo abro en el navegador», que es
la diferencia entre un asistente y un `os.startfile` con voz. Ademas
`webbrowser` respeta la variable de entorno BROWSER, que puede apuntar a
cualquier cosa que el usuario nunca eligio.

Solo `winreg`, que es biblioteca estandar: ninguna dependencia nueva por
leer una clave.
"""
from __future__ import annotations

import os
import re
import shlex
import time
import winreg
from typing import Any

from system.ports import DefaultApp

# HKCU: la eleccion del usuario gana sobre el registro de la maquina.
_USER_CHOICE = (r"Software\Microsoft\Windows\Shell\Associations"
                r"\UrlAssociations\{scheme}\UserChoice")

# El ProgId es un identificador, no un nombre. «BraveHTML» no se dice en voz
# alta. Se traduce por el ejecutable, que es estable y corto.
_PRETTY: dict[str, str] = {
    "brave": "Brave",
    "chrome": "Google Chrome",
    "msedge": "Microsoft Edge",
    "firefox": "Firefox",
    "opera": "Opera",
    "opera_gx": "Opera GX",
    "vivaldi": "Vivaldi",
    "iexplore": "Internet Explorer",
    "zen": "Zen Browser",
    "arc": "Arc",
    "librewolf": "LibreWolf",
    "waterfox": "Waterfox",
}


def _read(root: int, path: str, value: str = "") -> str:
    try:
        with winreg.OpenKey(root, path) as key:
            data, _kind = winreg.QueryValueEx(key, value)
        return str(data)
    except OSError:
        return ""


def _exe_from_command(command: str) -> str:
    """Saca la ruta del ejecutable de una linea de comando del registro.

    Viene en formatos variados: entre comillas con argumentos detras
    (`"C:\\...\\brave.exe" --single-argument %1`), sin comillas, o con
    variables sin expandir. `shlex` con `posix=False` respeta las comillas
    de Windows sin comerse las barras invertidas.
    """
    command = os.path.expandvars(command.strip())
    if not command:
        return ""
    try:
        first = shlex.split(command, posix=False)[0]
    except ValueError:
        first = command.split(" ")[0]
    first = first.strip('"')
    if os.path.isfile(first):
        return first
    # sin comillas y con espacios en la ruta: cortar en el .exe
    m = re.match(r"(?i)^(.*?\.exe)\b", command.strip('"'))
    if m and os.path.isfile(m.group(1)):
        return m.group(1)
    return ""


def _pretty(exe: str, progid: str) -> str:
    stem = os.path.splitext(os.path.basename(exe))[0].lower() if exe else ""
    if stem in _PRETTY:
        return _PRETTY[stem]
    if stem:
        return stem.replace("_", " ").title()
    # sin ejecutable resuelto, el ProgId al menos identifica algo
    return re.sub(r"(HTML|URL|HTM)$", "", progid) or "el navegador"


class WindowsDefaultApps:
    """Implementa `DefaultApps` leyendo el registro de Windows.

    Se cachea: la eleccion de navegador no cambia entre dos frases, y cada
    consulta son tres aperturas de clave.
    """

    def __init__(self, ttl_s: float = 300.0):
        self.ttl = ttl_s
        self._cache: dict[str, tuple[float, DefaultApp | None]] = {}

    # ── consulta ──────────────────────────────────────────────────
    def for_scheme(self, scheme: str) -> DefaultApp | None:
        scheme = (scheme or "https").strip().lower().rstrip(":")
        hit = self._cache.get(scheme)
        if hit and (time.time() - hit[0]) < self.ttl:
            return hit[1]

        app = self._resolve(scheme)
        self._cache[scheme] = (time.time(), app)
        return app

    def browser(self) -> DefaultApp | None:
        return self.for_scheme("https")

    # ── resolucion ────────────────────────────────────────────────
    @staticmethod
    def _resolve(scheme: str) -> DefaultApp | None:
        progid = _read(winreg.HKEY_CURRENT_USER,
                       _USER_CHOICE.format(scheme=scheme), "ProgId")
        if not progid:
            # Sin eleccion explicita, la asociacion global del esquema.
            progid = _read(winreg.HKEY_CLASSES_ROOT, scheme, "")
        if not progid:
            return None

        command = _read(winreg.HKEY_CLASSES_ROOT,
                        rf"{progid}\shell\open\command")
        exe = _exe_from_command(command)
        return DefaultApp(name=_pretty(exe, progid), progid=progid,
                          command=command, path=exe)


def build_default_apps(cfg: Any) -> WindowsDefaultApps:
    return WindowsDefaultApps(ttl_s=float(cfg.get("system.defaults_cache_s", 300)))
