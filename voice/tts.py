"""TTS local. La boca de FRIDAY.

Prioridad:
  1. Piper  — ONNX offline, voz natural, multiplataforma.
  2. SAPI5  — voces de Windows. Tambien 100% local, cero descarga.
Ninguna de las dos manda audio a ningun lado.
"""
from __future__ import annotations

import queue
import re
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any


class LocalTTS:
    def __init__(self, cfg):
        self.engine = cfg.get("voice.tts.engine", "piper")
        self.voice = cfg.get("voice.tts.voice", "es_MX-claude-high")
        self.model_dir = cfg.path_of("voice.tts.model_dir", "models/piper")
        self.speed = float(cfg.get("voice.tts.speed", 1.0))
        self.volume = float(cfg.get("voice.tts.volume", 0.9))

        self.backend = "none"
        self.info = ""
        self.speaking = False
        self.muted = False
        self._piper: Any = None
        self._sapi: Any = None
        self._q: queue.Queue[str | None] = queue.Queue()
        self._worker: threading.Thread | None = None
        self._stop = threading.Event()

    # -- carga ---------------------------------------------------------
    def load(self) -> None:
        if self.engine == "none":
            self.backend, self.info = "none", "silenciado por config"
            return
        if self.engine == "piper" and self._load_piper():
            return
        if self._load_sapi():
            return
        self.backend, self.info = "none", "sin backend de voz disponible"

    def _load_piper(self) -> bool:
        model = self._find_model()
        if model is None:
            return False
        try:
            from piper.voice import PiperVoice
            self._piper = PiperVoice.load(str(model))
            self.backend = "piper"
            self.info = model.name
            return True
        except Exception:
            pass
        exe = shutil.which("piper") or shutil.which("piper.exe")
        if exe:
            self._piper = ("cli", exe, str(model))
            self.backend = "piper-cli"
            self.info = model.name
            return True
        return False

    def _find_model(self) -> Path | None:
        if not self.model_dir.exists():
            return None
        exact = self.model_dir / f"{self.voice}.onnx"
        if exact.exists():
            return exact
        found = sorted(self.model_dir.glob("*.onnx"))
        return found[0] if found else None

    def _load_sapi(self) -> bool:
        try:
            import pyttsx3
            eng = pyttsx3.init()
            eng.setProperty("rate", int(190 * self.speed))
            eng.setProperty("volume", self.volume)
            for v in eng.getProperty("voices"):
                blob = f"{v.id} {getattr(v, 'name', '')}".lower()
                if any(k in blob for k in ("spanish", "espa", "es-", "helena", "sabina", "raul")):
                    eng.setProperty("voice", v.id)
                    self.info = getattr(v, "name", v.id)
                    break
            self._sapi = eng
            self.backend = "sapi5"
            self.info = self.info or "voz por defecto"
            return True
        except Exception:
            return False

    # -- cola de habla --------------------------------------------------
    def start(self) -> None:
        if not self.backend or self.backend == "none":
            self.load()
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    def say(self, text: str) -> None:
        text = self.clean(text)
        if text and not self.muted:
            self._q.put(text)

    def shutup(self) -> None:
        """Vacia la cola. Corta a mitad de frase si hace falta."""
        while not self._q.empty():
            try:
                self._q.get_nowait()
            except queue.Empty:
                break
        if self.backend == "sapi5" and self._sapi:
            try:
                self._sapi.stop()
            except Exception:
                pass

    def stop(self) -> None:
        self._stop.set()
        self._q.put(None)

    # -- interno ---------------------------------------------------------
    def _run(self) -> None:
        while not self._stop.is_set():
            item = self._q.get()
            if item is None:
                break
            self.speaking = True
            try:
                self._speak(item)
            except Exception as exc:
                print(f"[tts] fallo: {exc!r}")
            finally:
                self.speaking = False

    def _speak(self, text: str) -> None:
        if self.backend == "piper":
            self._speak_piper(text)
        elif self.backend == "piper-cli":
            self._speak_piper_cli(text)
        elif self.backend == "sapi5":
            self._sapi.say(text)
            self._sapi.runAndWait()

    def _speak_piper(self, text: str) -> None:
        import numpy as np
        import sounddevice as sd

        rate = getattr(getattr(self._piper, "config", None), "sample_rate", 22050)
        chunks = []
        for audio in self._piper.synthesize_stream_raw(text):
            chunks.append(np.frombuffer(audio, dtype=np.int16))
        if not chunks:
            return
        pcm = np.concatenate(chunks).astype(np.float32) / 32768.0 * self.volume
        sd.play(pcm, rate)
        sd.wait()

    def _speak_piper_cli(self, text: str) -> None:
        _, exe, model = self._piper
        wav = Path(self.model_dir) / "_out.wav"
        subprocess.run([exe, "-m", model, "-f", str(wav)],
                       input=text.encode("utf-8"), check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            import soundfile as sf
            import sounddevice as sd
            data, rate = sf.read(str(wav), dtype="float32")
            sd.play(data * self.volume, rate)
            sd.wait()
        finally:
            wav.unlink(missing_ok=True)

    # -- limpieza de texto -------------------------------------------------
    @staticmethod
    def clean(text: str) -> str:
        """Markdown no se pronuncia. Se lee el contenido, no los asteriscos."""
        if not text:
            return ""
        t = re.sub(r"```.*?```", " ", text, flags=re.S)
        t = re.sub(r"`([^`]*)`", r"\1", t)
        # [[Nota|alias]] se lee como el alias: es lo que el ojo veria
        t = re.sub(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]",
                   lambda m: (m.group(2) or m.group(1)).strip(), t)
        t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)
        t = re.sub(r"^\s{0,3}#{1,6}\s*", "", t, flags=re.M)
        t = re.sub(r"[*_>#|]+", " ", t)
        t = re.sub(r"^\s*[-–—]\s*", "", t, flags=re.M)
        t = re.sub(r"\s+", " ", t)
        return t.strip()
