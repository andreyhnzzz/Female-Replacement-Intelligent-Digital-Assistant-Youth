"""Contexto de pantalla: que tiene el usuario delante.

Tres fuentes, de barata a cara. Se usa la primera que rinda:

  titles  ventana activa y titulos abiertos. Instantaneo, siempre disponible,
          y sorprendentemente informativo: los titulos suelen traer el
          nombre del archivo y del proyecto.
  uia     texto de los controles via Win32. Funciona en apps nativas.
  ocr     captura y reconocimiento. Solo si hay tesseract; es lo mas caro.

Nunca se captura sin que se pida. No hay vigilancia de fondo.
"""
from __future__ import annotations

import shutil
import subprocess
from typing import TYPE_CHECKING

from core.proc import NO_WINDOW
from system.ports import ScreenContext

if TYPE_CHECKING:
    from system.win32.windows import WindowsWindowReader

try:
    import win32gui
    HAVE_WIN32 = True
except ImportError:
    HAVE_WIN32 = False


class WindowsScreenReader:
    """Implementa `ScreenReaderPort`."""

    def __init__(self, windows: "WindowsWindowReader", allow_ocr: bool = False,
                 max_chars: int = 4000):
        self.windows = windows
        self.allow_ocr = allow_ocr
        self.max_chars = max_chars
        self._tesseract = shutil.which("tesseract") if allow_ocr else None

    # ── fuente 1: titulos ─────────────────────────────────────────
    def _titles(self) -> tuple[str, str, tuple[str, ...]]:
        active = self.windows.active()
        others = tuple(w.title for w in self.windows.list_windows()
                       if not active or w.handle != active.handle)[:12]
        return (active.title if active else "",
                active.process if active else "",
                others)

    # ── fuente 2: texto de controles nativos ──────────────────────
    def _control_text(self) -> str:
        if not HAVE_WIN32:
            return ""
        try:
            hwnd = win32gui.GetForegroundWindow()
            if not hwnd:
                return ""
        except Exception:
            return ""

        chunks: list[str] = []

        def walk(child: int, _acc) -> bool:
            try:
                txt = win32gui.GetWindowText(child)
                if txt and len(txt) > 1:
                    chunks.append(txt)
            except Exception:
                pass
            return len(chunks) < 120

        try:
            win32gui.EnumChildWindows(hwnd, walk, None)
        except Exception:
            pass

        seen, out = set(), []
        for c in chunks:
            if c not in seen:
                seen.add(c)
                out.append(c)
        return "\n".join(out)[: self.max_chars]

    # ── fuente 3: OCR (opcional y caro) ───────────────────────────
    def _ocr(self) -> str:
        if not self._tesseract:
            return ""
        tmp = None
        try:
            import tempfile
            from pathlib import Path

            import mss
            import mss.tools

            with mss.mss() as sct:
                shot = sct.grab(sct.monitors[1])
                tmp = Path(tempfile.gettempdir()) / "friday_screen.png"
                mss.tools.to_png(shot.rgb, shot.size, output=str(tmp))

            proc = subprocess.run(
                [self._tesseract, str(tmp), "stdout", "-l", "spa+eng"],
                capture_output=True, timeout=25, creationflags=NO_WINDOW)
            return proc.stdout.decode("utf-8", "replace")[: self.max_chars]
        except Exception:
            return ""
        finally:
            # Un timeout o un tesseract que revienta dejaba la captura
            # huerfana en el temp: no es basura cualquiera, es un pantallazo
            # del usuario. `finally` la borra pase lo que pase arriba.
            if tmp is not None:
                tmp.unlink(missing_ok=True)

    # ── puerto ────────────────────────────────────────────────────
    def context(self, with_text: bool = True) -> ScreenContext:
        title, process, others = self._titles()

        if not with_text:
            return ScreenContext(title, process, others, "", "titles")

        text = self._control_text()
        source = "uia" if text else "titles"

        if not text and self.allow_ocr:
            text = self._ocr()
            source = "ocr" if text else "titles"

        return ScreenContext(active_title=title, active_process=process,
                             windows=others, text=text, source=source)
