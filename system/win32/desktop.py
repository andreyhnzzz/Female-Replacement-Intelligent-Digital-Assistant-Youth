"""Control de escritorio en Windows: volumen, reproduccion, sesion, portapapeles.

Implementa `MediaControl`, `SessionControl` y `Clipboard`. Ninguna skill
importa este archivo: hablan con los Protocol de `system/ports.py`.

Se usan las **teclas multimedia virtuales** en vez de la API de audio
(IAudioEndpointVolume por COM). Es una decision, no una limitacion:

- Las teclas las respeta cualquier reproductor —Spotify, el navegador, VLC—
  porque es el mismo evento que manda un teclado con teclas de medios. Ir por
  COM controlaria el volumen maestro pero no pausaria nada.
- No arrastra un objeto COM con afinidad de apartamento. Ya nos costo una
  sesion entera de voz muda en `voice/tts.py`; no hay motivo para repetir el
  patron por subir el volumen dos rayas.

El precio es que el volumen se mueve en pasos de ~2% (lo que hace Windows por
pulsacion) y no se puede leer el nivel actual. Se devuelve el numero de pasos
aplicados, no un porcentaje inventado.
"""
from __future__ import annotations

import ctypes
import time

import win32api
import win32con

from core.policy import Policy

# Un paso de tecla de volumen mueve ~2 puntos porcentuales en Windows.
_PASO_VOLUMEN = 2

# `win32con` no expone VK_MEDIA_STOP aunque si trae las otras tres, asi que
# se toma de ahi cuando existe y se cae al codigo virtual de Windows si no.
_MEDIA = {
    "play_pause": getattr(win32con, "VK_MEDIA_PLAY_PAUSE", 0xB3),
    "next": getattr(win32con, "VK_MEDIA_NEXT_TRACK", 0xB0),
    "prev": getattr(win32con, "VK_MEDIA_PREV_TRACK", 0xB1),
    "stop": getattr(win32con, "VK_MEDIA_STOP", 0xB2),
}


def _tecla(vk: int, veces: int = 1) -> None:
    """Pulsa una tecla virtual. KEYEVENTF_KEYUP para soltarla de verdad:
    sin el evento de subida el sistema la trata como mantenida."""
    for _ in range(max(1, veces)):
        win32api.keybd_event(vk, 0, 0, 0)
        win32api.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(0.01)


class WindowsMediaControl:
    """Implementa `MediaControl`."""

    def __init__(self, policy: Policy):
        self.policy = policy
        self.last_error = ""

    def _permiso(self, que: str) -> bool:
        decision = self.policy.can_control(que)
        self.last_error = "" if decision.allowed else decision.reason
        return decision.allowed

    def volume(self, delta: int) -> int:
        """Sube o baja. `delta` en puntos porcentuales; devuelve los aplicados."""
        if not self._permiso("media"):
            return 0
        pasos = max(1, round(abs(delta) / _PASO_VOLUMEN))
        _tecla(win32con.VK_VOLUME_UP if delta > 0 else win32con.VK_VOLUME_DOWN, pasos)
        return pasos * _PASO_VOLUMEN * (1 if delta > 0 else -1)

    def set_volume(self, level: int) -> int:
        """Nivel absoluto 0-100.

        Sin leer el estado actual no hay forma de saltar directo a un valor,
        asi que se baja a cero —50 pasos cubren cualquier nivel— y se sube lo
        pedido. Es visible como un barrido rapido; es el precio de no meter
        COM aqui.
        """
        if not self._permiso("media"):
            return 0
        level = max(0, min(100, int(level)))
        _tecla(win32con.VK_VOLUME_DOWN, 50)
        if level:
            _tecla(win32con.VK_VOLUME_UP, round(level / _PASO_VOLUMEN))
        return level

    def mute(self) -> bool:
        if not self._permiso("media"):
            return False
        _tecla(win32con.VK_VOLUME_MUTE)
        return True

    def playback(self, action: str) -> bool:
        vk = _MEDIA.get((action or "").strip().lower())
        if vk is None:
            self.last_error = f"accion de reproduccion desconocida: {action}"
            return False
        if not self._permiso("media"):
            return False
        _tecla(vk)
        return True


class WindowsSessionControl:
    """Implementa `SessionControl`."""

    def __init__(self, policy: Policy):
        self.policy = policy
        self.last_error = ""

    def _permiso(self) -> bool:
        decision = self.policy.can_control("session")
        self.last_error = "" if decision.allowed else decision.reason
        return decision.allowed

    def lock(self) -> bool:
        if not self._permiso():
            return False
        try:
            return bool(ctypes.windll.user32.LockWorkStation())
        except Exception as exc:
            self.last_error = str(exc)[:140]
            return False

    def sleep(self) -> bool:
        if not self._permiso():
            return False
        try:
            # (hibernar=False, forzar=False, deshabilitar_eventos_wake=False)
            # forzar=False deja que una app con trabajo sin guardar se niegue.
            return bool(ctypes.windll.powrprof.SetSuspendState(False, False, False))
        except Exception as exc:
            self.last_error = str(exc)[:140]
            return False


class WindowsClipboard:
    """Implementa `Clipboard`."""

    MAX = 100_000

    def __init__(self, policy: Policy):
        self.policy = policy
        self.last_error = ""

    def read(self) -> str:
        decision = self.policy.can_control("clipboard")
        if not decision.allowed:
            self.last_error = decision.reason
            return ""
        try:
            import win32clipboard
            win32clipboard.OpenClipboard()
            try:
                if not win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
                    return ""
                return str(win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT))[:self.MAX]
            finally:
                win32clipboard.CloseClipboard()
        except Exception as exc:
            self.last_error = str(exc)[:140]
            return ""

    def write(self, text: str) -> bool:
        decision = self.policy.can_control("clipboard")
        if not decision.allowed:
            self.last_error = decision.reason
            return False
        try:
            import win32clipboard
            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardText(str(text)[:self.MAX],
                                                win32clipboard.CF_UNICODETEXT)
                return True
            finally:
                win32clipboard.CloseClipboard()
        except Exception as exc:
            self.last_error = str(exc)[:140]
            return False
