"""STT local. faster-whisper corriendo en tu CPU/GPU.

El audio entra como array de numpy y sale como texto. No hay cliente HTTP
en este archivo — a proposito. Si algun dia alguien mete uno, el guardia
de privacidad de core lo va a gritar.
"""
from __future__ import annotations

import time
from typing import Any

import numpy as np


class LocalSTT:
    """Envoltura sobre faster-whisper con carga perezosa del modelo."""

    def __init__(self, cfg):
        self.engine = cfg.get("voice.stt.engine", "faster_whisper")
        self.model_name = cfg.get("voice.stt.model", "small")
        self.device = cfg.get("voice.stt.device", "auto")
        self.compute = cfg.get("voice.stt.compute_type", "int8")
        self.language = cfg.get("voice.stt.language", "es")
        self.vad = bool(cfg.get("voice.stt.vad_filter", True))
        self.rate = int(cfg.get("voice.stt.sample_rate", 16000))
        self._model: Any = None
        self.ready = False
        self.info = ""

    # -- carga ---------------------------------------------------------
    def load(self) -> None:
        if self._model is not None:
            return
        if self.engine != "faster_whisper":
            raise NotImplementedError(f"STT '{self.engine}' no implementado todavia.")
        from faster_whisper import WhisperModel

        device = self.device
        if device == "auto":
            device = "cuda" if self._has_cuda() else "cpu"
        compute = self.compute if device == "cpu" else "float16"
        t0 = time.time()
        self._model = WhisperModel(self.model_name, device=device, compute_type=compute)
        self.ready = True
        self.info = f"{self.model_name}/{device}/{compute} ({time.time() - t0:.1f}s)"

    @staticmethod
    def _has_cuda() -> bool:
        try:
            import ctranslate2
            return ctranslate2.get_cuda_device_count() > 0
        except Exception:
            return False

    # -- transcripcion --------------------------------------------------
    def transcribe(self, audio: np.ndarray) -> dict[str, Any]:
        if not self.ready:
            self.load()
        audio = np.asarray(audio, dtype=np.float32).reshape(-1)
        peak = float(np.max(np.abs(audio))) if audio.size else 0.0
        if peak > 0:
            audio = audio / max(peak, 1e-6) * 0.95   # normaliza, ayuda al modelo

        t0 = time.time()
        segments, info = self._model.transcribe(
            audio,
            language=self.language or None,
            vad_filter=self.vad,
            vad_parameters={"min_silence_duration_ms": 400} if self.vad else None,
            beam_size=5,
            condition_on_previous_text=False,
        )
        parts, conf = [], []
        for seg in segments:
            parts.append(seg.text.strip())
            conf.append(getattr(seg, "avg_logprob", -1.0))

        text = " ".join(p for p in parts if p).strip()
        return {
            "text": text,
            "language": getattr(info, "language", self.language),
            "confidence": round(float(np.exp(np.mean(conf))) if conf else 0.0, 3),
            "ms": int((time.time() - t0) * 1000),
            "audio_s": round(audio.size / self.rate, 2),
            "peak": round(peak, 3),
        }
