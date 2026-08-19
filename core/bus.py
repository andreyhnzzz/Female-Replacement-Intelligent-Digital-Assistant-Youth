"""Bus de eventos asincrono.

Todo en FRIDAY se comunica por aqui: PTT -> STT -> router -> skill -> TTS -> HUD.
Nadie importa a nadie. Por eso el sistema es modular de verdad.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
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
        # Donde contar lo que revienta dentro de un handler. Lo apunta
        # `friday.py` a la bitacora; sin el, el fallo solo queda en
        # `_history`. Ver `_handler_fallo`.
        self.on_error: Callable[[str], None] | None = None

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
                    self._handler_fallo(pattern, exc)
        return ev

    def report(self, message: str, origen: str = "") -> None:
        """Contar algo que **no puede** viajar como evento normal.

        Dos casos: lo que revienta dentro de un handler (reemitirlo llamaria
        otra vez al que acaba de fallar, y eso es un bucle) y lo que pasa
        antes de que el bucle de eventos exista, como el arranque de la
        ventana.

        Todo esto iba a `print`, y en produccion FRIDAY arranca con
        `pythonw.exe`: sin consola `sys.stdout` es None y CPython se come el
        `print` sin decir nada. El rastro se perdia justo en el unico modo en
        que el programa corre siempre.

        Dos destinos, ninguno reentrante: `_history`, para que `recent()` y
        el panel lo vean, y `on_error`, un callback **sincrono** que
        `friday.py` apunta a la bitacora.
        """
        self._history.append(
            Event("core.error", {"origen": origen or "core", "message": message}))
        if self.on_error is None:
            return
        try:
            self.on_error(f"[{origen or 'core'}] {message}")
        except Exception:
            pass                          # ya no queda a quien contarselo

    def _handler_fallo(self, pattern: str, exc: Exception) -> None:
        self.report(f"handler «{pattern}» fallo: {exc!r}", origen="bus")

    def emit_threadsafe(self, topic: str, **data: Any) -> None:
        """Emitir desde un hilo no-asyncio (listener de teclado, callback de audio).

        Sin bucle atado no hay nada que hacer, pero callarse tampoco: quien
        llama a esto es el push-to-talk, y «el microfono no responde» sin una
        linea en la bitacora es exactamente el rato perdido que la bitacora
        existe para evitar.
        """
        loop = self._loop
        if loop is None or loop.is_closed():
            self._handler_fallo(f"emit:{topic}",
                                RuntimeError("bus sin bucle atado (falta bind_loop)"))
            return
        def revisar(f) -> None:
            # Sin esto, una excepcion dentro del emit se queda en el Future y
            # no la ve nadie: el hilo que la provoco ya siguio a lo suyo.
            try:
                exc = f.exception()
            except (asyncio.CancelledError, concurrent.futures.CancelledError):
                return                    # apagando: no es un fallo
            if exc is not None:
                self._handler_fallo(f"emit:{topic}", exc)

        asyncio.run_coroutine_threadsafe(
            self.emit(topic, **data), loop).add_done_callback(revisar)

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
