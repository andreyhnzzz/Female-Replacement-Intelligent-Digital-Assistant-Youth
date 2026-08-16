"""Geometria del nucleo holografico, generada en Python.

QML no sabe construir mallas. Qt Quick 3D expone `QQuick3DGeometry` para eso:
se rellena un buffer de vertices y se declara que significa cada tramo. Aqui
se construyen las tres piezas que dan la estructura del holograma:

    WireGlobe      meridianos y paralelos — el armazon esferico
    RadialSpokes   los radios que salen del nucleo hacia la superficie
    DataArcs       arcos y cuerdas sueltas — la textura de «datos vivos»

Todo son **lineas**, no triangulos. Un holograma no tiene superficie: tiene
aristas que brillan. Las lineas ademas cuestan una fraccion de lo que cuesta
una malla equivalente y no necesitan normales ni iluminacion.

Los nodos luminosos NO se construyen aqui: son particulas (`SpriteParticle3D`),
porque tienen que reaccionar al estado y un buffer estatico no reacciona.

Cada vertice lleva posicion y color. El color por vertice es lo que hace que
la esfera se apague hacia los polos y hacia el fondo sin necesidad de un
shader propio: es un degradado horneado en la malla.
"""
from __future__ import annotations

import math
import random
import struct

from PySide6.QtCore import Property, QByteArray, Signal
from PySide6.QtGui import QVector3D
from PySide6.QtQml import QmlElement
from PySide6.QtQuick3D import QQuick3DGeometry

QML_IMPORT_NAME = "Friday.Geometry"
QML_IMPORT_MAJOR_VERSION = 1

# posicion (3f) + color (4f)
_STRIDE = 7 * 4


class _LineGeometry(QQuick3DGeometry):
    """Base: acumula segmentos y los sube como un buffer de lineas.

    Las subclases solo implementan `_build`, que llama a `_line` tantas veces
    como haga falta. El empaquetado, los limites y el ciclo de invalidacion
    viven aqui una sola vez.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._radius = 100.0
        self._seed = 7
        self._buf = bytearray()
        self._extent = 1.0
        self.rebuild()

    # ── API para las subclases ────────────────────────────────────
    def _line(self, a: tuple[float, float, float], b: tuple[float, float, float],
              ca: tuple[float, float, float, float],
              cb: tuple[float, float, float, float] | None = None) -> None:
        cb = cb if cb is not None else ca
        self._buf += struct.pack("<7f", *a, *ca)
        self._buf += struct.pack("<7f", *b, *cb)
        for v in (a, b):
            self._extent = max(self._extent, abs(v[0]), abs(v[1]), abs(v[2]))

    def _build(self) -> None:                     # pragma: no cover - abstracto
        raise NotImplementedError

    # ── ciclo ─────────────────────────────────────────────────────
    def rebuild(self) -> None:
        self._buf = bytearray()
        self._extent = 1.0
        random.seed(self._seed)
        self._build()

        self.clear()
        self.setStride(_STRIDE)
        self.setVertexData(QByteArray(bytes(self._buf)))
        self.setPrimitiveType(QQuick3DGeometry.PrimitiveType.Lines)
        self.addAttribute(QQuick3DGeometry.Attribute.PositionSemantic, 0,
                          QQuick3DGeometry.Attribute.F32Type)
        self.addAttribute(QQuick3DGeometry.Attribute.ColorSemantic, 3 * 4,
                          QQuick3DGeometry.Attribute.F32Type)
        e = self._extent
        self.setBounds(QVector3D(-e, -e, -e), QVector3D(e, e, e))
        self.update()

    # ── propiedades comunes ───────────────────────────────────────
    radiusChanged = Signal()
    seedChanged = Signal()

    def _get_radius(self) -> float:
        return self._radius

    def _set_radius(self, v: float) -> None:
        if abs(v - self._radius) > 1e-6:
            self._radius = float(v)
            self.radiusChanged.emit()
            self.rebuild()

    radius = Property(float, _get_radius, _set_radius, notify=radiusChanged)

    def _get_seed(self) -> int:
        return self._seed

    def _set_seed(self, v: int) -> None:
        if v != self._seed:
            self._seed = int(v)
            self.seedChanged.emit()
            self.rebuild()

    seed = Property(int, _get_seed, _set_seed, notify=seedChanged)


@QmlElement
class WireGlobe(_LineGeometry):
    """El armazon: paralelos y meridianos.

    Los paralelos no se reparten uniformemente en latitud sino en **seno** de
    latitud. Repartirlos uniformemente amontona anillos en los polos, que es
    justo donde menos informacion hay, y deja el ecuador desnudo.
    """

    ringsChanged = Signal()
    meridiansChanged = Signal()
    segmentsChanged = Signal()

    def __init__(self, parent=None):
        self._rings = 9
        self._meridians = 18
        self._segments = 64
        super().__init__(parent)

    def _build(self) -> None:
        r = self._radius
        # Paralelos
        for i in range(1, self._rings + 1):
            t = i / (self._rings + 1)
            lat = math.asin(2.0 * t - 1.0)          # denso en el ecuador
            y = r * math.sin(lat)
            rr = r * math.cos(lat)
            # El ecuador es el eje de lectura del objeto: si todos los
            # paralelos pesan igual, la esfera se lee como un ovillo.
            equator = abs(lat) < 1e-3
            fade = 1.0 if equator else 0.22 + 0.55 * math.cos(lat) ** 2
            prev = None
            for s in range(self._segments + 1):
                a = (s / self._segments) * math.tau
                p = (rr * math.cos(a), y, rr * math.sin(a))
                if prev is not None:
                    self._line(prev, p, self._tint(fade, prev), self._tint(fade, p))
                prev = p

        # Meridianos
        for m in range(self._meridians):
            phi = (m / self._meridians) * math.tau
            strong = (m % 3 == 0)
            fade = 0.72 if strong else 0.20
            prev = None
            steps = self._segments
            for s in range(steps + 1):
                lat = -math.pi / 2 + (s / steps) * math.pi
                p = (r * math.cos(lat) * math.cos(phi),
                     r * math.sin(lat),
                     r * math.cos(lat) * math.sin(phi))
                if prev is not None:
                    self._line(prev, p, self._tint(fade, prev), self._tint(fade, p))
                prev = p

    @staticmethod
    def _tint(alpha: float, p: tuple[float, float, float]) -> tuple[float, float, float, float]:
        """Oro al frente, ambar profundo al fondo.

        La `z` decide: lo que viene hacia la camara arde, lo que se va se
        enfria. Es niebla de profundidad horneada en el vertice — mas barata
        que cualquier efecto y funciona aunque el post-proceso este apagado.

        El verde nunca baja de 0.66: por debajo el ambar vira a rojo ladrillo
        y el holograma deja de parecer oro para parecer oxido.
        """
        depth = max(0.0, min(1.0, (p[2] + 120.0) / 240.0))
        return (1.0, 0.66 + 0.26 * depth, 0.20 + 0.42 * depth, alpha)

    def _get_rings(self) -> int:
        return self._rings

    def _set_rings(self, v: int) -> None:
        if v != self._rings:
            self._rings = max(0, int(v))
            self.ringsChanged.emit()
            self.rebuild()

    rings = Property(int, _get_rings, _set_rings, notify=ringsChanged)

    def _get_meridians(self) -> int:
        return self._meridians

    def _set_meridians(self, v: int) -> None:
        if v != self._meridians:
            self._meridians = max(0, int(v))
            self.meridiansChanged.emit()
            self.rebuild()

    meridians = Property(int, _get_meridians, _set_meridians, notify=meridiansChanged)

    def _get_segments(self) -> int:
        return self._segments

    def _set_segments(self, v: int) -> None:
        if v != self._segments:
            self._segments = max(8, int(v))
            self.segmentsChanged.emit()
            self.rebuild()

    segments = Property(int, _get_segments, _set_segments, notify=segmentsChanged)


@QmlElement
class RadialSpokes(_LineGeometry):
    """Los radios: del nucleo incandescente hacia la superficie.

    Se reparten con la espiral de Fibonacci sobre la esfera, no al azar. El
    azar puro deja calvas y grumos visibles de inmediato en una esfera; la
    espiral da una distribucion pareja que aun asi no se lee como una rejilla.
    """

    countChanged = Signal()
    innerChanged = Signal()

    def __init__(self, parent=None):
        self._count = 28
        self._inner = 0.14
        super().__init__(parent)

    def _build(self) -> None:
        r = self._radius
        n = max(1, self._count)
        golden = math.pi * (3.0 - math.sqrt(5.0))
        for i in range(n):
            y = 1.0 - (i / max(1, n - 1)) * 2.0
            rr = math.sqrt(max(0.0, 1.0 - y * y))
            phi = i * golden
            direction = (math.cos(phi) * rr, y, math.sin(phi) * rr)

            reach = r * random.uniform(0.74, 1.04)
            start = tuple(c * r * self._inner for c in direction)
            end = tuple(c * reach for c in direction)

            # El radio nace blanco y muere en ambar: la luz sale del nucleo.
            # La opacidad inicial es 1.0 y la final 0.0 — el degradado es lo
            # que da la sensacion de emision y no de jaula de alambre.
            self._line(start, end, (1.0, 0.97, 0.86, 1.0),
                       (1.0, 0.62, 0.12, 0.0))

    def _get_count(self) -> int:
        return self._count

    def _set_count(self, v: int) -> None:
        if v != self._count:
            self._count = max(0, int(v))
            self.countChanged.emit()
            self.rebuild()

    count = Property(int, _get_count, _set_count, notify=countChanged)

    def _get_inner(self) -> float:
        return self._inner

    def _set_inner(self, v: float) -> None:
        if abs(v - self._inner) > 1e-6:
            self._inner = float(v)
            self.innerChanged.emit()
            self.rebuild()

    inner = Property(float, _get_inner, _set_inner, notify=innerChanged)


@QmlElement
class DataArcs(_LineGeometry):
    """Arcos sueltos sobre la superficie: trayectorias, rutas, conexiones.

    Es la capa que hace que el objeto parezca estar *procesando* algo y no
    solo girando. Deliberadamente ilegible: sugiere un sistema complejo sin
    afirmar ningun dato concreto. Un holograma que pretendiera mostrar cifras
    reales estaria mintiendo, porque no las tiene.
    """

    countChanged = Signal()

    def __init__(self, parent=None):
        self._count = 34
        super().__init__(parent)

    def _build(self) -> None:
        r = self._radius
        for _ in range(self._count):
            a = self._on_sphere(r)
            b = self._on_sphere(r)
            steps = 14
            # Los arcos van pegados a la superficie. Despegarlos mas los
            # convierte en un ovillo de cuerdas por fuera del globo, que es
            # exactamente lo contrario de «trayectorias sobre un mapa».
            lift = random.uniform(1.005, 1.045)
            prev = None
            for s in range(steps + 1):
                t = s / steps
                p = self._slerp(a, b, t)
                bulge = lift + 0.035 * math.sin(t * math.pi)
                p = (p[0] * bulge, p[1] * bulge, p[2] * bulge)
                if prev is not None:
                    edge = math.sin(t * math.pi)   # se desvanece en los extremos
                    c = (1.0, 0.78, 0.30, 0.10 + 0.34 * edge)
                    self._line(prev, p, c)
                prev = p

            # nodo en cada extremo: una pequeña antena hacia fuera
            for end in (a, b):
                tip = (end[0] * 1.01, end[1] * 1.01, end[2] * 1.01)
                out = (end[0] * 1.07, end[1] * 1.07, end[2] * 1.07)
                self._line(tip, out, (1.0, 0.93, 0.62, 0.90), (1.0, 0.64, 0.14, 0.0))

    @staticmethod
    def _on_sphere(r: float) -> tuple[float, float, float]:
        z = random.uniform(-1.0, 1.0)
        phi = random.uniform(0.0, math.tau)
        rr = math.sqrt(max(0.0, 1.0 - z * z))
        return (r * rr * math.cos(phi), r * z, r * rr * math.sin(phi))

    @staticmethod
    def _slerp(a, b, t: float):
        """Interpolacion sobre la esfera. Con lerp recto los arcos cortarian
        por dentro del globo y se verian como cuerdas, no como rutas."""
        na = math.sqrt(sum(c * c for c in a)) or 1.0
        ua = [c / na for c in a]
        ub = [c / (math.sqrt(sum(c * c for c in b)) or 1.0) for c in b]
        dot = max(-1.0, min(1.0, sum(x * y for x, y in zip(ua, ub))))
        omega = math.acos(dot)
        if omega < 1e-4:
            return a
        s = math.sin(omega)
        w1, w2 = math.sin((1 - t) * omega) / s, math.sin(t * omega) / s
        return tuple((ua[i] * w1 + ub[i] * w2) * na for i in range(3))

    def _get_count(self) -> int:
        return self._count

    def _set_count(self, v: int) -> None:
        if v != self._count:
            self._count = max(0, int(v))
            self.countChanged.emit()
            self.rebuild()

    count = Property(int, _get_count, _set_count, notify=countChanged)
