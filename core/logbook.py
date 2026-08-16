"""Bitacora del bus.

Algo que corre todo el dia en segundo plano necesita dejar rastro. Sin esto,
cuando el push-to-talk no responde no hay forma de saber si el modelo no
cargo, si el hotkey no armo o si el microfono no abrio.

Se suscribe al bus y escribe una linea por evento. No decide nada, no
transforma nada: observa.
"""
from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from .bus import Bus, Event

# Eventos de alta frecuencia que ahogarian el archivo
_NOISY = {"voice.level", "core.tick"}


class Logbook:
    def __init__(self, bus: Bus, path: Path | str, echo: bool = False,
                 max_bytes: int = 2_000_000):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.echo = echo
        self.max_bytes = max_bytes
        self._rotate_if_big()
        bus.on("*", self._write)
        self.line(f"=== sesion iniciada {datetime.now():%Y-%m-%d %H:%M:%S} ===")

    def _rotate_if_big(self) -> None:
        try:
            if self.path.exists() and self.path.stat().st_size > self.max_bytes:
                self.path.replace(self.path.with_suffix(".1.log"))
        except OSError:
            pass

    def line(self, text: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        try:
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(f"{stamp}  {text}\n")
        except OSError:
            pass
        if self.echo:
            print(f"  {stamp}  {text}", flush=True)

    async def _write(self, ev: Event) -> None:
        if ev.topic in _NOISY:
            return
        bits = []
        for k, v in ev.data.items():
            if k.startswith("_"):
                continue
            s = str(v).replace("\n", " ")
            bits.append(f"{k}={s[:110]}")
        self.line(f"[{ev.topic}] " + " ".join(bits))
