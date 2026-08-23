"""Catalogo y lanzador de aplicaciones para Windows.

Cuatro fuentes, porque ninguna sola cubre lo que el usuario llama "una
aplicacion":

  1. **Menu Inicio** (`*.lnk`) — lo clasico y lo mas barato de leer.
  2. **`Get-StartApps`** — incluye las apps empaquetadas (Store/UWP), que no
     dejan acceso directo. Se lanzan por `shell:AppsFolder\\<AppID>`.
  3. **Steam** — los juegos no ponen `.lnk`; viven en
     `steamapps/appmanifest_*.acf` y se lanzan por `steam://rungameid/<id>`.
  4. **PATH y URIs del sistema** — `code`, `ms-settings:`, la papelera.

Se cachea en memoria con TTL: la fuente 2 levanta un PowerShell y la 3 lee
disco, asi que hacerlo en cada peticion se notaria al hablar.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import unicodedata
from pathlib import Path

from core.policy import Policy
from core.proc import NO_WINDOW
from system.ports import AppInfo

# URIs nativas: no son archivos pero el usuario las llama "aplicaciones"
_URIS: dict[str, str] = {
    "configuracion": "ms-settings:",
    "ajustes": "ms-settings:",
    "settings": "ms-settings:",
    "papelera": "shell:RecycleBinFolder",
    "explorador": "explorer.exe",
    "descargas": "shell:Downloads",
    "documentos": "shell:Personal",
    "escritorio": "shell:Desktop",
    "calculadora": "calc.exe",
    "bloc de notas": "notepad.exe",
    "terminal": "wt.exe",
    "administrador de tareas": "taskmgr.exe",
}

_START_MENUS = (
    r"%APPDATA%\Microsoft\Windows\Start Menu\Programs",
    r"%PROGRAMDATA%\Microsoft\Windows\Start Menu\Programs",
)

# Alias hablados que no salen de ningun catalogo. El STT oye «vs code», el
# Menu Inicio dice «Visual Studio Code» y en esta maquina la unica pista es
# un `code.cmd` en el PATH: por eso cada alias lleva VARIOS candidatos y se
# prueban todos. Se completan desde el toml (`[system.app_aliases]`).
_ALIASES: dict[str, tuple[str, ...]] = {
    "vscode": ("visual studio code", "code"),
    "vs code": ("visual studio code", "code"),
    "visual code": ("visual studio code", "code"),
    "chrome": ("google chrome",),
    "edge": ("microsoft edge",),
    "word": ("microsoft word", "winword"),
    "excel": ("microsoft excel",),
    "powerpoint": ("microsoft powerpoint",),
    "cs": ("counter-strike 2",),
    "cs2": ("counter-strike 2",),
    "counter strike": ("counter-strike 2",),
    "geometry": ("geometry dash",),
    "dbd": ("dead by daylight",),
}

# Lo que Steam instala pero nadie llama "un juego". Sin este filtro,
# «abre steam» compite con «Steamworks Common Redistributables».
_STEAM_NOISE = re.compile(
    r"(?i)(steamworks|redistributabl|proton|steam\s*linux\s*runtime|"
    r"directx|vc\+\+|visual c\+\+|dedicated server|soundtrack|demo$)")

_STEAM_KEYS = (
    (r"HKCU", r"Software\Valve\Steam", "SteamPath"),
    (r"HKLM", r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
    (r"HKLM", r"SOFTWARE\Valve\Steam", "InstallPath"),
)


def _fold(s: str) -> str:
    """Normaliza para comparar: sin acentos, minusculas, sin ruido."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9 ]+", " ", s.lower()).strip()


# Palabras que no identifican ninguna aplicacion. Sin esto, «en» bastaba
# para emparejar dos frases que no tienen nada que ver: el 17/08/2026,
# «Descríbete a ti misma en dos palabras» puntuo 0.45 contra el acceso
# directo «Que hay de nuevo en la última versión» y FRIDAY lo lanzo.
_VACIAS = frozenset("""
en el la los las un una de del al y o para por con sin sobre que quien como
cuando donde mi tu su es son the of and to in for a an my your
""".split())


def _score(query: str, name: str) -> float:
    """Puntua que tan bien `name` responde a `query`.

    Las coincidencias fuertes (igualdad, prefijo, subcadena) valen tal cual:
    si dijiste el nombre entero, es el nombre entero. La coincidencia debil
    —compartir palabras sueltas— solo cuenta con palabras que signifiquen
    algo, porque es la unica que puede emparejar dos frases ajenas.
    """
    q, n = _fold(query), _fold(name)
    if not q or not n:
        return 0.0
    if q == n:
        return 1.0
    if n.startswith(q):
        return 0.9
    if q in n:
        return 0.75

    qt = {t for t in q.split() if t not in _VACIAS}
    nt = {t for t in n.split() if t not in _VACIAS}
    if not qt or not nt:
        return 0.0
    if qt <= nt:
        return 0.7
    common = qt & nt
    if common:
        return 0.4 + 0.3 * len(common) / len(qt)
    return 0.0


def _merge_aliases(extra: dict[str, object] | None) -> dict[str, tuple[str, ...]]:
    """Alias del codigo mas los del toml. Un valor puede ser texto o lista."""
    merged: dict[str, tuple[str, ...]] = {
        _fold(k): tuple(_fold(c) for c in v) for k, v in _ALIASES.items()}
    for raw_key, raw_val in (extra or {}).items():
        cands = raw_val if isinstance(raw_val, (list, tuple)) else [raw_val]
        vals = tuple(_fold(str(c)) for c in cands if str(c).strip())
        if vals:
            merged[_fold(str(raw_key))] = vals
    return merged


# ══════════════════════════════════════════════════ fuentes extra
def steam_root() -> Path | None:
    """Donde vive Steam, segun el registro. None si no esta instalado."""
    try:
        import winreg
    except ImportError:
        return None
    roots = {"HKCU": winreg.HKEY_CURRENT_USER, "HKLM": winreg.HKEY_LOCAL_MACHINE}
    for hive, path, value in _STEAM_KEYS:
        try:
            with winreg.OpenKey(roots[hive], path) as key:
                raw, _ = winreg.QueryValueEx(key, value)
        except OSError:
            continue
        p = Path(str(raw).replace("/", "\\"))
        if p.is_dir():
            return p
    return None


def steam_libraries(root: Path) -> list[Path]:
    """Todas las bibliotecas, no solo la de instalacion.

    Quien tiene un SSD chico y un disco grande tiene los juegos repartidos.
    Asumir una sola carpeta deja fuera justo los juegos pesados.
    """
    libs = [root / "steamapps"]
    vdf = root / "steamapps" / "libraryfolders.vdf"
    try:
        text = vdf.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return [p for p in libs if p.is_dir()]

    for m in re.finditer(r'"path"\s+"([^"]+)"', text):
        p = Path(m.group(1).replace("\\\\", "\\")) / "steamapps"
        if p.is_dir() and p not in libs:
            libs.append(p)
    return [p for p in libs if p.is_dir()]


def steam_games() -> list[AppInfo]:
    """Los juegos instalados, leidos de los manifiestos.

    El `.acf` es VDF: pares `"clave" "valor"` planos. Dos regex bastan y no
    hay que meter una dependencia para leer ocho lineas.
    """
    root = steam_root()
    if root is None:
        return []

    out: list[AppInfo] = []
    seen: set[str] = set()
    for lib in steam_libraries(root):
        try:
            manifests = sorted(lib.glob("appmanifest_*.acf"))
        except OSError:
            continue
        for acf in manifests:
            try:
                text = acf.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            appid = re.search(r'"appid"\s+"(\d+)"', text)
            name = re.search(r'"name"\s+"([^"]+)"', text)
            if not appid or not name:
                continue
            # «Overwatch®» se dice «Overwatch». El simbolo de marca no
            # aporta nada al buscar y el TTS intenta pronunciarlo.
            title = re.sub(r"[®™©]", "", name.group(1)).strip()
            if not title or _STEAM_NOISE.search(title) or appid.group(1) in seen:
                continue
            seen.add(appid.group(1))
            out.append(AppInfo(name=title,
                               target=f"steam://rungameid/{appid.group(1)}",
                               kind="uri"))
    return out


def start_apps(timeout_s: float = 8.0) -> list[AppInfo]:
    """Todo lo que el usuario ve en el menu, incluido lo empaquetado.

    `Get-StartApps` es la unica fuente que ve las apps de la Store: no
    dejan `.lnk` en ningun sitio. El peaje es levantar PowerShell una vez
    por refresco, y por eso el catalogo se cachea con un TTL generoso.

    La salida se fuerza a UTF-8: sin eso, PowerShell 5.1 entrega la pagina
    de codigos ANSI y cualquier nombre acentuado llega roto.
    """
    exe = shutil.which("powershell") or shutil.which("powershell.exe")
    if not exe:
        return []

    script = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
              "Get-StartApps | Select-Object Name,AppID | "
              "ConvertTo-Json -Compress")
    try:
        proc = subprocess.run(
            [exe, "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, timeout=timeout_s, check=False,
            creationflags=NO_WINDOW)      # sin ventana negra: ver core/proc.py
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0 or not proc.stdout:
        return []

    try:
        data = json.loads(proc.stdout.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):          # una sola app: JSON escalar
        data = [data]

    out: list[AppInfo] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        name = str(row.get("Name") or "").strip()
        appid = str(row.get("AppID") or "").strip()
        if not name or not appid:
            continue
        # AppsFolder abre por igual lo empaquetado y lo clasico, asi que no
        # hace falta distinguir el tipo de AppID para lanzarlo.
        out.append(AppInfo(name=name, target=f"shell:AppsFolder\\{appid}",
                           kind="uwp"))
    return out


class WindowsAppCatalog:
    """Implementa `AppCatalog`."""

    def __init__(self, ttl_s: float = 120.0,
                 aliases: dict[str, str] | None = None,
                 include_store: bool = True, include_steam: bool = True):
        self.ttl = ttl_s
        self.include_store = include_store
        self.include_steam = include_steam
        self.aliases = _merge_aliases(aliases)
        self._apps: list[AppInfo] = []
        self._built = 0.0
        self.sources: dict[str, int] = {}

    # ── construccion ──────────────────────────────────────────────
    def refresh(self) -> int:
        apps: dict[str, AppInfo] = {}
        counts: dict[str, int] = {}

        def add(app: AppInfo, source: str) -> None:
            """La primera fuente que nombra algo se lo queda.

            El orden no es casual: un `.lnk` se abre directo, `AppsFolder`
            pasa por el shell. Ante el mismo nombre, gana el camino corto.
            """
            key = _fold(app.name)
            if key and key not in apps:
                apps[key] = app
                counts[source] = counts.get(source, 0) + 1

        for raw in _START_MENUS:
            root = Path(os.path.expandvars(raw))
            if not root.is_dir():
                continue
            try:
                for lnk in root.rglob("*.lnk"):
                    add(AppInfo(name=lnk.stem, target=str(lnk), kind="shortcut"),
                        "menu")
            except OSError:
                continue

        # Los juegos van ANTES que la Store: si un juego aparece en ambas,
        # `steam://rungameid` arranca el cliente y el juego; AppsFolder no
        # siempre. Y son lo que mas se pide por voz.
        if self.include_steam:
            for game in steam_games():
                add(game, "steam")

        if self.include_store:
            for app in start_apps():
                add(app, "store")

        for label, uri in _URIS.items():
            add(AppInfo(name=label, target=uri,
                        kind="uri" if ":" in uri and not uri.endswith(".exe") else "exe"),
                "uri")

        for exe in ("code", "chrome", "msedge", "firefox", "python", "git",
                    "obsidian", "spotify", "discord", "steam"):
            if shutil.which(exe):
                add(AppInfo(name=exe, target=exe, kind="exe"), "path")

        self._apps = list(apps.values())
        self._built = time.time()
        self.sources = counts
        return len(self._apps)

    def _ensure(self) -> None:
        if not self._apps or (time.time() - self._built) > self.ttl:
            self.refresh()

    # ── consulta ──────────────────────────────────────────────────
    def _expand(self, query: str) -> list[str]:
        """Lo dicho, mas su alias si lo tiene. Se prueban ambos.

        Traducir y descartar el original seria peor: «chrome» -> «google
        chrome» acierta, pero si un dia no esta instalado Chrome y si un
        `chrome.exe` suelto, el alias lo habria escondido.
        """
        return [query, *self.aliases.get(_fold(query), ())]

    def find(self, query: str, limit: int = 5) -> list[AppInfo]:
        self._ensure()
        best: dict[str, AppInfo] = {}
        for app in self._apps:
            s = max(_score(q, app.name) for q in self._expand(query))
            if s > 0.35:
                key = _fold(app.name)
                if key not in best or s > best[key].score:
                    best[key] = AppInfo(app.name, app.target, app.kind,
                                        app.icon, round(s, 3))
        hits = sorted(best.values(), key=lambda a: -a.score)
        return hits[:limit]


class WindowsAppLauncher:
    """Implementa `AppLauncher`. Todo lanzamiento pasa por la politica."""

    def __init__(self, policy: Policy):
        self.policy = policy
        self.last_error = ""

    def launch(self, app: AppInfo, args: list[str] | None = None) -> bool:
        decision = self.policy.can_launch(app.target)
        if not decision.allowed:
            self.last_error = decision.reason
            return False

        self.last_error = ""
        try:
            if app.kind in ("uri", "shortcut", "uwp"):
                # os.startfile respeta el shell, y el shell es quien sabe
                # abrir un .lnk, una `steam://` y un `shell:AppsFolder\...`.
                # Una app empaquetada no tiene ejecutable que invocar: solo
                # existe para el shell, asi que este es el unico camino.
                os.startfile(app.target)  # noqa: S606
                return True
            cmd = [app.target, *(args or [])]
            subprocess.Popen(cmd, shell=False,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except OSError as exc:
            # ultimo recurso: dejar que el shell resuelva el nombre
            try:
                os.startfile(app.target)  # noqa: S606
                return True
            except OSError:
                self.last_error = str(exc)[:160]
                return False

    def open_path(self, path: Path) -> bool:
        """Abre un archivo o carpeta con lo que el usuario tenga asociado.

        Pasa por `can_open`, no por `can_launch`: la ruta viene de haber
        buscado en el disco, y una busqueda saca lo que haya. Ahi es donde
        se bloquean los ejecutables — abrir un `.exe` que apareció en
        Descargas seria ejecucion arbitraria dictada por voz.

        `os.startfile` y no `Popen`: quien sabe que programa abre un `.xlsx`
        es el shell, no nosotros, y ademas respeta lo que el usuario haya
        elegido como predeterminado.
        """
        ruta = Path(path)
        decision = self.policy.can_open(ruta)
        if not decision.allowed:
            self.last_error = decision.reason
            return False
        if not ruta.exists():
            self.last_error = f"ya no esta ahi: {ruta.name}"
            return False

        self.last_error = ""
        try:
            os.startfile(str(ruta))  # noqa: S606
            return True
        except OSError as exc:
            self.last_error = str(exc)[:160]
            return False
