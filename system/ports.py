"""Puertos del sistema — los contratos que FRIDAY conoce.

Aqui esta la inversion de dependencias del proyecto: las skills dependen de
estos Protocol, nunca de una implementacion concreta. `system/win32/` los
implementa para Windows; manana un `system/linux/` los implementa para X11 y
ninguna skill cambia.

Segregacion de interfaces a proposito: leer y escribir estan separados.
Una skill que solo busca archivos recibe `FileIndex` y es literalmente
incapaz de borrar nada — no por disciplina, por tipo.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


# ══════════════════════════════════════════════ modelos de datos
@dataclass(frozen=True, slots=True)
class AppInfo:
    """Una aplicacion instalada y como lanzarla."""
    name: str
    target: str                      # exe, .lnk, uri o comando
    kind: str = "exe"                # exe | shortcut | uwp | uri
    icon: str | None = None
    score: float = 0.0               # confianza de la coincidencia


@dataclass(frozen=True, slots=True)
class DefaultApp:
    """Lo que el usuario eligio para abrir algo: un esquema, un tipo.

    `path` vacio no invalida la entrada: significa que sabemos QUE app es
    pero no donde vive, y entonces hay que dejarsela al shell.
    """
    name: str
    progid: str = ""
    command: str = ""
    path: str = ""                   # ejecutable resuelto

    @property
    def launchable(self) -> bool:
        return bool(self.path)


@dataclass(frozen=True, slots=True)
class WindowInfo:
    handle: int
    title: str
    process: str = ""
    pid: int = 0
    rect: tuple[int, int, int, int] = (0, 0, 0, 0)
    minimized: bool = False

    @property
    def label(self) -> str:
        return f"{self.title} — {self.process}" if self.process else self.title


@dataclass(frozen=True, slots=True)
class FileInfo:
    path: Path
    name: str
    size: int = 0
    mtime: float = 0.0
    is_dir: bool = False
    score: float = 0.0

    @property
    def ext(self) -> str:
        return self.path.suffix.lower()


class OpKind(str, Enum):
    MOVE = "move"
    RENAME = "rename"
    COPY = "copy"
    MKDIR = "mkdir"
    TRASH = "trash"


@dataclass(slots=True)
class FileOp:
    """Una operacion PLANEADA. Nada se ejecuta al construirla."""
    kind: OpKind
    src: Path
    dst: Path | None = None
    reason: str = ""

    def describe(self) -> str:
        if self.kind is OpKind.MKDIR:
            return f"crear carpeta {self.dst or self.src}"
        if self.kind is OpKind.TRASH:
            return f"a la papelera: {self.src.name}"
        return f"{self.kind.value}: {self.src.name} -> {self.dst}"


@dataclass(slots=True)
class OpResult:
    done: list[FileOp] = field(default_factory=list)
    failed: list[tuple[FileOp, str]] = field(default_factory=list)
    skipped: list[tuple[FileOp, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed

    def summary(self) -> str:
        bits = [f"{len(self.done)} aplicadas"]
        if self.skipped:
            bits.append(f"{len(self.skipped)} omitidas")
        if self.failed:
            bits.append(f"{len(self.failed)} fallidas")
        return ", ".join(bits)


@dataclass(frozen=True, slots=True)
class NewsItem:
    """Un titular. Solo lo que vino del feed: nada inferido."""
    title: str
    source: str = ""
    url: str = ""
    summary: str = ""
    published: float = 0.0           # epoch; 0 = el feed no lo dijo
    topic: str = ""                  # la seccion que lo pidio

    def line(self) -> str:
        return f"- {self.title}" + (f" ({self.source})" if self.source else "")


@dataclass(frozen=True, slots=True)
class PageText:
    """Una pagina reducida a texto plano.

    `truncated` importa: si el resumen se hizo sobre la mitad del articulo,
    quien lo lea tiene que poder saberlo.
    """
    url: str
    title: str = ""
    text: str = ""
    source: str = ""                 # dominio o api de origen
    truncated: bool = False

    @property
    def empty(self) -> bool:
        return not self.text.strip()


@dataclass(frozen=True, slots=True)
class ScreenContext:
    """Lo que el usuario tiene delante, sin adivinar."""
    active_title: str = ""
    active_process: str = ""
    windows: tuple[str, ...] = ()
    text: str = ""                   # texto extraido (UI Automation u OCR)
    source: str = "none"             # uia | ocr | titles | none

    def brief(self, limit: int = 1200) -> str:
        head = f"Ventana activa: {self.active_title or '(ninguna)'}"
        if self.active_process:
            head += f" [{self.active_process}]"
        body = f"\n\nTexto en pantalla ({self.source}):\n{self.text[:limit]}" if self.text else ""
        others = "\n\nOtras ventanas: " + ", ".join(self.windows[:8]) if self.windows else ""
        return head + others + body


# ══════════════════════════════════════════════ puertos de LECTURA
@runtime_checkable
class AppCatalog(Protocol):
    """Encuentra aplicaciones instaladas. Solo lee."""

    def find(self, query: str, limit: int = 5) -> list[AppInfo]: ...
    def refresh(self) -> int: ...


@runtime_checkable
class WindowReader(Protocol):
    """Ve que hay abierto. Solo lee."""

    def list_windows(self) -> list[WindowInfo]: ...
    def active(self) -> WindowInfo | None: ...


@runtime_checkable
class DefaultApps(Protocol):
    """Que aplicacion abre que cosa, segun el usuario. Solo lee.

    Puerto propio y no un metodo de `AppCatalog`: el catalogo dice que hay
    instalado, esto dice que esta elegido. No es la misma pregunta.
    """

    def browser(self) -> DefaultApp | None: ...
    def for_scheme(self, scheme: str) -> DefaultApp | None: ...


@runtime_checkable
class FileIndex(Protocol):
    """Busca archivos. Incapaz de modificarlos."""

    def search(self, query: str, roots: list[Path] | None = None,
               limit: int = 20) -> list[FileInfo]: ...


@runtime_checkable
class ScreenReaderPort(Protocol):
    """Lee el contexto de pantalla."""

    def context(self, with_text: bool = True) -> ScreenContext: ...


@runtime_checkable
class NewsPort(Protocol):
    """Trae titulares. Solo lee, y solo de fuentes declaradas en el toml.

    `async` porque detras hay red: los puertos locales siguen sincronos
    porque el disco responde en microsegundos.
    """

    async def headlines(self, topic: str = "", limit: int = 12) -> list[NewsItem]: ...

    def topics(self) -> list[str]: ...


@runtime_checkable
class PageReaderPort(Protocol):
    """Descarga una pagina y la deja en texto. No navega ni ejecuta scripts.

    `lookup` va aparte de `read`: raspar resultados de un buscador se rompe
    cada vez que cambian el HTML, asi que para temas se usa una API estable.
    """

    async def read(self, url: str) -> PageText: ...

    async def lookup(self, topic: str) -> PageText | None: ...


# ══════════════════════════════════════════════ puertos de ESCRITURA
@runtime_checkable
class AppLauncher(Protocol):
    """Lanza aplicaciones. Efecto sobre el sistema."""

    def launch(self, app: AppInfo, args: list[str] | None = None) -> bool: ...


@runtime_checkable
class WindowController(Protocol):
    """Manipula ventanas. Efecto sobre el sistema."""

    def focus(self, handle: int) -> bool: ...
    def minimize(self, handle: int) -> bool: ...


@runtime_checkable
class FileOrganizer(Protocol):
    """Planea y aplica cambios en disco.

    `plan` es puro: devuelve las operaciones sin tocar nada. `apply` es el
    unico que escribe, y pasa por la politica. Esa separacion es lo que
    permite mostrar al usuario que va a pasar antes de que pase.
    """

    def plan_organize(self, root: Path, strategy: str = "extension") -> list[FileOp]: ...
    def plan_rename(self, files: list[FileInfo], pattern: str) -> list[FileOp]: ...
    def apply(self, ops: list[FileOp], dry_run: bool = False) -> OpResult: ...


@runtime_checkable
class MediaControl(Protocol):
    """Volumen y reproduccion. Efecto inmediato y trivialmente reversible.

    Va separado de `SessionControl` por riesgo, no por comodidad: bajar el
    volumen se deshace subiendolo, bloquear la sesion no se deshace desde
    aqui. Que la politica pueda conceder uno sin el otro es el punto.
    """

    def volume(self, delta: int) -> int: ...
    def set_volume(self, level: int) -> int: ...
    def mute(self) -> bool: ...
    def playback(self, action: str) -> bool: ...     # play_pause | next | prev | stop


@runtime_checkable
class SessionControl(Protocol):
    """Bloquear o suspender la sesion. Te deja fuera de la maquina.

    No incluye apagar ni reiniciar a proposito: una orden dictada por voz y
    mal transcrita no puede costarte el trabajo sin guardar.
    """

    def lock(self) -> bool: ...
    def sleep(self) -> bool: ...


@runtime_checkable
class Clipboard(Protocol):
    """Leer y escribir el portapapeles.

    Leer es sensible aunque parezca inofensivo: ahi es donde la gente pega
    contraseñas. Por eso pasa por politica igual que escribir.
    """

    def read(self) -> str: ...
    def write(self, text: str) -> bool: ...


@runtime_checkable
class WebOpener(Protocol):
    """Abre busquedas, sitios y URLs en el navegador del usuario.

    Le entrega el destino a Chrome y se aparta: la sesion y las cookies
    siguen siendo del usuario. Para que FRIDAY lea el contenido por su
    cuenta esta `PageReaderPort`, que es otro permiso.
    """

    def search(self, query: str, engine: str = "default") -> str: ...
    def open_site(self, name: str) -> str: ...
    def open_url(self, url: str) -> bool: ...


@runtime_checkable
class DocumentWriter(Protocol):
    """Deja un documento en disco: PDF o una hoja de calculo.

    **Solo escribe.** Leer o modificar un PDF ajeno es otro permiso y sera
    otro puerto: aqui se crea a partir de contenido que ya trae FRIDAY, y eso
    no necesita abrir nada del usuario.

    Quien redacta es el motor (devuelve markdown o filas); quien escribe el
    archivo es Python (regla 4). El puerto no le pregunta nada al motor.

    `formats()` dice que sabe hacer AHORA mismo — `xlsx` depende de que
    openpyxl este instalado, y la skill tiene que poder decirlo antes de
    prometerselo al usuario.
    """

    def formats(self) -> tuple[str, ...]: ...
    def write_pdf(self, path: "Path", titulo: str, markdown: str) -> bool: ...
    def write_sheet(self, path: "Path", cabeceras: list[str],
                    filas: list[list[Any]]) -> "Path": ...


# ══════════════════════════════════════════════ agregador
@dataclass(slots=True)
class SystemAccess:
    """Todo lo que FRIDAY puede hacerle a la computadora, en un objeto.

    Cada campo puede ser None: si una capacidad no esta disponible en esta
    plataforma, la skill lo detecta y lo dice, en vez de reventar.
    """
    apps: AppCatalog | None = None
    defaults: DefaultApps | None = None
    launcher: AppLauncher | None = None
    windows: WindowReader | None = None
    window_ctl: WindowController | None = None
    files: FileIndex | None = None
    organizer: FileOrganizer | None = None
    screen: ScreenReaderPort | None = None
    web: WebOpener | None = None
    news: NewsPort | None = None
    pages: PageReaderPort | None = None
    media: MediaControl | None = None
    session: SessionControl | None = None
    clipboard: Clipboard | None = None
    documents: DocumentWriter | None = None

    def available(self) -> dict[str, bool]:
        return {f: getattr(self, f) is not None for f in self.__slots__}

    def missing(self) -> list[str]:
        return [k for k, v in self.available().items() if not v]
