"""Push-to-talk. Manten la barra y habla.

Listener global de teclado (hilo aparte) + captura de audio en RAM.
El buffer nunca toca el disco salvo que lo pidas explicitamente.
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
        self.key_name = cfg.get("voice.ptt.key", "space")
        self.mode = cfg.get("voice.ptt.mode", "hold")
        self.min_dur = float(cfg.get("voice.ptt.min_duration_s", 0.35))
        self.max_dur = float(cfg.get("voice.ptt.max_duration_s", 60.0))
        self.rate = int(cfg.get("voice.stt.sample_rate", 16000))

        self.recording = False
        self.enabled = True
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

    # -- ciclo de vida -------------------------------------------------
    def start(self) -> None:
        from pynput import keyboard

        target = self._resolve_key(keyboard)

        def on_press(key):
            if not self.enabled or self.recording:
                return
            if self._is(key, target):
                if self.mode == "toggle" and self.recording:
                    return
                self._begin()

        def on_release(key):
            if self._is(key, target):
                if self.mode == "hold" and self.recording:
                    self._end()
                elif self.mode == "toggle":
                    self._end() if self.recording else self._begin()

        self._listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        self._listener.daemon = True
        self._listener.start()
        self.bus.emit_threadsafe("voice.ptt.ready", key=self.key_name, mode=self.mode)

    def stop(self) -> None:
        if self.recording:
            self._end()
        if self._listener:
            self._listener.stop()

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
