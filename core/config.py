"""Carga de configuracion. Un solo objeto, acceso por ruta punteada.

Dos archivos, y la diferencia importa porque este repo es publico:

    config/friday.toml         se versiona. Es el ejemplo que ve todo el
                               mundo: valores por defecto y documentacion.
    config/friday.local.toml   NO se versiona. Lo tuyo: las rutas de tus
                               proyectos, tus alias, tus claves.

El segundo se fusiona **encima** del primero, tabla por tabla, asi que solo
tienes que escribir lo que cambies. Si no existe, no pasa nada.

Sin esta separacion, configurar FRIDAY significaba editar un archivo
versionado, y entonces tu disco acaba en un commit. Ha pasado.
"""
from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


def _merge(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    """Fusion profunda: `extra` gana, pero solo en lo que menciona.

    Las listas se reemplazan enteras, no se concatenan: si declaras
    `agent_roots` en tu archivo local, quieres **esas** raices, no esas mas
    las del ejemplo.
    """
    out = dict(base)
    for clave, valor in extra.items():
        if isinstance(valor, dict) and isinstance(out.get(clave), dict):
            out[clave] = _merge(out[clave], valor)
        else:
            out[clave] = valor
    return out


class Config:
    """Wrapper de solo lectura sobre friday.toml (+ friday.local.toml).

    Uso:  cfg.get("voice.stt.model", "small")
          cfg["engine"]["backend"]
    """

    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else ROOT / "config" / "friday.toml"
        if not self.path.exists():
            raise FileNotFoundError(f"No encuentro la config: {self.path}")
        self.local_path = self.path.with_name(f"{self.path.stem}.local.toml")
        self.root = ROOT
        self._data: dict[str, Any] = {}
        self.reload()

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self._data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def path_of(self, dotted: str, default: str = "") -> Path:
        """Resuelve un valor de config como ruta absoluta bajo ROOT."""
        raw = self.get(dotted, default)
        p = Path(raw)
        return p if p.is_absolute() else (self.root / p)

    @property
    def vault_root(self) -> Path:
        return self.path_of("vault.root", "vault")

    def ptt_hint(self) -> str:
        """Como se le dice al usuario que hable.

        Vive aqui porque lo necesitan dos capas que no se conocen: `voice/`
        para anunciarlo por el bus y `desktop/` para pintarlo antes de que la
        voz haya arrancado siquiera. Duplicar el formato garantizaria que un
        dia digan cosas distintas.
        """
        key = str(self.get("voice.ptt.key", "space")).upper()
        mode = str(self.get("voice.ptt.mode", "hold"))
        return f"pulsa {key}" if mode == "toggle" else f"manten {key}"

    def persona(self) -> str:
        """Texto de persona con los placeholders resueltos."""
        pf = self.path_of("identity.persona_file", "config/persona.md")
        text = pf.read_text(encoding="utf-8") if pf.exists() else ""
        return text.replace("{user_title}", self.get("identity.user_title", "Jefe"))

    @property
    def has_local(self) -> bool:
        return self.local_path.exists()

    def reload(self) -> None:
        with open(self.path, "rb") as fh:
            data = tomllib.load(fh)
        if self.local_path.exists():
            with open(self.local_path, "rb") as fh:
                data = _merge(data, tomllib.load(fh))
        self._data = data


_singleton: Config | None = None


def load(path: Path | str | None = None) -> Config:
    global _singleton
    if _singleton is None or path is not None:
        _singleton = Config(path)
    return _singleton
