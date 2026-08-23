"""La puerta de salida: avisos que llegan cuando no estas delante.

Implementa `NotifyPort`. Existe por el caso que la voz no cubre y que no
tiene arreglo dentro del escritorio: un encargo al taller tarda veinte
minutos, el recordatorio de las nueve suena a las nueve, y a esa hora puedes
estar en otra habitacion. Hablarle a una silla vacia no es avisar.

    -- Que NO es esto --

No es una pasarela de mensajeria. No recibe. FRIDAY no acepta ordenes que
lleguen de fuera, ni por aqui ni por ningun sitio: la unica boca de entrada
sigue siendo el push-to-talk delante del equipo. Aceptar ordenes remotas
sortearia de un golpe el PTT, la confirmacion hablada y la politica —los tres
guardias que existen porque el STT se equivoca— y convertiria un token
filtrado en control de la maquina.

    -- Tres transportes, un contrato --

`ntfy`, `webhook` y `telegram`. Los tres son un POST a una URL; lo que cambia
es la forma del cuerpo. Se eligen por `[notify] kind` en el toml y ninguno
trae credenciales en el codigo: el token sale del entorno, como las claves de
los motores.

Cada envio pasa por `policy.can_notify`, que ademas hereda el guardia de
`can_fetch`: un destino que apunte a la red local no recibe nada.
"""
from __future__ import annotations

import os
from typing import Any

from core.policy import Policy
from system import net
from system.ports import Notice

# Los avisos son cortos a proposito: lo que se lee de un vistazo en una
# pantalla de bloqueo. Lo largo ya esta en el panel y en el vault.
MAX_TITULO = 120
MAX_CUERPO = 900

# Prioridades de ntfy: 1 min .. 5 max. El mapeo se queda estrecho adrede —
# un recordatorio no merece romper el modo silencio del telefono.
_PRIORIDAD_NTFY = {"baja": "2", "normal": "3", "alta": "4"}


def _recorta(notice: Notice) -> tuple[str, str]:
    titulo = " ".join(str(notice.title).split())[:MAX_TITULO]
    cuerpo = str(notice.body).strip()[:MAX_CUERPO]
    return titulo or "F.R.I.D.A.Y", cuerpo


class HttpNotifier:
    """Implementa `NotifyPort` sobre los tres transportes.

    Una sola clase y no tres: el 90% —permiso, recorte, POST, reporte del
    fallo— es identico, y lo unico que cambia es como se arma el cuerpo. Tres
    clases con el mismo `send` copiado serian tres sitios donde olvidarse de
    consultar la politica.
    """

    def __init__(self, policy: Policy, *, kind: str = "ntfy", target: str = "",
                 token_env: str = "", chat_id: str = "",
                 timeout_s: float = 10.0):
        self.policy = policy
        self.kind = (kind or "ntfy").strip().lower()
        self._target = str(target or "").strip()
        self.token_env = str(token_env or "").strip()
        self.chat_id = str(chat_id or "").strip()
        self.timeout_s = float(timeout_s)
        self.last_error = ""

    # ── identidad ─────────────────────────────────────────────────
    @property
    def token(self) -> str:
        return os.environ.get(self.token_env, "") if self.token_env else ""

    @property
    def target(self) -> str:
        """La URL a la que se manda, ya resuelta.

        Telegram la compone con el token, asi que el `target` del toml es
        solo el nombre del bot para el panel. Aqui se devuelve lo que de
        verdad se va a pedir, porque es lo que tiene que ver la politica.
        """
        if self.kind == "telegram":
            return (f"https://api.telegram.org/bot{self.token}/sendMessage"
                    if self.token else "")
        return self._target

    @property
    def configurado(self) -> bool:
        if self.kind == "telegram":
            return bool(self.token and self.chat_id)
        return bool(self._target)

    def describe(self) -> str:
        """Para el panel y el diagnostico. **Nunca incluye el token.**"""
        if self.kind == "telegram":
            estado = "listo" if self.configurado else f"falta ${self.token_env}"
            return f"telegram -> chat {self.chat_id or '?'} ({estado})"
        return f"{self.kind} -> {self._target or 'sin destino'}"

    # ── el cuerpo, segun transporte ───────────────────────────────
    def _payload(self, notice: Notice) -> tuple[dict[str, Any] | None, str, dict[str, str]]:
        titulo, cuerpo = _recorta(notice)

        if self.kind == "telegram":
            texto = f"*{titulo}*\n{cuerpo}" if cuerpo else f"*{titulo}*"
            return ({"chat_id": self.chat_id, "text": texto,
                     "parse_mode": "Markdown",
                     "disable_notification": notice.urgencia == "baja"},
                    "", {})

        if self.kind == "ntfy":
            # ntfy lee titulo y prioridad de las cabeceras y el cuerpo del
            # body. Las cabeceras van en latin-1 por HTTP, y un titulo con
            # tildes revienta el envio entero: se codifica a ASCII con el
            # esquema que ntfy entiende para eso.
            cabeceras = {
                "Title": titulo.encode("utf-8").decode("latin-1", "replace"),
                "Priority": _PRIORIDAD_NTFY.get(notice.urgencia, "3"),
                "Content-Type": "text/plain; charset=utf-8",
            }
            if notice.tag:
                cabeceras["Tags"] = notice.tag
            return None, cuerpo or titulo, cabeceras

        # webhook generico: JSON plano, que lo interprete quien lo reciba
        return ({"title": titulo, "body": cuerpo,
                 "urgency": notice.urgencia, "tag": notice.tag,
                 "source": "friday"}, "", {})

    # ── el contrato ───────────────────────────────────────────────
    async def send(self, notice: Notice) -> bool:
        """Manda el aviso. Nunca lanza: el fallo queda en `last_error`.

        Lo llama trabajo de fondo —el programador, el taller— y ahi una
        excepcion no tiene a quien subir: se comeria el ciclo entero por no
        haber podido avisar de algo que ya paso.
        """
        destino = self.target
        if not self.configurado or not destino:
            self.last_error = "notificacion sin destino configurado"
            return False

        decision = self.policy.can_notify(destino)
        if not decision.allowed:
            self.last_error = decision.reason
            return False

        json_body, texto, cabeceras = self._payload(notice)
        resultado = await net.post(destino, self.policy, json=json_body,
                                   data=texto, headers=cabeceras,
                                   timeout_s=self.timeout_s)
        self.last_error = resultado.error
        return not resultado.error


def build_notifier(cfg: Any, policy: Policy) -> HttpNotifier | None:
    """El notificador del toml, o None si no hay ninguno declarado.

    None y no un objeto inerte, al reves que los puertos de red: `news` y
    `pages` se construyen siempre porque «denegado» es mas informativo que
    «no existe», pero un notificador sin destino no tiene nada que denegar —
    no es una capacidad apagada, es una capacidad no configurada. Que salga
    en `--check` como ausente es la respuesta correcta.
    """
    if not bool(cfg.get("notify.enabled", False)):
        return None
    n = HttpNotifier(
        policy,
        kind=str(cfg.get("notify.kind", "ntfy")),
        target=str(cfg.get("notify.target", "") or ""),
        token_env=str(cfg.get("notify.token_env", "") or ""),
        chat_id=str(cfg.get("notify.chat_id", "") or ""),
        timeout_s=float(cfg.get("notify.timeout_s", 10)),
    )
    return n if n.configurado else None
