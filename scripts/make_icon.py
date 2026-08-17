"""Genera el .ico del lanzador con el mismo pincel que el icono de bandeja.

Reutiliza `desktop/sprites.py::glow` en vez de pintar un circulo nuevo. Si
manana cambia el nucleo, el acceso directo y la bandeja siguen siendo la
misma naranja — que es justo lo que se rompe cuando cada uno tiene su propio
degradado a ojo.

    python scripts/make_icon.py [salida.ico]
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QBuffer, QByteArray, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter

# Windows escoge el tamaño segun el contexto: barra de tareas, escritorio,
# lista de detalles. Un .ico con un solo tamaño se ve borroso en el resto.
TAMANOS = (16, 24, 32, 48, 64, 128, 256)


def marco(lado: int) -> QImage:
    """El nucleo: halo dorado con dos anillos, sobre fondo transparente."""
    from desktop.sprites import glow

    img = QImage(lado, lado, QImage.Format_ARGB32)
    img.fill(Qt.transparent)

    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    # El halo del nucleo, ya afinado en sprites.py
    p.drawImage(0, 0, glow(lado).scaled(lado, lado, Qt.IgnoreAspectRatio,
                                        Qt.SmoothTransformation))

    # Dos anillos para que se lea como giroscopio y no como una bola.
    # Por debajo de 24 px las lineas se emborronan y estorban mas que suman.
    if lado >= 24:
        p.setBrush(Qt.NoBrush)
        ancho = max(1.0, lado / 42.0)
        pluma = p.pen()
        pluma.setWidthF(ancho)
        pluma.setColor(QColor(255, 190, 90, 200))
        p.setPen(pluma)
        m = lado * 0.13
        p.drawEllipse(int(m), int(m), int(lado - 2 * m), int(lado - 2 * m))
        pluma.setColor(QColor(255, 215, 130, 140))
        p.setPen(pluma)
        m2 = lado * 0.26
        p.drawEllipse(int(m2), int(lado * 0.34), int(lado - 2 * m2), int(lado * 0.32))
    p.end()
    return img


def main() -> int:
    destino = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "desktop" / "friday.ico"
    destino.parent.mkdir(parents=True, exist_ok=True)

    # QPainter necesita una aplicacion Qt viva aunque no se abra ventana.
    app = QGuiApplication.instance() or QGuiApplication([])

    # Qt no escribe .ico multi-tamaño, asi que se arma el contenedor a mano:
    # cabecera de 6 bytes, una entrada de 16 por tamaño, y los PNG detras.
    pngs: list[bytes] = []
    for lado in TAMANOS:
        # El QByteArray va en su propia variable a proposito: pasarlo como
        # temporal a QBuffer lo deja sin referencias del lado de Python, el
        # recolector se lo lleva, y QBuffer escribe sobre memoria liberada.
        # Sintoma: segfault, sin traza y sin mensaje.
        crudo = QByteArray()
        buf = QBuffer(crudo)
        buf.open(QBuffer.WriteOnly)
        # QImage.save basta y no exige QGuiApplication como QPixmap.
        marco(lado).save(buf, "PNG")
        buf.close()
        pngs.append(bytes(crudo))

    cabecera = b"\x00\x00\x01\x00" + len(TAMANOS).to_bytes(2, "little")
    desplazamiento = 6 + 16 * len(TAMANOS)
    entradas, cuerpo = b"", b""
    for lado, png in zip(TAMANOS, pngs):
        entradas += bytes([
            0 if lado >= 256 else lado,     # 0 significa 256
            0 if lado >= 256 else lado,
            0, 0,                           # paleta y reservado
        ])
        entradas += (1).to_bytes(2, "little")        # planos
        entradas += (32).to_bytes(2, "little")       # bits por pixel
        entradas += len(png).to_bytes(4, "little")
        entradas += desplazamiento.to_bytes(4, "little")
        desplazamiento += len(png)
        cuerpo += png

    destino.write_bytes(cabecera + entradas + cuerpo)
    print(f"  icono: {destino}  ({destino.stat().st_size / 1024:.1f} KB, "
          f"{len(TAMANOS)} tamanos)")
    # Sin `del app`: desmontar QGuiApplication a mano aqui vuelve a
    # segfaultar. Que el interprete se cierre y Qt caiga con el.
    return 0


if __name__ == "__main__":
    sys.exit(main())
