"""TTS local. La boca de FRIDAY.

Prioridad:
  1. Piper  — ONNX offline, voz natural, multiplataforma.
  2. SAPI5  — voces de Windows, por COM directo. Tambien 100% local.
Ninguna de las dos manda audio a ningun lado.

**Todo lo que toca COM vive en el hilo `tts` y no sale de ahi.** SAPI5 tiene
afinidad de apartamento: crearlo en un hilo y usarlo en otro no da error, da
un cuelgue permanente en `runAndWait()`. De ahi tres rodeos que no lo son:

- `load()` solo detecta; el objeto de voz se crea dentro del worker.
- `shutup()` no llama a COM: levanta un evento y purga el worker.
- Se habla en modo asincrono con un bucle de `WaitUntilDone`, que es lo que
  permite cortar a mitad de frase sin tocar el objeto desde fuera.

`comtypes` directo y no `pyttsx3`: este cachea el motor en un dict global del
modulo y su `runAndWait()` vuelve antes de que acabe el audio, asi que cada
frase cortaba a la anterior.
"""
from __future__ import annotations

import queue
import re
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any

# Banderas de ISpVoice::Speak
SVSF_ASYNC = 1          # vuelve enseguida; se espera con WaitUntilDone
SVSF_PURGE = 2          # descarta lo que estuviera sonando

_VOZ_ES = ("spanish", "espa", "es-", "es_", "helena", "sabina", "raul", "laura")


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
        self._sapi: Any = None            # se crea DENTRO del worker
        self._q: queue.Queue[str | None] = queue.Queue()
        self._worker: threading.Thread | None = None
        self._stop = threading.Event()
        self._cut = threading.Event()     # «calla»: lo atiende el worker
        self._idle = threading.Event()    # sin cola y sin hablar
        self._ready = threading.Event()   # el worker ya tiene voz utilizable
        self._idle.set()

    # ══════════════════════════════ deteccion (sin construir nada)
    def load(self) -> None:
        """Decide QUE backend se usara. No instancia el motor de voz.

        Puede correr en cualquier hilo justamente porque no toca COM.
        """
        if self.engine == "none":
            self.backend, self.info = "none", "silenciado por config"
            return
        if self.engine == "piper" and self._load_piper():
            return
        if self._detect_sapi():
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

    def _detect_sapi(self) -> bool:
        """¿Hay SAPI en esta maquina? Se comprueba importando, no creando."""
        try:
            import comtypes.client  # noqa: F401
            import pythoncom  # noqa: F401
        except ImportError:
            return False
        self.backend = "sapi5"
        self.info = "voz del sistema"      # el nombre real lo pone el worker
        return True

    # ══════════════════════════════ ciclo de vida
    def start(self, wait_s: float = 6.0) -> None:
        if not self.backend or self.backend == "none":
            self.load()
        self._worker = threading.Thread(target=self._run, daemon=True, name="tts")
        self._worker.start()
        # Se espera a que el worker tenga voz para que `info` sea el nombre de
        # verdad y no «voz del sistema» en la bitacora de arranque.
        if self.backend == "sapi5":
            self._ready.wait(timeout=wait_s)

    def say(self, text: str) -> None:
        text = self.clean(text)
        if text and not self.muted:
            self._idle.clear()
            self._q.put(text)

    def shutup(self) -> None:
        """Vacia la cola y corta la frase en curso.

        No toca el objeto de voz: solo deja la señal. Purgar COM desde este
        hilo es precisamente el fallo que este archivo existe para no repetir.
        """
        while not self._q.empty():
            try:
                self._q.get_nowait()
            except queue.Empty:
                break
        self._cut.set()
        # Si se corta antes de que el worker recogiera nada, no queda quien
        # marque el reposo: `wait_until_idle` se colgaria hasta el timeout y
        # con el, la respuesta entera.
        if not self.speaking:
            self._idle.set()

    def stop(self) -> None:
        self._stop.set()
        self._cut.set()
        self._q.put(None)

    def wait_until_idle(self, timeout: float = 60.0) -> bool:
        """Bloquea hasta que se acabe de hablar. Lo usa el orquestador para
        que el HUD muestre «hablando» durante la voz real y no un parpadeo."""
        return self._idle.wait(timeout=timeout)

    # ══════════════════════════════ el worker: dueño unico de la voz
    def _run(self) -> None:
        com = None
        if self.backend == "sapi5":
            try:
                import pythoncom
                pythoncom.CoInitialize()
                com = pythoncom
                self._sapi = self._build_sapi()
            except Exception as exc:
                print(f"[tts] SAPI no arranco: {exc!r}")
                self.backend = "none"
            finally:
                self._ready.set()

        try:
            while not self._stop.is_set():
                item = self._q.get()
                if item is None:
                    break
                self.speaking = True
                self._cut.clear()
                try:
                    self._speak(item)
                except Exception as exc:
                    print(f"[tts] fallo: {exc!r}")
                    self._recover()
                finally:
                    self.speaking = False
                    if self._q.empty():
                        self._idle.set()
        finally:
            self._sapi = None
            if com is not None:
                try:
                    com.CoUninitialize()
                except Exception:
                    pass
            self._idle.set()

    def _build_sapi(self):
        import comtypes.client

        voz = comtypes.client.CreateObject("SAPI.SpVoice")
        for token in voz.GetVoices():
            try:
                desc = token.GetDescription()
            except Exception:
                continue
            if any(k in desc.lower() for k in _VOZ_ES):
                voz.Voice = token
                self.info = desc
                break
        else:
            self.info = "voz por defecto"

        # Rate va de -10 a 10 con 0 = normal; volumen de 0 a 100.
        voz.Rate = max(-10, min(10, round((self.speed - 1.0) * 10)))
        voz.Volume = max(0, min(100, round(self.volume * 100)))
        return voz

    def _recover(self) -> None:
        """Un fallo no puede dejar a FRIDAY muda el resto de la sesion."""
        if self.backend != "sapi5":
            return
        try:
            self._sapi = self._build_sapi()
        except Exception as exc:
            print(f"[tts] no pude recuperar la voz: {exc!r}")
            self._sapi = None

    # ══════════════════════════════ sintesis
    def _speak(self, text: str) -> None:
        if self.backend == "piper":
            self._speak_piper(text)
        elif self.backend == "piper-cli":
            self._speak_piper_cli(text)
        elif self.backend == "sapi5":
            self._speak_sapi(text)

    def _speak_sapi(self, text: str) -> None:
        if self._sapi is None:
            self._recover()
            if self._sapi is None:
                return
        self._sapi.Speak(text, SVSF_ASYNC)
        # Bucle en vez de llamada sincrona: es lo que hace la voz
        # interrumpible sin tocar el objeto desde otro hilo.
        while not self._sapi.WaitUntilDone(80):
            if self._cut.is_set() or self._stop.is_set():
                self._sapi.Speak("", SVSF_PURGE)
                break

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
        self._wait_playback(sd)

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
            self._wait_playback(sd)
        finally:
            wav.unlink(missing_ok=True)

    def _wait_playback(self, sd) -> None:
        """`sd.wait()` no se puede interrumpir; este bucle si."""
        while sd.get_stream().active:
            if self._cut.is_set() or self._stop.is_set():
                sd.stop()
                return
            threading.Event().wait(0.05)

    # ══════════════════════════════ limpieza de texto
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
