"""Puente entre el nucleo de FRIDAY y la capa visual.

Unica frontera entre Python y QML. QML no conoce skills, vault ni motor:
observa propiedades y emite `submit`. Si mañana la UI se reescribe en otra
tecnologia, este archivo es lo unico que cambia.
"""
from __future__ import annotations

import asyncio
from typing import Any, Callable

from PySide6.QtCore import Property, QObject, Signal, Slot

from core.bus import Bus, Event

# estados del nucleo — el nombre lo consume QML para elegir color y ritmo
IDLE, LISTENING, THINKING, SPEAKING, ERROR, WAITING = (
    "idle", "listening", "thinking", "speaking", "error", "waiting")


class FridayBridge(QObject):
    """Modelo observable del estado de FRIDAY."""

    stateChanged = Signal()
    levelChanged = Signal()
    transcriptChanged = Signal()
    responseChanged = Signal()
    pendingChanged = Signal()
    statusChanged = Signal()
    modelChanged = Signal()
    pttChanged = Signal()
    logAppended = Signal(str, str)        # (quien, texto)

    def __init__(self, bus: Bus, submit: Callable[[str], Any],
                 loop: asyncio.AbstractEventLoop):
        super().__init__()
        self._bus = bus
        self._submit = submit
        self._loop = loop

        self._state = IDLE
        self._level = 0.0
        self._transcript = ""
        self._response = ""
        self._pending = ""
        self._status = "iniciando"
        self._skill = ""
        self._model = ""
        self._ptt = ""

        bus.on("*", self._on_event)

    # ══════════════════════════════ propiedades para QML
    def _get_state(self) -> str:
        return self._state

    def _set_state(self, v: str) -> None:
        if v != self._state:
            self._state = v
            self.stateChanged.emit()

    state = Property(str, _get_state, _set_state, notify=stateChanged)

    def _get_level(self) -> float:
        return self._level

    level = Property(float, _get_level, notify=levelChanged)

    def _get_transcript(self) -> str:
        return self._transcript

    transcript = Property(str, _get_transcript, notify=transcriptChanged)

    def _get_response(self) -> str:
        return self._response

    response = Property(str, _get_response, notify=responseChanged)

    def _get_pending(self) -> str:
        return self._pending

    pending = Property(str, _get_pending, notify=pendingChanged)

    def _get_status(self) -> str:
        return self._status

    status = Property(str, _get_status, notify=statusChanged)

    def _get_skill(self) -> str:
        return self._skill

    skill = Property(str, _get_skill, notify=responseChanged)

    def _get_model(self) -> str:
        return self._model

    model = Property(str, _get_model, notify=modelChanged)

    def _get_ptt(self) -> str:
        return self._ptt

    ptt = Property(str, _get_ptt, notify=pttChanged)

    # ══════════════════════════════ de QML hacia Python
    @Slot(str)
    def submit(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        self._transcript = text
        self.transcriptChanged.emit()
        self.logAppended.emit("tu", text)
        self._set_state(THINKING)
        asyncio.run_coroutine_threadsafe(self._submit(text), self._loop)

    @Slot()
    def confirm(self) -> None:
        self.submit("si")

    @Slot()
    def cancel(self) -> None:
        self.submit("cancela")

    # ══════════════════════════════ del bus hacia QML
    async def _on_event(self, ev: Event) -> None:
        topic, d = ev.topic, ev.data

        if topic == "voice.ptt.down":
            self._set_state(LISTENING)

        elif topic == "voice.ptt.up":
            self._set_state(THINKING)

        elif topic == "voice.ptt.discard":
            self._set_state(IDLE)
            self.logAppended.emit("sys", "muy corto, descartado")

        elif topic == "voice.level":
            self._level = float(d.get("level", 0.0))
            self.levelChanged.emit()

        elif topic == "voice.stt.final":
            self._transcript = str(d.get("text", ""))
            self.transcriptChanged.emit()
            if self._transcript:
                self.logAppended.emit("tu", self._transcript)
            self._set_state(THINKING)

        elif topic == "router.decided":
            self._skill = str(d.get("skill", ""))
            self._set_state(THINKING)

        elif topic == "skill.result":
            self._response = str(d.get("display", "") or d.get("speak", ""))
            self.responseChanged.emit()
            speak = str(d.get("speak", ""))
            if speak:
                self.logAppended.emit("friday", speak)
            pend = str(d.get("pending", ""))
            if pend != self._pending:
                self._pending = pend
                self.pendingChanged.emit()
            self._set_state(WAITING if pend else IDLE)

        elif topic == "tts.speaking":
            self._set_state(SPEAKING)

        elif topic == "tts.done":
            self._set_state(WAITING if self._pending else IDLE)

        elif topic == "engine.switched":
            # El modelo activo se muestra siempre: cambiarlo por voz sin
            # verlo reflejado deja al usuario sin saber quien esta pensando.
            self._model = str(d.get("label", ""))
            self.modelChanged.emit()
            self.logAppended.emit("sys", f"motor → {self._model}")

        elif topic == "voice.ptt.ready":
            self._ptt = str(d.get("hint", "")) or f"pulsa {d.get('key', '')}".strip()
            self.pttChanged.emit()

        elif topic == "core.error":
            self._set_state(ERROR)
            self.logAppended.emit("error", str(d.get("message", "")))

        elif topic == "core.info":
            msg = str(d.get("message", ""))
            self._status = msg
            self.statusChanged.emit()
            self.logAppended.emit("sys", msg)

    # ══════════════════════════════ estado inicial
    def set_status(self, text: str) -> None:
        self._status = text
        self.statusChanged.emit()

    def set_model(self, label: str) -> None:
        """El modelo de arranque. Despues lo mantiene `engine.switched`."""
        self._model = label
        self.modelChanged.emit()

    def set_ptt(self, hint: str) -> None:
        self._ptt = hint
        self.pttChanged.emit()
