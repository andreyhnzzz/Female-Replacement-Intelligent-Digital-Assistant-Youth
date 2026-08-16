"""Texturas del nucleo, pintadas en memoria.

Un nodo holografico no es un punto: es un punto **con halo**. Sin el halo,
la nube se ve como ruido de sal y pimienta; con el, se ve como luz. Y el
post-proceso de brillo necesita algo que desbordar — un pixel duro no
desborda nada.

Se generan en Python y se sirven por `image://friday/...` en vez de guardar
PNG en el repo. Dos razones: el radio y el degradado se afinan cambiando una
linea en vez de reexportando un asset, y no hay archivos binarios que revisar
en un diff.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QRadialGradient
from PySide6.QtQuick import QQuickImageProvider

PROVIDER_ID = "friday"


def glow(size: int = 64, core: float = 0.14, warmth: float = 1.0) -> QImage:
    """Disco con caida suave. `core` es la fraccion que va a blanco puro.

    La caida no es lineal: tres paradas intermedias imitan el perfil de una
    fuente puntual vista a traves de una lente. Un degradado lineal se ve
    plano y delata inmediatamente que es un circulo dibujado.
    """
    img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)

    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)

    half = size / 2.0
    grad = QRadialGradient(half, half, half)
    grad.setColorAt(0.0, QColor(255, 253, 245, 255))
    grad.setColorAt(max(0.02, core), QColor(255, 236, 190, 235))
    grad.setColorAt(0.34, QColor(255, int(190 * warmth), 60, 150))
    grad.setColorAt(0.62, QColor(255, int(150 * warmth), 20, 52))
    grad.setColorAt(1.0, QColor(255, 130, 0, 0))

    p.setBrush(grad)
    p.setPen(Qt.NoPen)
    p.drawEllipse(0, 0, size, size)
    p.end()
    return img


def spark(size: int = 32) -> QImage:
    """Chispa alargada para el polvo orbital: mas nerviosa que un disco."""
    img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)

    half = size / 2.0
    grad = QRadialGradient(half, half, half)
    grad.setColorAt(0.0, QColor(255, 255, 240, 255))
    grad.setColorAt(0.45, QColor(255, 200, 90, 120))
    grad.setColorAt(1.0, QColor(255, 150, 20, 0))
    p.setBrush(grad)
    p.setPen(Qt.NoPen)
    p.drawEllipse(int(size * 0.30), 0, int(size * 0.40), size)
    p.end()
    return img


class SpriteProvider(QQuickImageProvider):
    """Sirve `image://friday/glow` y `image://friday/spark`."""

    def __init__(self) -> None:
        super().__init__(QQuickImageProvider.Image)

    def requestImage(self, sprite_id: str, size: QSize, requested: QSize) -> QImage:
        side = requested.width() if requested.width() > 0 else 64
        name = (sprite_id or "").split("?")[0].lower()

        img = spark(max(16, side)) if name == "spark" else glow(max(16, side))
        if size is not None:
            size.setWidth(img.width())
            size.setHeight(img.height())
        return img
