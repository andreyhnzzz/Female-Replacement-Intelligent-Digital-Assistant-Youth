// Plan B del nucleo: sin QtQuick3D.
//
// Existe porque la escena 3D depende de tres cosas que pueden faltar —el
// modulo QtQuick3D, un backend RHI que acepte post-proceso, y un driver que
// no se atragante con una ventana translucida. Cuando alguna falla, lo peor
// posible es un acompanante sin cara.
//
// Esta version es 2.5D: anillos concentricos aplastados y girando en ejes
// distintos. No tiene profundidad real —los anillos del fondo no pasan por
// detras del nucleo— pero reacciona al estado igual y corre en cualquier GPU.
//
// Se activa con `[desktop.core] mode = "projected"` en el toml.

import QtQuick

Item {
    id: fallback

    property string state_: "idle"
    property real   level: 0.0
    property real   base: 96

    // Los ajustes 3D se aceptan y se ignoran a proposito: asi
    // `HoloCore` pasa el mismo bloque de config a las dos implementaciones
    // sin tener que saber cual esta viva.
    property int  nodes: 0
    property int  spokes: 0
    property int  dust: 0
    property bool bloom: false
    property bool depthField: false
    property real fov: 0

    Orb {
        anchors.centerIn: parent
        state_: fallback.state_
        level: fallback.level
        base: fallback.base
    }
}
