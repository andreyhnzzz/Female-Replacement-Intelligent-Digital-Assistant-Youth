"""STT local. faster-whisper corriendo en tu CPU/GPU.

El audio entra como array de numpy y sale como texto. No hay cliente HTTP
en este archivo — a proposito. Si algun dia alguien mete uno, el guardia
de privacidad de core lo va a gritar.
"""
from __future__ import annotations

import os
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
        self.on_error: Any = None
        self._en_cpu = False

    # -- carga ---------------------------------------------------------
    def load(self, allow_download: bool = False) -> None:
        """Carga el modelo. Por defecto, **estrictamente offline**.

        Aunque el modelo ya este en cache, huggingface_hub sale a la red a
        validar la revision; con el candado de privacidad activo eso aborta
        la carga entera y te quedas sin voz. `local_files_only` le dice que
        use lo que hay en disco y no le pregunte a nadie.

        Solo `--allow-model-download` abre la red, y solo esa vez.
        """
        if self._model is not None:
            return
        if self.engine != "faster_whisper":
            raise NotImplementedError(f"STT '{self.engine}' no implementado todavia.")

        if not allow_download:
            # cinturon y tirantes: hay rutas de HF que ignoran local_files_only
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

        from faster_whisper import WhisperModel

        device = self.device
        if device == "auto":
            device = "cuda" if self._has_cuda() else "cpu"
        compute = self.compute if device == "cpu" else "float16"
        t0 = time.time()
        self._model = WhisperModel(self.model_name, device=device,
                                   compute_type=compute,
                                   local_files_only=not allow_download)
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

        try:
            return self._run(audio, peak)
        except Exception as exc:
            if not self._cuda_inservible(exc):
                raise
            self._rescatar_en_cpu(exc)
            return self._run(audio, peak)

    def _cuda_inservible(self, exc: Exception) -> bool:
        """¿El fallo es que CUDA no se puede usar de verdad?

        CTranslate2 carga cuBLAS/cuDNN en la PRIMERA transcripcion, no al
        construir el modelo. Por eso `load()` anuncia «cuda» tan tranquilo,
        el PTT se arma, y la voz muere justo cuando hablas: contar GPUs
        (`_has_cuda`) ve la tarjeta pero no ve que falte una DLL del runtime.
        """
        if self._en_cpu or "/cuda/" not in self.info:
            return False
        m = str(exc).lower()
        return any(s in m for s in ("cublas", "cudnn", "cuda", "library"))

    def _rescatar_en_cpu(self, exc: Exception) -> None:
        """Rehace el modelo en CPU y lo cuenta. Sorda no se queda."""
        from faster_whisper import WhisperModel

        previo = self.info
        # `local_files_only` no es opcional: esto corre dentro de
        # `privacy.sealed()`, asi que salir a la red aborta la transcripcion.
        self._model = WhisperModel(self.model_name, device="cpu",
                                   compute_type=self.compute,
                                   local_files_only=True)
        self._en_cpu = True
        self.info = f"{self.model_name}/cpu/{self.compute} (rescate)"
        self._aviso(f"CUDA no es utilizable ({exc}); STT continua en CPU "
                    f"el resto de la sesion. Venia de {previo}.")

    def _aviso(self, texto: str) -> None:
        """Una degradacion de la voz, contada donde se pueda leer."""
        if self.on_error is None:
            return
        try:
            self.on_error(texto)
        except Exception:
            pass                          # no vamos a perder la voz por el log

    def _run(self, audio: np.ndarray, peak: float) -> dict[str, Any]:
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
