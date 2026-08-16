"""Previsualiza el acompañante sin arrancar el nucleo.

Carga solo el QML con datos de muestra: sin motor, sin voz, sin acceso al
sistema. Sirve para iterar el diseño en segundos en vez de esperar a que
cargue el modelo de voz.

    python scripts/ui_preview.py                 estado inactivo
    python scripts/ui_preview.py listening       con el orbe escuchando
    python scripts/ui_preview.py thinking        procesando
    python scripts/ui_preview.py waiting         con confirmacion pendiente
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Property, QObject, QTimer, QUrl, Qt, Signal, Slot
from PySide6.QtGui import QColor
from PySide6.QtQuick import QQuickView
from PySide6.QtWidgets import QApplication

DEMO = """# Descargas organizadas

**199** movimientos planeados, estrategia `extension`

### Destinos
- **Documentos** — 50 archivos
- **Comprimidos** — 41 archivos
- **Imagenes** — 30 archivos
- **Instaladores** — 22 archivos

### Muestra
- `informe-final.pdf` → `Documentos/`
- `captura-2026.png` → `Imagenes/`
- `respaldo.zip` → `Comprimidos/`

---

Patron integrado. Frecuencia estable.
"""


class MockBridge(QObject):
    """Mismo contrato que FridayBridge, con datos fijos."""

    stateChanged = Signal()
    levelChanged = Signal()
    transcriptChanged = Signal()
    responseChanged = Signal()
    pendingChanged = Signal()
    statusChanged = Signal()
    logAppended = Signal(str, str)

    def __init__(self, state: str = "idle"):
        super().__init__()
        self._state = state
        self._level = 0.0
        self._pending = ("organizar Downloads: 199 movimientos"
                         if state == "waiting" else "")

    state = Property(str, lambda s: s._state, notify=stateChanged)
    level = Property(float, lambda s: s._level, notify=levelChanged)
    transcript = Property(str, lambda s: "organiza mis descargas",
                          notify=transcriptChanged)
    response = Property(str, lambda s: DEMO, notify=responseChanged)
    pending = Property(str, lambda s: s._pending, notify=pendingChanged)
    status = Property(str, lambda s: "vista previa", notify=statusChanged)
    skill = Property(str, lambda s: "archivos · 167ms", notify=responseChanged)

    def pulse(self) -> None:
        """Simula el nivel de audio para ver reaccionar al orbe."""
        import math
        import time
        self._level = abs(math.sin(time.time() * 3)) * 0.5
        self.levelChanged.emit()

    # ranuras que el QML invoca — sin @Slot, QML no las ve como funciones
    @Slot(str)
    def submit(self, text: str) -> None:
        print(f"[preview] submit: {text}")

    @Slot()
    def confirm(self) -> None:
        print("[preview] confirmar")

    @Slot()
    def cancel(self) -> None:
        print("[preview] cancelar")


def main() -> int:
    state = sys.argv[1] if len(sys.argv) > 1 else "idle"
    app = QApplication([])

    bridge = MockBridge(state)
    view = QQuickView()
    view.setFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
    view.setColor(QColor(0, 0, 0, 0))
    view.setResizeMode(QQuickView.SizeRootObjectToView)

    ctx = view.rootContext()
    ctx.setContextProperty("friday", bridge)
    ctx.setContextProperty("appWindow", view)

    qml = ROOT / "desktop" / "qml"
    view.engine().addImportPath(str(qml))
    view.setSource(QUrl.fromLocalFile(str(qml / "Companion.qml")))

    if view.status() == QQuickView.Error:
        for e in view.errors():
            print(f"[qml] {e.toString()}")
        return 1

    view.setTitle("F.R.I.D.A.Y")
    view.resize(760, 460)
    view.show()
    view.setPosition(140, 120)     # despues de show(), o el gestor la reubica

    if state == "listening":
        t = QTimer()
        t.timeout.connect(bridge.pulse)
        t.start(50)
        app._t = t  # evita que el recolector se lo lleve

    print(f"  vista previa · estado «{state}» · Ctrl+C para salir")
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
