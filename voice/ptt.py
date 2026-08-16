"""Push-to-talk. Pulsa F9 y habla.

Listener global de teclado (hilo aparte) + captura de audio en RAM.
El buffer nunca toca el disco salvo que lo pidas explicitamente.

Dos modos, y la diferencia esta en donde vive la decision:

  hold    la tecla ES el microfono. Bajar abre, soltar cierra. A prueba de
          errores: si sueltas, se acabo.
  toggle  la tecla es un interruptor. Pulsar abre, pulsar cierra. Toda la
          logica vive en `on_press` — repartirla entre press y release
          hace que la primera pulsacion abra y cierre en el mismo gesto.

El teclado repite `on_press` mientras la tecla sigue abajo, asi que hace
falta recordar el flanco: sin eso, mantener F9 medio segundo en modo toggle
abre y cierra el microfono treinta veces.
"""
from __future__ import annotations

import queue
import threading
import time
from typing import Any, Callable

import numpy as np

from core.bus import Bus


class PushToTalk:
    def __init__(self, cfg, bus: Bus):
        self.bus = bus
        self.cfg = cfg
        self.key_name = cfg.get("voice.ptt.key", "space")
        self.mode = cfg.get("voice.ptt.mode", "hold")
        self.min_dur = float(cfg.get("voice.ptt.min_duration_s", 0.35))
        self.max_dur = float(cfg.get("voice.ptt.max_duration_s", 60.0))
        self.rate = int(cfg.get("voice.stt.sample_rate", 16000))

        self.recording = False
        self.enabled = True
        self._held = False               # flanco de la tecla, no estado del micro
        self._frames: list[np.ndarray] = []
        self._q: queue.Queue[np.ndarray] = queue.Queue()
        self._stream: Any = None
        self._t0 = 0.0
        self._level = 0.0
        self._listener: Any = None
        self.on_utterance: Callable[[np.ndarray, float], None] | None = None

    # -- nivel para el HUD --------------------------------------------
    @property
    def level(self) -> float:
        return round(self._level, 4)

    @property
    def hint(self) -> str:
        """Como se le dice al usuario que hable. Lo consume el acompanante."""
        return self.cfg.ptt_hint()

    # -- ciclo de vida -------------------------------------------------
    def start(self) -> None:
        from pynput import keyboard

        target = self._resolve_key(keyboard)

        def on_press(key):
            if self._is(key, target):
                self.key_down()

        def on_release(key):
            if self._is(key, target):
                self.key_up()

        self._listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        self._listener.daemon = True
        self._listener.start()
        self.bus.emit_threadsafe("voice.ptt.ready", key=self.key_name,
                                 mode=self.mode, hint=self.hint)

    def stop(self) -> None:
        if self.recording:
            self._end()
        if self._listener:
            self._listener.stop()

    # -- maquina de estados de la tecla --------------------------------
    # Separada del listener a proposito: es la parte con reglas y por tanto
    # la parte que puede equivocarse. Aqui se puede probar sin teclado, sin
    # microfono y sin pynput instalado.
    def key_down(self) -> None:
        if self._held:                   # auto-repeticion: no es una pulsacion nueva
            return
        self._held = True
        if not self.enabled:
            return
        if self.mode == "toggle":
            self._end() if self.recording else self._begin()
        elif not self.recording:
            self._begin()

    def key_up(self) -> None:
        self._held = False
        # En toggle, soltar no significa nada: el microfono sigue abierto
        # hasta la siguiente pulsacion o hasta `max_duration_s`.
        if self.mode == "hold" and self.recording:
            self._end()

    # -- grabacion -----------------------------------------------------
    def _begin(self) -> None:
        import sounddevice as sd

        self._frames.clear()
        self.recording = True
        self._t0 = time.time()

        def cb(indata, frames, time_info, status):
            if status:
                pass  # xruns: no vale la pena tumbar la captura
            chunk = indata.copy().reshape(-1)
            self._frames.append(chunk)
            self._level = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))
            if time.time() - self._t0 > self.max_dur:
                threading.Thread(target=self._end, daemon=True).start()

        self._stream = sd.InputStream(samplerate=self.rate, channels=1,
                                      dtype="float32", callback=cb, blocksize=1024)
        self._stream.start()
        self.bus.emit_threadsafe("voice.ptt.down", rate=self.rate)

    def _end(self) -> None:
        if not self.recording:
            return
        self.recording = False
        dur = time.time() - self._t0
        try:
            if self._stream:
                self._stream.stop()
                self._stream.close()
        except Exception:
            pass
        self._stream = None
        self._level = 0.0

        audio = np.concatenate(self._frames) if self._frames else np.zeros(0, dtype=np.float32)
        self._frames.clear()
        self.bus.emit_threadsafe("voice.ptt.up", duration=round(dur, 2),
                                 samples=int(audio.size))

        if dur < self.min_dur or audio.size < self.rate * self.min_dur:
            self.bus.emit_threadsafe("voice.ptt.discard", duration=round(dur, 2))
            return
        if self.on_utterance:
            threading.Thread(target=self.on_utterance, args=(audio, dur), daemon=True).start()

    # -- teclas --------------------------------------------------------
    def _resolve_key(self, keyboard):
        name = self.key_name.lower().strip()
        special = getattr(keyboard.Key, name, None)
        if special is not None:
            return special
        return keyboard.KeyCode.from_char(name[0])

    @staticmethod
    def _is(key, target) -> bool:
        if key == target:
            return True
        return getattr(key, "char", None) is not None and \
            getattr(target, "char", None) == key.char
