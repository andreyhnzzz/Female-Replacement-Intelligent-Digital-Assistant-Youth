"""Carga de configuracion. Un solo objeto, acceso por ruta punteada."""
from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


class Config:
    """Wrapper de solo lectura sobre friday.toml.

    Uso:  cfg.get("voice.stt.model", "small")
          cfg["engine"]["backend"]
    """

    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else ROOT / "config" / "friday.toml"
        if not self.path.exists():
            raise FileNotFoundError(f"No encuentro la config: {self.path}")
        with open(self.path, "rb") as fh:
            self._data: dict[str, Any] = tomllib.load(fh)
        self.root = ROOT

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

    def reload(self) -> None:
        with open(self.path, "rb") as fh:
            self._data = tomllib.load(fh)


_singleton: Config | None = None


def load(path: Path | str | None = None) -> Config:
    global _singleton
    if _singleton is None or path is not None:
        _singleton = Config(path)
    return _singleton
