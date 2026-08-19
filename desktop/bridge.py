"""Puente entre el nucleo de FRIDAY y la capa visual.

Unica frontera entre Python y QML: QML observa propiedades y emite `submit`,
sin conocer skills, vault ni motor. Reescribir la UI en otra tecnologia
cambia este archivo y ninguno mas.
"""
from __future__ import annotations

import asyncio
import math
import time
from typing import Any, Callable

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from core.bus import Bus, Event

# estados del nucleo — el nombre lo consume QML para elegir color y ritmo
IDLE, LISTENING, THINKING, SPEAKING, ERROR, WAITING = (
    "idle", "listening", "thinking", "speaking", "error", "waiting")

# Cada cuanto se recalcula el esfuerzo. No es la tasa de refresco de la
# escena, que interpola sola: es cada cuanto puede cambiar el numero.
_TICK_MS = 90


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
    effortChanged = Signal()
    thoughtsChanged = Signal()
    logAppended = Signal(str, str)        # (quien, texto)

    def __init__(self, bus: Bus, submit: Callable[[str], Any],
                 loop: asyncio.AbstractEventLoop,
                 thought_every_s: float = 2.5, thought_max: int = 14,
                 effort_full_s: float = 45.0):
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

        # ── el reloj del esfuerzo ─────────────────────────────────
        # `_work_since` no es «desde cuando piensa» sino «desde cuando hay
        # trabajo», incluido el de fondo, que deja el estado en reposo. Sin
        # eso, lo unico que tarda minutos seria lo que el HUD no cuenta.
        self._every_s = max(0.2, float(thought_every_s))
        self._max_thoughts = max(0, int(thought_max))
        self._full_s = max(1.0, float(effort_full_s))
        self._work_since = 0.0
        self._jobs = 0                    # encargos de fondo en vuelo
        self._effort = 0.0
        self._thoughts = 0
        self._shed = 0                    # ticks acumulados del desvanecido

        self._clock = QTimer(self)
        self._clock.setInterval(_TICK_MS)
        self._clock.timeout.connect(self._pulse)
        self._clock.start()

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

    def _get_effort(self) -> float:
        return self._effort

    effort = Property(float, _get_effort, notify=effortChanged)

    def _get_thoughts(self) -> int:
        return self._thoughts

    thoughts = Property(int, _get_thoughts, notify=thoughtsChanged)

    # ══════════════════════════════ el reloj del esfuerzo
    def _begin_work(self) -> None:
        """Empieza a contar, sin reiniciar si ya se estaba contando: un turno
        hablado pasa por `ptt.up`, `stt.final` y `router.decided` antes de que
        nadie piense, y reiniciar mediria el ultimo tramo, no la espera."""
        if self._work_since == 0.0:
            self._work_since = time.time()

    def _end_work(self) -> None:
        """El turno acabo; los picos se apagan en `_pulse`, no desaparecen.

        Con un encargo de fondo en vuelo el reloj sigue: el turno que lo pidio
        se cerro, pero FRIDAY sigue trabajando y eso es lo que hay que decir.
        """
        if self._jobs <= 0:
            self._work_since = 0.0

    def _pulse(self) -> None:
        """Corre en el hilo de Qt: traduce tiempo esperando a forma.

        `_work_since` y `_jobs` los escribe el hilo de asyncio y aqui solo se
        leen; son asignaciones sueltas y el peor caso de una lectura vieja es
        un tick de retraso en un adorno.
        """
        if self._work_since > 0.0:
            elapsed = time.time() - self._work_since
            # Curva saturante, no rampa: los primeros segundos son los que
            # tiene que notar el ojo.
            effort = 1.0 - math.exp(-elapsed / (self._full_s / 3.0))
            thoughts = min(self._max_thoughts, int(elapsed / self._every_s))
            self._shed = 0
        elif self._thoughts > 0 or self._effort > 0.005:
            # Se apaga: un pico cada tres ticks, porque vaciar de golpe se lee
            # como un corte. Y resta en vez de factor: una caida geometrica
            # sobre un valor cuantizado tiene punto fijo (0,05 * 0,9 redondea
            # de vuelta a 0,05) y el reloj no volvia a dormirse nunca.
            effort = max(0.0, self._effort - 0.02)
            self._shed += 1
            thoughts = self._thoughts
            if self._shed >= 3:
                self._shed = 0
                thoughts = max(0, self._thoughts - 1)
        else:
            return

        # Cuantizado a centesimas: alimenta una geometria que se reconstruye
        # al cambiar, y nadie ve una milesima.
        effort = round(min(1.0, max(0.0, effort)), 2)
        if effort != self._effort:
            self._effort = effort
            self.effortChanged.emit()
        if thoughts != self._thoughts:
            self._thoughts = thoughts
            self.thoughtsChanged.emit()

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
        self._begin_work()
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
            self._begin_work()

        elif topic == "voice.ptt.discard":
            self._set_state(IDLE)
            self._end_work()
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
            self._begin_work()

        elif topic == "router.decided":
            self._skill = str(d.get("skill", ""))
            self._set_state(THINKING)
            self._begin_work()

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
            self._end_work()

        # El trabajo de fondo deja el estado en reposo: sin esto el HUD dice
        # «no pasa nada» mientras un agente escribe en un repo. Se cuentan
        # porque puede haber varios a la vez.
        elif topic == "agent.started":
            self._jobs += 1
            self._begin_work()

        elif topic in ("agent.done", "agent.failed"):
            self._jobs = max(0, self._jobs - 1)
            self._end_work()

        elif topic == "tts.speaking":
            self._set_state(SPEAKING)

        elif topic == "tts.done":
            self._set_state(WAITING if self._pending else IDLE)

        elif topic == "engine.switched":
            # Cambiarlo por voz sin verlo reflejado deja al usuario sin saber
            # quien esta pensando.
            self._model = str(d.get("label", ""))
            self.modelChanged.emit()
            self.logAppended.emit("sys", f"motor → {self._model}")

        elif topic == "voice.ptt.ready":
            self._ptt = str(d.get("hint", "")) or f"pulsa {d.get('key', '')}".strip()
            self.pttChanged.emit()

        elif topic == "core.error":
            self._set_state(ERROR)
            self._end_work()
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
