"""Desenfoque de fondo nativo de Windows 11 (acrilico / mica).

El glassmorphism de verdad necesita desenfocar lo que hay DETRAS de la
ventana, y eso solo lo puede hacer el compositor del sistema. Qt no lo hace
por su cuenta: una ventana translucida sin desenfoque deja leer el
escritorio a traves del texto.

Es opcional (`[desktop] backdrop`) porque tiene un costo: el efecto cubre
toda la ventana, asi que el orbe pierde el fondo totalmente transparente y
deja de verse flotando. Con `none` el orbe flota; con `acrylic` el panel se
ve como cristal real. Es una eleccion estetica, no una carencia tecnica.
"""
from __future__ import annotations

import sys

# DwmSetWindowAttribute
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_SYSTEMBACKDROP_TYPE = 38

BACKDROPS = {
    "none": 1,      # automatico (sin efecto en ventanas sin marco)
    "mica": 2,
    "acrylic": 3,
    "tabbed": 4,
}


def apply(win_id: int, kind: str = "none", dark: bool = True) -> tuple[bool, str]:
    """Aplica el efecto a un HWND. Devuelve (ok, detalle)."""
    if sys.platform != "win32":
        return False, "solo Windows"
    if kind not in BACKDROPS:
        return False, f"desconocido: {kind}"
    if kind == "none":
        return True, "sin efecto de fondo"

    try:
        import ctypes
        from ctypes import wintypes

        dwm = ctypes.windll.dwmapi
        hwnd = wintypes.HWND(int(win_id))

        if dark:
            val = ctypes.c_int(1)
            dwm.DwmSetWindowAttribute(hwnd, ctypes.c_uint(DWMWA_USE_IMMERSIVE_DARK_MODE),
                                      ctypes.byref(val), ctypes.sizeof(val))

        val = ctypes.c_int(BACKDROPS[kind])
        res = dwm.DwmSetWindowAttribute(hwnd, ctypes.c_uint(DWMWA_SYSTEMBACKDROP_TYPE),
                                        ctypes.byref(val), ctypes.sizeof(val))
        if res != 0:
            return False, (f"DWM rechazo el efecto (0x{res & 0xFFFFFFFF:08X}); "
                           "requiere Windows 11 22H2 o superior")
        return True, kind
    except Exception as exc:
        return False, str(exc)[:120]
