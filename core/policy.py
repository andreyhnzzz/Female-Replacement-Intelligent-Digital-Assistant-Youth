"""Politica de permisos: el guardia.

Algo que abre programas y mueve archivos por dictado necesita uno, porque el
STT se equivoca. Cada accion con efecto recibe un veredicto — ALLOW, CONFIRM
(hace falta un si explicito) o DENY, y se dice por que.

Las reglas viven en el toml: el codigo no decide politica, la aplica.
"""
from __future__ import annotations

import fnmatch
import ipaddress
import os
import socket
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


class Verdict(str, Enum):
    ALLOW = "allow"
    CONFIRM = "confirm"
    DENY = "deny"


@dataclass(frozen=True, slots=True)
class Decision:
    verdict: Verdict
    reason: str = ""
    rule: str = ""

    @property
    def allowed(self) -> bool:
        return self.verdict is Verdict.ALLOW

    @property
    def needs_confirm(self) -> bool:
        return self.verdict is Verdict.CONFIRM


# Carpetas que no se tocan jamas, digan lo que digan las reglas del usuario.
# No son configurables a proposito: son el suelo, no una preferencia.
_HARD_DENY = (
    "c:/windows", "c:/program files", "c:/program files (x86)",
    "c:/programdata", "c:/$recycle.bin", "c:/system volume information",
)

# Extensiones que nunca se ejecutan ni se renombran en masa.
_DANGEROUS_EXT = {".sys", ".dll", ".drv", ".efi", ".msi", ".scr", ".cpl"}


# ── direcciones: lo que parece un host y a donde apunta de verdad ──
def _hostname(url: str) -> str:
    """El host de una URL, sin corchetes de IPv6, sin puerto y sin userinfo.

    A mano no sale bien: `urlsplit` ya desenvuelve `[::1]`, descarta el
    `usuario@` y separa el `:puerto` — tres sitios donde un `split` casero
    se equivoca y deja pasar lo que creia estar bloqueando.
    """
    try:
        partes = urlsplit(url.strip())
        partes.port                         # valida el puerto: lanza si no es un numero
        return (partes.hostname or "").strip().lower()
    except ValueError:                      # puerto no numerico, IPv6 mal cerrado
        return ""


def _as_ip(host: str):
    """El host como direccion IP, o None si es un nombre.

    Acepta las tres formas que designan la misma maquina: `127.0.0.1`,
    `2130706433` (decimal) y `0x7f000001` (hex). Windows resuelve las tres,
    asi que bloquear solo la primera no bloquea nada.
    """
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass
    try:
        if host.startswith(("0x", "0X")):
            entero = int(host, 16)
        elif host.isdigit():
            entero = int(host, 10)
        else:
            return None
        if 0 <= entero <= 0xFFFFFFFF:
            return ipaddress.ip_address(entero)
    except ValueError:
        pass
    return None


def _is_local_ip(direccion) -> bool:
    """¿Esta IP vive dentro de la red del usuario?

    `is_private` es una sola comprobacion que ya cubre loopback, RFC1918,
    enlace local, ULA de IPv6 y `0.0.0.0`. Escribir los rangos a mano es lo
    que dejaba fuera IPv6 entero.
    """
    return bool(direccion.is_private or direccion.is_reserved
                or direccion.is_multicast or direccion.is_unspecified)


class Policy:
    """Aplica las reglas de `[policy]` del toml."""

    def __init__(self, cfg: Any):
        p = "policy"
        self.enabled = bool(cfg.get(f"{p}.enabled", True))
        self.allow_launch = bool(cfg.get(f"{p}.allow_launch", True))
        self.allow_file_write = bool(cfg.get(f"{p}.allow_file_write", True))
        self.allow_shell = bool(cfg.get(f"{p}.allow_shell", False))
        self.allow_web = bool(cfg.get(f"{p}.allow_web", True))
        self.allow_web_fetch = bool(cfg.get(f"{p}.allow_web_fetch", True))
        self.confirm_over = int(cfg.get(f"{p}.confirm_over_files", 5))
        self.blocked_apps = [a.lower() for a in cfg.get(f"{p}.blocked_apps", [])]
        self.blocked_hosts = [h.lower() for h in cfg.get(f"{p}.blocked_hosts", [])]
        self.control = {
            "media": bool(cfg.get(f"{p}.allow_media", True)),
            "session": bool(cfg.get(f"{p}.allow_session", False)),
            "clipboard": bool(cfg.get(f"{p}.allow_clipboard", True)),
        }

        self.allow_agent = bool(cfg.get(f"{p}.allow_agent", True))
        self.allow_memory_prune = bool(cfg.get(f"{p}.allow_memory_prune", True))

        root = Path(cfg.root) if hasattr(cfg, "root") else Path.cwd()
        vr = cfg.get("vault.root", "vault") if hasattr(cfg, "get") else "vault"
        self.vault_root = getattr(cfg, "vault_root", None) or (
            Path(vr) if Path(vr).is_absolute() else root / vr)
        try:
            self.vault_root = Path(self.vault_root).resolve()
        except OSError:
            self.vault_root = Path(self.vault_root)

        self.write_roots = self._resolve_roots(
            cfg.get(f"{p}.write_roots", ["~/Documents", "~/Downloads", "~/Desktop"]), root)
        self.read_roots = self._resolve_roots(
            cfg.get(f"{p}.read_roots", ["~"]), root)
        # Lista aparte y vacia por defecto: no hay raiz razonable que
        # adivinar, y adivinar mal deja a un agente suelto en tu disco.
        self.agent_roots = self._resolve_roots(cfg.get(f"{p}.agent_roots", []), root)

    # ── raices ────────────────────────────────────────────────────
    @staticmethod
    def _resolve_roots(items: list[str], base: Path) -> list[Path]:
        out: list[Path] = []
        for raw in items or []:
            p = Path(os.path.expandvars(str(raw))).expanduser()
            if not p.is_absolute():
                p = base / p
            try:
                out.append(p.resolve())
            except OSError:
                continue
        return out

    @staticmethod
    def _under(path: Path, roots: list[Path]) -> bool:
        try:
            rp = path.resolve()
        except OSError:
            return False
        return any(rp == r or r in rp.parents for r in roots)

    @staticmethod
    def _is_hard_denied(path: Path) -> bool:
        s = str(path.resolve()).replace("\\", "/").lower()
        return any(s == d or s.startswith(d + "/") for d in _HARD_DENY)

    # ── decisiones ────────────────────────────────────────────────
    def can_launch(self, target: str) -> Decision:
        if not self.enabled:
            return Decision(Verdict.ALLOW, "politica desactivada")
        if not self.allow_launch:
            return Decision(Verdict.DENY, "lanzar aplicaciones esta deshabilitado",
                            "policy.allow_launch")
        low = target.lower()
        for pat in self.blocked_apps:
            if fnmatch.fnmatch(low, pat) or pat in low:
                return Decision(Verdict.DENY, f"«{pat}» esta en la lista negra",
                                "policy.blocked_apps")
        return Decision(Verdict.ALLOW)

    def can_read(self, path: Path) -> Decision:
        if not self.enabled:
            return Decision(Verdict.ALLOW, "politica desactivada")
        if self._is_hard_denied(path):
            return Decision(Verdict.DENY, "carpeta protegida del sistema", "hard-deny")
        if self.read_roots and not self._under(path, self.read_roots):
            return Decision(Verdict.DENY, "fuera de las raices de lectura",
                            "policy.read_roots")
        return Decision(Verdict.ALLOW)

    def can_write(self, path: Path) -> Decision:
        if not self.enabled:
            return Decision(Verdict.ALLOW, "politica desactivada")
        if not self.allow_file_write:
            return Decision(Verdict.DENY, "escritura en disco deshabilitada",
                            "policy.allow_file_write")
        if self._is_hard_denied(path):
            return Decision(Verdict.DENY, "carpeta protegida del sistema", "hard-deny")
        if path.suffix.lower() in _DANGEROUS_EXT:
            return Decision(Verdict.DENY, f"extension critica ({path.suffix})",
                            "hard-deny")
        if not self._under(path, self.write_roots):
            return Decision(Verdict.DENY,
                            "fuera de las carpetas donde puedo escribir",
                            "policy.write_roots")
        return Decision(Verdict.ALLOW)

    def can_apply_batch(self, ops: list[Any]) -> Decision:
        """Un lote entero: gana la decision mas restrictiva."""
        if not self.enabled:
            return Decision(Verdict.ALLOW, "politica desactivada")
        if not ops:
            return Decision(Verdict.ALLOW, "nada que hacer")

        for op in ops:
            for target in (getattr(op, "src", None), getattr(op, "dst", None)):
                if target is None:
                    continue
                d = self.can_write(Path(target))
                if d.verdict is Verdict.DENY:
                    return Decision(Verdict.DENY,
                                    f"{d.reason}: {Path(target).name}", d.rule)

        if len(ops) > self.confirm_over:
            return Decision(Verdict.CONFIRM,
                            f"son {len(ops)} archivos (umbral {self.confirm_over})",
                            "policy.confirm_over_files")

        if any(getattr(getattr(op, "kind", None), "value", "") == "trash" for op in ops):
            return Decision(Verdict.CONFIRM, "hay envios a la papelera", "trash")

        return Decision(Verdict.ALLOW)

    def can_shell(self, command: str) -> Decision:
        if not self.enabled:
            return Decision(Verdict.ALLOW, "politica desactivada")
        if not self.allow_shell:
            return Decision(Verdict.DENY,
                            "ejecucion de comandos deshabilitada",
                            "policy.allow_shell")
        return Decision(Verdict.CONFIRM, "todo comando de shell se confirma", "shell")

    def can_delegate(self, path: Path, writes: bool = False) -> Decision:
        """Soltar un agente dentro de un directorio: el permiso mas fuerte.

        No es «escribir un archivo», es delegar en algo que elige por su
        cuenta que tocar, dirigido por un dictado que a veces oye mal.

        - Lista blanca explicita: `agent_roots` vacia = no se delega en
          ningun sitio, y no hereda de `write_roots`.
        - Leer no es escribir: revisar corre solo, arreglar espera un «si».
        """
        if not self.enabled:
            return Decision(Verdict.ALLOW, "politica desactivada")
        if not self.allow_agent:
            return Decision(Verdict.DENY, "delegar trabajo esta deshabilitado",
                            "policy.allow_agent")
        if not self.agent_roots:
            return Decision(Verdict.DENY,
                            "no hay ningun directorio declarado en agent_roots",
                            "policy.agent_roots")
        if self._is_hard_denied(path):
            return Decision(Verdict.DENY, "carpeta protegida del sistema", "hard-deny")
        if not self._under(path, self.agent_roots):
            return Decision(Verdict.DENY,
                            "fuera de los directorios donde puedo delegar trabajo",
                            "policy.agent_roots")
        if writes:
            return Decision(Verdict.CONFIRM,
                            "va a modificar archivos del proyecto", "agent-write")
        return Decision(Verdict.ALLOW)

    def can_prune(self, paths: list[Path]) -> Decision:
        """Retirar notas del vault que ya quedaron resumidas en otra.

        El unico permiso que **quita** algo, y por eso no se parece a
        `can_write`: la frontera no es `write_roots` —el vault no esta ahi—
        sino el vault, donde vive lo que escribio FRIDAY. Fuera estan los
        archivos del usuario, y esos no los retira nadie por su cuenta.

        Interruptor propio y no `allow_file_write`: mover un PDF y decidir
        que dos semanas de diario sobran no son la misma decision.
        """
        if not self.enabled:
            return Decision(Verdict.ALLOW, "politica desactivada")
        if not self.allow_memory_prune:
            return Decision(Verdict.DENY, "retirar notas esta deshabilitado",
                            "policy.allow_memory_prune")
        if not paths:
            return Decision(Verdict.ALLOW, "nada que retirar")

        for raw in paths:
            p = Path(raw)
            if p.suffix.lower() != ".md":
                return Decision(Verdict.DENY, f"no es una nota: {p.name}",
                                "hard-deny")
            try:
                rp = p.resolve()
            except OSError:
                return Decision(Verdict.DENY, f"ruta ilegible: {p.name}", "hard-deny")
            if self.vault_root not in rp.parents:
                return Decision(Verdict.DENY,
                                f"fuera del vault: {p.name}", "vault-only")
        return Decision(Verdict.ALLOW)

    def can_web(self, url: str) -> Decision:
        if not self.enabled:
            return Decision(Verdict.ALLOW, "politica desactivada")
        if not self.allow_web:
            return Decision(Verdict.DENY, "abrir el navegador esta deshabilitado",
                            "policy.allow_web")
        return Decision(Verdict.ALLOW)

    def can_control(self, kind: str) -> Decision:
        """Control directo del escritorio: `media`, `session` o `clipboard`.

        Un interruptor cada uno porque el riesgo no se parece: el volumen se
        deshace solo, la sesion te deja fuera y el portapapeles a veces tiene
        una contraseña. Con un solo `allow_control`, habilitar lo util
        obligaria a habilitar lo delicado.
        """
        if not self.enabled:
            return Decision(Verdict.ALLOW, "politica desactivada")

        kind = (kind or "").strip().lower()
        permitido = self.control.get(kind)
        if permitido is None:
            return Decision(Verdict.DENY, f"control desconocido: «{kind}»", "hard-deny")
        if not permitido:
            return Decision(Verdict.DENY,
                            f"el control de {kind} esta deshabilitado",
                            f"policy.allow_{kind}")

        # La sesion se confirma siempre: «bloquea» mal transcrito no puede
        # echarte de la maquina sin que lo digas dos veces.
        if kind == "session":
            return Decision(Verdict.CONFIRM, "bloquear o suspender se confirma", "session")
        return Decision(Verdict.ALLOW)

    def can_fetch(self, url: str) -> Decision:
        """Descargar una pagina para leerla. Distinto de abrirla: `can_web`
        entrega la URL al navegador del usuario, con su sesion y sus cookies;
        esto autoriza que **FRIDAY** salga a la red por su cuenta."""
        if not self.enabled:
            return Decision(Verdict.ALLOW, "politica desactivada")
        if not self.allow_web_fetch:
            return Decision(Verdict.DENY, "leer paginas de la red esta deshabilitado",
                            "policy.allow_web_fetch")

        try:
            esquema = urlsplit(url.strip()).scheme.lower()
        except ValueError:
            return Decision(Verdict.DENY, "URL ilegible", "hard-deny")
        if esquema not in ("http", "https"):
            return Decision(Verdict.DENY, "solo http/https", "hard-deny")

        host = _hostname(url)
        if not host:
            return Decision(Verdict.DENY, "URL sin host", "hard-deny")

        # La red local no es «la web»: que una URL dictada alcance el router
        # o un servicio interno es un accidente, no una funcion.
        #
        # Partir la cadena a mano no servia. `[::1]` roto por `:` daba `[`,
        # que no se parece a nada de la lista, asi que el chequeo de `::1`
        # que habia aqui no podia dispararse nunca; y `2130706433` es
        # 127.0.0.1 sin un solo punto. Lo resuelven `_hostname` y `_as_ip`.
        literal = _as_ip(host)
        if literal is not None and _is_local_ip(literal):
            return Decision(Verdict.DENY, "direccion de red local", "hard-deny")
        if host == "localhost" or host.endswith((".local", ".localhost", ".internal")):
            return Decision(Verdict.DENY, "direccion de red local", "hard-deny")

        for pat in self.blocked_hosts:
            if fnmatch.fnmatch(host, pat) or pat in host:
                return Decision(Verdict.DENY, f"«{pat}» esta en la lista negra",
                                "policy.blocked_hosts")

        return Decision(Verdict.ALLOW)

    def resolves_to_local(self, url: str) -> Decision:
        """La otra mitad de `can_fetch`: ¿a que IP apunta ese nombre?

        Va aparte porque **consulta el DNS**, y eso bloquea hasta segundos.
        `can_fetch` es puro y decide en microsegundos; separarlos deja el
        permiso barato, comprobable sin red y usable desde el bucle de
        eventos, y confina el paso caro a un hilo (ver `system/net.py`).

        Cierra el unico hueco que la comprobacion literal no puede ver: un
        nombre publico que resuelve a 127.0.0.1. Sin esto, `localtest.me`
        entra andando.
        """
        if not self.enabled:
            return Decision(Verdict.ALLOW, "politica desactivada")

        host = _hostname(url)
        if not host:
            return Decision(Verdict.DENY, "URL sin host", "hard-deny")
        if _as_ip(host) is not None:
            return Decision(Verdict.ALLOW, "literal, ya lo vio can_fetch")

        try:
            infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
        except (OSError, UnicodeError):
            return Decision(Verdict.DENY, f"no se pudo resolver «{host}»", "hard-deny")

        for info in infos:
            direccion = _as_ip(str(info[4][0]))
            # Un nombre que no sabemos a donde apunta tampoco se visita.
            if direccion is None or _is_local_ip(direccion):
                return Decision(Verdict.DENY,
                                f"«{host}» resuelve a una direccion local",
                                "hard-deny")
        return Decision(Verdict.ALLOW)

    # ── para el acompanante ───────────────────────────────────────
    def snapshot(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "launch": self.allow_launch,
            "file_write": self.allow_file_write,
            "shell": self.allow_shell,
            "web": self.allow_web,
            "web_fetch": self.allow_web_fetch,
            "agent": self.allow_agent,
            "memory_prune": self.allow_memory_prune,
            "control": dict(self.control),
            "confirm_over": self.confirm_over,
            "write_roots": [str(r) for r in self.write_roots],
            "agent_roots": [str(r) for r in self.agent_roots],
        }
