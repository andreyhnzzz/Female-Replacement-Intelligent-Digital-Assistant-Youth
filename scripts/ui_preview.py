"""Previsualiza el acompañante sin arrancar el nucleo.

Carga solo el QML con datos de muestra: sin motor, sin voz, sin acceso al
sistema. Sirve para iterar el diseño en segundos en vez de esperar a que
cargue el modelo de voz.

    python scripts/ui_preview.py                 estado inactivo
    python scripts/ui_preview.py listening       el nucleo escuchando
    python scripts/ui_preview.py thinking        procesando: los nodos hierven
                                                 y van saliendo picos, uno
                                                 cada 1,2 s hasta el tope
    python scripts/ui_preview.py waiting         con confirmacion pendiente

    python scripts/ui_preview.py thinking --shot nucleo.png
        deja que la escena se asiente, guarda un PNG y sale. Una escena 3D
        con particulas y post-proceso no se puede validar leyendo el QML:
        hay que mirarla. Esto permite mirarla sin ojos humanos delante y
        comparar dos versiones lado a lado.

    python scripts/ui_preview.py thinking --picos 14 --shot erizado.png
        cuantos picos de pensamiento lleva acumulados. Sirve para ver el
        extremo —una espera larguisima— sin esperarla.

    python scripts/ui_preview.py idle --projected
        fuerza el plan B en 2.5D aunque QtQuick3D este disponible.
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

from core.config import load as load_config
from desktop.sprites import PROVIDER_ID, SpriteProvider

try:
    from desktop import geometry as _geometry     # registra los tipos QML
    GEOMETRY_OK = True
except Exception as _exc:                          # pragma: no cover
    GEOMETRY_OK = False
    print(f"[preview] sin QtQuick3D: {_exc}")

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
    modelChanged = Signal()
    pttChanged = Signal()
    effortChanged = Signal()
    thoughtsChanged = Signal()
    logAppended = Signal(str, str)

    def __init__(self, state: str = "idle", ptt: str = "pulsa F9", picos: int = 6):
        super().__init__()
        self._state = state
        self._level = 0.0
        self._ptt = ptt
        self._pending = ("organizar Downloads: 199 movimientos"
                         if state == "waiting" else "")
        # Los picos arrancan a media altura en «thinking»: una captura a los
        # 2,6 s con el contador desde cero saldria con una aguja o ninguna,
        # que es justo lo que no hay que mirar.
        self._thoughts = picos if state == "thinking" else 0
        self._effort = min(1.0, picos / 12.0) if state == "thinking" else 0.0

    state = Property(str, lambda s: s._state, notify=stateChanged)
    level = Property(float, lambda s: s._level, notify=levelChanged)
    effort = Property(float, lambda s: s._effort, notify=effortChanged)
    thoughts = Property(int, lambda s: s._thoughts, notify=thoughtsChanged)
    transcript = Property(str, lambda s: "organiza mis descargas",
                          notify=transcriptChanged)
    response = Property(str, lambda s: DEMO, notify=responseChanged)
    pending = Property(str, lambda s: s._pending, notify=pendingChanged)
    status = Property(str, lambda s: "vista previa", notify=statusChanged)
    skill = Property(str, lambda s: "archivos · 167ms", notify=responseChanged)
    model = Property(str, lambda s: "Opus 5", notify=modelChanged)
    ptt = Property(str, lambda s: s._ptt, notify=pttChanged)

    def pulse(self) -> None:
        """Simula el nivel de audio para ver reaccionar al nucleo."""
        import math
        import time
        self._level = abs(math.sin(time.time() * 3)) * 0.5
        self.levelChanged.emit()

    def think(self) -> None:
        """Un pico mas, como si la tarea siguiera sin volver.

        Al llegar al tope vuelve a cero: en vivo interesa ver el brote de la
        aguja nueva una y otra vez, no dejar el globo erizado y quieto.
        """
        self._thoughts = 0 if self._thoughts >= 14 else self._thoughts + 1
        self._effort = min(1.0, self._thoughts / 12.0)
        self.thoughtsChanged.emit()
        self.effortChanged.emit()

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


def hud_config(force_projected: bool) -> dict:
    """Mismo bloque que arma `desktop/app.py`, leido del toml de verdad."""
    try:
        cfg = load_config()
        conf = {
            "mode": str(cfg.get("desktop.core.mode", "quick3d")),
            "nodes": int(cfg.get("desktop.core.nodes", 1400)),
            "spokes": int(cfg.get("desktop.core.spokes", 28)),
            "dust": int(cfg.get("desktop.core.dust", 260)),
            "bloom": bool(cfg.get("desktop.core.bloom", True)),
            "depth_field": bool(cfg.get("desktop.core.depth_field", True)),
            "fov": float(cfg.get("desktop.core.fov", 42)),
        }
        ptt = cfg.ptt_hint()
    except Exception:
        conf = {"mode": "quick3d", "nodes": 1400, "spokes": 28, "dust": 260,
                "bloom": True, "depth_field": True, "fov": 42.0}
        ptt = "pulsa F9"

    if force_projected or not GEOMETRY_OK:
        conf["mode"] = "projected"
    return conf, ptt


def main() -> int:
    args = [a for a in sys.argv[1:]]
    shot = ""
    if "--shot" in args:
        i = args.index("--shot")
        shot = args[i + 1] if i + 1 < len(args) else "preview.png"
        del args[i:i + 2]
    picos = 6
    if "--picos" in args:
        i = args.index("--picos")
        picos = int(args[i + 1]) if i + 1 < len(args) else 6
        del args[i:i + 2]
    projected = "--projected" in args
    args = [a for a in args if not a.startswith("--")]
    state = args[0] if args else "idle"

    app = QApplication([])
    conf, ptt = hud_config(projected)

    bridge = MockBridge(state, ptt, picos)
    view = QQuickView()
    view.setFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
    view.setColor(QColor(0, 0, 0, 0))
    view.setResizeMode(QQuickView.SizeRootObjectToView)

    ctx = view.rootContext()
    ctx.setContextProperty("friday", bridge)
    ctx.setContextProperty("appWindow", view)
    ctx.setContextProperty("hudCfg", conf)

    qml = ROOT / "desktop" / "qml"
    view.engine().addImportPath(str(qml))
    view.engine().addImageProvider(PROVIDER_ID, SpriteProvider())
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

    if state == "thinking" and not shot:
        t = QTimer()
        t.timeout.connect(bridge.think)
        t.start(1200)
        app._tp = t

    if shot:
        # Las particulas tardan en emitirse y el post-proceso necesita un par
        # de cuadros: capturar de inmediato daria una esfera vacia.
        def capture() -> None:
            img = view.grabWindow()
            path = Path(shot)
            if not path.is_absolute():
                path = Path.cwd() / path
            ok = img.save(str(path))
            print(f"  captura {'guardada en' if ok else 'FALLO en'} {path}")
            app.quit()

        QTimer.singleShot(2600, capture)
        print(f"  capturando «{state}» · modo {conf['mode']}…")
        return app.exec()

    print(f"  vista previa · estado «{state}» · nucleo {conf['mode']} · Ctrl+C para salir")
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
