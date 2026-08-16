"""Anfitrion nativo del acompañante.

Qt vive en el hilo principal; el nucleo asincrono de FRIDAY corre en un hilo
aparte. La frontera son las señales de `FridayBridge`: emitirlas desde el
hilo de asyncio es seguro porque Qt las entrega en cola al hilo de la GUI.

No es una ventana de navegador ni un servidor local. Es una ventana del
sistema, sin marco y sin barra de tareas, que flota sobre tu escritorio.
"""
from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPainter, QPixmap, QRadialGradient
from PySide6.QtQuick import QQuickView
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from core.bus import Bus

from . import backdrop
from .bridge import FridayBridge
from .sprites import PROVIDER_ID, SpriteProvider

QML_DIR = Path(__file__).parent / "qml"

# Importar el modulo registra los tipos QML: el decorador @QmlElement no
# corre si nadie carga el archivo. Sin esto, `import Friday.Geometry` falla
# en el QML y el nucleo 3D cae al plan B sin explicar por que.
try:
    from . import geometry as _geometry     # noqa: F401
    GEOMETRY_OK = True
    GEOMETRY_WHY = ""
except Exception as _exc:                   # QtQuick3D ausente o sin driver
    GEOMETRY_OK = False
    GEOMETRY_WHY = str(_exc)[:160]


def _orb_icon(size: int = 64) -> QIcon:
    """Icono de bandeja: el nucleo, pintado en memoria. Sin archivos externos."""
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)

    grad = QRadialGradient(size / 2, size / 2, size / 2)
    grad.setColorAt(0.0, QColor("#FFFDF2"))
    grad.setColorAt(0.35, QColor("#FFD700"))
    grad.setColorAt(0.75, QColor(255, 140, 0, 170))
    grad.setColorAt(1.0, QColor(255, 140, 0, 0))
    p.setBrush(grad)
    p.setPen(Qt.NoPen)
    p.drawEllipse(0, 0, size, size)

    p.setPen(QColor(255, 179, 71, 210))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(6, 6, size - 12, size - 12)
    p.drawEllipse(14, 18, size - 28, size - 36)
    p.end()
    return QIcon(pix)


class CompanionApp:
    """Ventana flotante + bandeja. Todo lo visual pasa por aqui."""

    def __init__(self, cfg: Any, bus: Bus, submit: Callable[[str], Any]):
        self.cfg = cfg
        self.bus = bus
        self._submit = submit
        self.app: QApplication | None = None
        self.view: QQuickView | None = None
        self.bridge: FridayBridge | None = None
        self.tray: QSystemTrayIcon | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None

    # ══════════════════════════════ arranque
    def run(self, core_main: Callable[[asyncio.AbstractEventLoop], Any]) -> int:
        """Bloquea en el bucle de Qt. `core_main` arranca FRIDAY en otro hilo."""
        QGuiApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
        self.app = QApplication([])
        self.app.setApplicationName("F.R.I.D.A.Y")
        self.app.setQuitOnLastWindowClosed(False)
        self.app.setWindowIcon(_orb_icon())

        # ── nucleo asincrono en su propio hilo ────────────────────
        self._loop = asyncio.new_event_loop()
        ready = threading.Event()

        def spin() -> None:
            asyncio.set_event_loop(self._loop)
            self.bus.bind_loop(self._loop)
            ready.set()
            self._loop.run_forever()

        self._thread = threading.Thread(target=spin, daemon=True, name="friday-core")
        self._thread.start()
        ready.wait(timeout=5)

        # ── puente y ventana ──────────────────────────────────────
        self.bridge = FridayBridge(self.bus, self._submit, self._loop)
        self.bridge.set_ptt(self.cfg.ptt_hint())
        self._build_window()
        self._build_tray()

        # ── enciende FRIDAY dentro del hilo asincrono ─────────────
        asyncio.run_coroutine_threadsafe(core_main(self._loop), self._loop)

        code = self.app.exec()
        self._shutdown_loop()
        return code

    # ══════════════════════════════ ventana
    def _build_window(self) -> None:
        view = QQuickView()
        view.setFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool                      # fuera de la barra de tareas
            | Qt.NoDropShadowWindowHint
        )
        view.setColor(QColor(0, 0, 0, 0))          # fondo real transparente
        view.setResizeMode(QQuickView.SizeRootObjectToView)

        ctx = view.rootContext()
        ctx.setContextProperty("friday", self.bridge)
        ctx.setContextProperty("appWindow", view)
        ctx.setContextProperty("hudCfg", self._hud_config())

        view.engine().addImportPath(str(QML_DIR))
        view.engine().addImageProvider(PROVIDER_ID, SpriteProvider())
        view.setSource(QUrl.fromLocalFile(str(QML_DIR / "Companion.qml")))

        if view.status() == QQuickView.Error:
            for err in view.errors():
                print(f"[qml] {err.toString()}")
            raise RuntimeError("El QML del acompañante no cargo.")

        size = QSize(int(self.cfg.get("desktop.width", 760)),
                     int(self.cfg.get("desktop.height", 460)))
        view.resize(size)

        view.engine().quit.connect(self.app.quit)
        view.show()
        # La posicion se fija DESPUES de show(): antes, el gestor de ventanas
        # la reemplaza por su propia colocacion por defecto.
        self._place(view, size)

        kind = str(self.cfg.get("desktop.backdrop", "none"))
        if kind != "none":
            ok, detail = backdrop.apply(int(view.winId()), kind)
            if not ok:
                print(f"[desktop] sin desenfoque de fondo: {detail}")

        self.view = view

    def _hud_config(self) -> dict[str, Any]:
        """`[desktop.core]` tal cual, para que QML lo lea sin conocer el toml.

        Si la geometria no se pudo importar se fuerza el plan B aqui, en
        Python, en vez de dejar que QML lo descubra fallando: asi el motivo
        aparece en la consola una vez y no como un error de QML sin contexto.
        """
        mode = str(self.cfg.get("desktop.core.mode", "quick3d"))
        if mode == "quick3d" and not GEOMETRY_OK:
            print(f"[desktop] sin QtQuick3D, uso el nucleo 2.5D: {GEOMETRY_WHY}")
            mode = "projected"
        return {
            "mode": mode,
            "nodes": int(self.cfg.get("desktop.core.nodes", 1400)),
            "spokes": int(self.cfg.get("desktop.core.spokes", 28)),
            "dust": int(self.cfg.get("desktop.core.dust", 260)),
            "bloom": bool(self.cfg.get("desktop.core.bloom", True)),
            "depth_field": bool(self.cfg.get("desktop.core.depth_field", True)),
            "fov": float(self.cfg.get("desktop.core.fov", 42)),
        }

    def _place(self, view: QQuickView, size: QSize) -> None:
        """Esquina inferior derecha por defecto, respetando la barra de tareas."""
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        margin = int(self.cfg.get("desktop.margin", 24))
        corner = str(self.cfg.get("desktop.corner", "bottom-right"))

        x = area.right() - size.width() - margin if "right" in corner \
            else area.left() + margin
        y = area.bottom() - size.height() - margin if "bottom" in corner \
            else area.top() + margin
        view.setPosition(int(x), int(y))

    # ══════════════════════════════ bandeja
    def _build_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        tray = QSystemTrayIcon(_orb_icon(), self.app)
        tray.setToolTip(f"F.R.I.D.A.Y — {self.cfg.ptt_hint()} y habla")

        menu = QMenu()
        act_show = menu.addAction("Mostrar")
        act_hide = menu.addAction("Ocultar")
        menu.addSeparator()
        act_quit = menu.addAction("Salir")

        act_show.triggered.connect(self._show)
        act_hide.triggered.connect(lambda: self.view and self.view.hide())
        act_quit.triggered.connect(self.app.quit)

        tray.setContextMenu(menu)
        tray.activated.connect(
            lambda reason: self._show() if reason == QSystemTrayIcon.Trigger else None)
        tray.show()
        self.tray = tray

    def _show(self) -> None:
        if self.view:
            self.view.show()
            self.view.raise_()

    def notify(self, title: str, body: str) -> None:
        if self.tray:
            self.tray.showMessage(title, body, _orb_icon(), 4000)

    # ══════════════════════════════ cierre
    def _shutdown_loop(self) -> None:
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=4)
