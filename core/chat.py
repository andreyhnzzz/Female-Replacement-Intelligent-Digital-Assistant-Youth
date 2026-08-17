"""El hilo de conversacion.

Hasta ahora cada peticion era independiente: un «y eso cuanto cuesta» no
tenia a que referirse, porque el turno anterior no existia. Esto lo arregla
con lo minimo — una lista de turnos en RAM.

Tres reglas que la mantienen honesta:

  1. **No toca disco.** La memoria de FRIDAY es markdown y solo markdown
     (regla 1 del CLAUDE.md); esto es un cache de sesion, no memoria. Se
     pierde al cerrar y eso es lo correcto: lo que merece recordarse se
     dice («recuerda que...») y acaba en el vault.
  2. **Se enfria.** Pasado `ttl_s` sin hablar, el hilo se corta solo. Un
     «y eso?» cuarenta minutos despues no es una continuacion, es una
     pregunta nueva, y arrastrar contexto viejo hace que el motor responda
     sobre algo que el usuario ya olvido.
  3. **Tiene tope doble** — turnos y caracteres. Un turno largo (el resumen
     de una pagina) puede comerse la ventana el solo, asi que el limite de
     caracteres recorta por el principio aunque queden turnos libres.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Turn:
    role: str                      # user | assistant
    text: str
    ts: float = field(default_factory=time.time)


class Conversation:
    """Los ultimos turnos, y nada mas."""

    def __init__(self, max_turns: int = 12, max_chars: int = 4000,
                 ttl_s: float = 900.0, user_title: str = "Jefe",
                 assistant: str = "FRIDAY"):
        self.max_turns = max(0, int(max_turns))
        self.max_chars = max(0, int(max_chars))
        self.ttl_s = float(ttl_s)
        self.user_title = user_title
        self.assistant = assistant
        self.turns: list[Turn] = []

    # ── estado ────────────────────────────────────────────────────
    @property
    def active(self) -> bool:
        """Hay un hilo vivo al que un «y eso?» pueda referirse."""
        if not self.turns:
            return False
        return (time.time() - self.turns[-1].ts) <= self.ttl_s

    def __len__(self) -> int:
        return len(self.turns)

    # ── escritura ─────────────────────────────────────────────────
    def add(self, role: str, text: str) -> None:
        text = (text or "").strip()
        if not text or self.max_turns == 0:
            return
        if self.turns and not self.active:
            self.turns.clear()          # el hilo se enfrio: empieza otro
        self.turns.append(Turn(role=role, text=text))
        self._trim()

    def clear(self) -> None:
        self.turns.clear()

    def _trim(self) -> None:
        if len(self.turns) > self.max_turns:
            self.turns = self.turns[-self.max_turns:]
        # el tope de caracteres recorta por el principio, que es lo viejo
        while len(self.turns) > 1 and \
                sum(len(t.text) for t in self.turns) > self.max_chars:
            self.turns.pop(0)

    # ── lectura ───────────────────────────────────────────────────
    def transcript(self, limit: int = 0) -> str:
        """El hilo en texto plano, listo para meter en un prompt.

        Con etiquetas habladas («Jefe:», «FRIDAY:») en vez de roles de API:
        el prompt tiene que funcionar con un 8B local que no entiende de
        `role: assistant` pero si de un dialogo escrito (regla 3).
        """
        if not self.turns or not self.active:
            return ""
        rows = [f"{self.user_title if t.role == 'user' else self.assistant}: {t.text}"
                for t in self.turns]
        text = "\n".join(rows)
        if limit and len(text) > limit:
            text = text[-limit:]
            text = text[text.find("\n") + 1:]      # no cortar a media linea
        return text

    def last(self, role: str = "") -> str:
        for t in reversed(self.turns):
            if not role or t.role == role:
                return t.text
        return ""


def build_conversation(cfg) -> Conversation:
    return Conversation(
        max_turns=int(cfg.get("chat.max_turns", 12)),
        max_chars=int(cfg.get("chat.max_chars", 4000)),
        ttl_s=float(cfg.get("chat.ttl_s", 900)),
        user_title=str(cfg.get("identity.user_title", "Jefe")),
        assistant=str(cfg.get("identity.name", "FRIDAY")),
    )
