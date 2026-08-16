"""Lectura y control de ventanas en Windows.

Separado en dos clases a proposito (segregacion de interfaces): saber que
hay abierto no requiere poder manipularlo.
"""
from __future__ import annotations

from system.ports import WindowInfo

try:
    import win32con
    import win32gui
    import win32process
    HAVE_WIN32 = True
except ImportError:
    HAVE_WIN32 = False

try:
    import psutil
except ImportError:
    psutil = None

# Ventanas de sistema que no le interesan a nadie
_NOISE = {"Program Manager", "Windows Input Experience", "Microsoft Text Input Application",
          "Настройки", "Setup", ""}


def _process_name(pid: int) -> str:
    if psutil is None or not pid:
        return ""
    try:
        return psutil.Process(pid).name()
    except Exception:
        return ""


class WindowsWindowReader:
    """Implementa `WindowReader`."""

    def list_windows(self) -> list[WindowInfo]:
        if not HAVE_WIN32:
            return []
        out: list[WindowInfo] = []

        def cb(hwnd: int, _acc) -> bool:
            if not win32gui.IsWindowVisible(hwnd):
                return True
            title = win32gui.GetWindowText(hwnd)
            if not title or title in _NOISE:
                return True
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                rect = win32gui.GetWindowRect(hwnd)
                minimized = bool(win32gui.IsIconic(hwnd))
            except Exception:
                pid, rect, minimized = 0, (0, 0, 0, 0), False
            out.append(WindowInfo(handle=hwnd, title=title, process=_process_name(pid),
                                  pid=pid, rect=rect, minimized=minimized))
            return True

        try:
            win32gui.EnumWindows(cb, None)
        except Exception:
            return out
        return out

    def active(self) -> WindowInfo | None:
        if not HAVE_WIN32:
            return None
        try:
            hwnd = win32gui.GetForegroundWindow()
            if not hwnd:
                return None
            title = win32gui.GetWindowText(hwnd)
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            return WindowInfo(handle=hwnd, title=title, process=_process_name(pid),
                              pid=pid, rect=win32gui.GetWindowRect(hwnd))
        except Exception:
            return None


class WindowsWindowController:
    """Implementa `WindowController`."""

    def focus(self, handle: int) -> bool:
        if not HAVE_WIN32:
            return False
        try:
            if win32gui.IsIconic(handle):
                win32gui.ShowWindow(handle, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(handle)
            return True
        except Exception:
            # Windows bloquea SetForegroundWindow desde procesos sin foco;
            # el flash de la barra de tareas es el respaldo honesto.
            try:
                win32gui.FlashWindow(handle, True)
            except Exception:
                pass
            return False

    def minimize(self, handle: int) -> bool:
        if not HAVE_WIN32:
            return False
        try:
            win32gui.ShowWindow(handle, win32con.SW_MINIMIZE)
            return True
        except Exception:
            return False
