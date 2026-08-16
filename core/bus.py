"""Bus de eventos asincrono.

Todo en FRIDAY se comunica por aqui: PTT -> STT -> router -> skill -> TTS -> HUD.
Nadie importa a nadie. Por eso el sistema es modular de verdad.
"""
from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

Handler = Callable[["Event"], Awaitable[None]]


@dataclass
class Event:
    topic: str
    data: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    def as_json(self) -> dict[str, Any]:
        return {"topic": self.topic, "ts": self.ts, **self.data}


class Bus:
    """Pub/sub con comodines de un nivel: 'voice.*' escucha 'voice.stt.final'."""

    def __init__(self, history: int = 300):
        self._subs: dict[str, list[Handler]] = defaultdict(list)
        self._history: deque[Event] = deque(maxlen=history)
        self._loop: asyncio.AbstractEventLoop | None = None

    # -- suscripcion --------------------------------------------------
    def on(self, topic: str, handler: Handler) -> Handler:
        self._subs[topic].append(handler)
        return handler

    def subscribe(self, topic: str):
        def deco(fn: Handler) -> Handler:
            self.on(topic, fn)
            return fn
        return deco

    # -- publicacion --------------------------------------------------
    async def emit(self, topic: str, **data: Any) -> Event:
        ev = Event(topic, data)
        self._history.append(ev)
        for pattern in self._matching(topic):
            for handler in list(self._subs[pattern]):
                try:
                    await handler(ev)
                except Exception as exc:  # una skill rota no tumba el bus
                    print(f"[bus] handler {pattern} fallo: {exc!r}")
        return ev

    def emit_threadsafe(self, topic: str, **data: Any) -> None:
        """Emitir desde un hilo no-asyncio (listener de teclado, callback de audio)."""
        loop = self._loop or asyncio.get_event_loop()
        asyncio.run_coroutine_threadsafe(self.emit(topic, **data), loop)

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    # -- utilidades ---------------------------------------------------
    def _matching(self, topic: str) -> list[str]:
        out = ["*"] if "*" in self._subs else []
        parts = topic.split(".")
        for i in range(len(parts), 0, -1):
            prefix = ".".join(parts[:i])
            if prefix in self._subs:
                out.append(prefix)
            wild = ".".join(parts[:i - 1] + ["*"]) if i > 1 else None
            if wild and wild in self._subs:
                out.append(wild)
        return out

    def recent(self, n: int = 50, prefix: str | None = None) -> list[dict[str, Any]]:
        items = [e for e in self._history if not prefix or e.topic.startswith(prefix)]
        return [e.as_json() for e in items[-n:]]


BUS = Bus()
