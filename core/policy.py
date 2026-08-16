"""Politica de permisos.

Una herramienta que abre programas y mueve archivos por dictado de voz
necesita un guardia, porque el STT se equivoca. "Borra los temporales"
mal reconocido no puede convertirse en un desastre.

Cada accion con efecto pasa por aqui y recibe un veredicto:

    ALLOW    adelante
    CONFIRM  hace falta un si explicito del usuario
    DENY     no, y se dice por que

Las reglas viven en el toml. El codigo no decide politica; la aplica.
"""
from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


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

        root = Path(cfg.root) if hasattr(cfg, "root") else Path.cwd()
        self.write_roots = self._resolve_roots(
            cfg.get(f"{p}.write_roots", ["~/Documents", "~/Downloads", "~/Desktop"]), root)
        self.read_roots = self._resolve_roots(
            cfg.get(f"{p}.read_roots", ["~"]), root)

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

    def can_web(self, url: str) -> Decision:
        if not self.enabled:
            return Decision(Verdict.ALLOW, "politica desactivada")
        if not self.allow_web:
            return Decision(Verdict.DENY, "abrir el navegador esta deshabilitado",
                            "policy.allow_web")
        return Decision(Verdict.ALLOW)

    def can_control(self, kind: str) -> Decision:
        """Control directo del escritorio: `media`, `session` o `clipboard`.

        Cada uno tiene su interruptor porque el riesgo no se parece en nada:
        bajar el volumen se deshace subiendolo; bloquear la sesion te deja
        fuera; leer el portapapeles ve lo ultimo que copiaste, que a menudo
        es una contraseña. Un solo `allow_control` los trataria igual, y
        entonces habilitar lo util obligaria a habilitar lo delicado.
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

        # La sesion se confirma siempre, aunque este permitida: «bloquea» mal
        # transcrito no puede echarte de la maquina sin que lo digas dos veces.
        if kind == "session":
            return Decision(Verdict.CONFIRM, "bloquear o suspender se confirma", "session")
        return Decision(Verdict.ALLOW)

    def can_fetch(self, url: str) -> Decision:
        """Descargar una pagina para leerla. Distinto de abrirla.

        `can_web` autoriza entregarle una URL al navegador del usuario: la
        peticion la hace Chrome, con su sesion y sus cookies. `can_fetch`
        autoriza que **FRIDAY** salga a la red por su cuenta. Es un permiso
        mas fuerte y por eso tiene su propio interruptor.
        """
        if not self.enabled:
            return Decision(Verdict.ALLOW, "politica desactivada")
        if not self.allow_web_fetch:
            return Decision(Verdict.DENY, "leer paginas de la red esta deshabilitado",
                            "policy.allow_web_fetch")

        low = url.strip().lower()
        if not low.startswith(("http://", "https://")):
            return Decision(Verdict.DENY, "solo http/https", "hard-deny")

        host = low.split("://", 1)[1].split("/", 1)[0].split("@")[-1].split(":")[0]
        if not host:
            return Decision(Verdict.DENY, "URL sin host", "hard-deny")

        # La red local no es «la web». Que una URL dictada por voz alcance el
        # router o un servicio interno no es una funcion, es un accidente.
        if host in ("localhost", "::1") or host.endswith(".local") or \
                host.startswith(("127.", "10.", "192.168.", "169.254.")) or \
                any(host.startswith(f"172.{n}.") for n in range(16, 32)):
            return Decision(Verdict.DENY, "direccion de red local", "hard-deny")

        for pat in self.blocked_hosts:
            if fnmatch.fnmatch(host, pat) or pat in host:
                return Decision(Verdict.DENY, f"«{pat}» esta en la lista negra",
                                "policy.blocked_hosts")

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
            "control": dict(self.control),
            "confirm_over": self.confirm_over,
            "write_roots": [str(r) for r in self.write_roots],
        }
