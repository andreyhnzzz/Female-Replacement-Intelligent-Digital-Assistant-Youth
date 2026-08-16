// Selector del nucleo. Decide que implementacion se carga y sobrevive si
// la elegida no arranca.
//
// QtQuick3D no siempre esta. Falta si PySide6 se instalo sin los addons, si
// el equipo cae al backend de software, o si el driver se pelea con el
// post-proceso sobre una ventana translucida. Cargarlo con un `Loader` en
// vez de con un `import` directo convierte ese fallo de «el QML no compila y
// no hay acompanante» en «se ve el nucleo 2.5D y hay un aviso en la
// bitacora». La diferencia entre degradar y morirse.

import QtQuick

Item {
    id: core

    property string state_: "idle"
    property real   level: 0.0
    property real   base: 96

    // Config de [desktop.core]. `hudCfg` lo inyecta Python; si no esta
    // —vista previa suelta, pruebas— se usan valores razonables.
    readonly property var conf: (typeof hudCfg !== "undefined" && hudCfg) ? hudCfg : ({})
    readonly property string mode: conf.mode || "quick3d"

    // Que se acabo usando de verdad, no que se pidio. Lo lee el panel.
    readonly property string activeMode: loader.status === Loader.Ready && !loader.failed
        ? mode : "projected"

    Loader {
        id: loader
        anchors.fill: parent
        asynchronous: false

        property bool failed: false

        source: failed || core.mode === "projected"
            ? "core2d/HoloProjected.qml"
            : "core3d/Holo3D.qml"

        onStatusChanged: {
            if (status === Loader.Error && !failed) {
                console.warn("[hud] la escena 3D no cargo; cayendo al nucleo 2.5D");
                failed = true;              // relee `source` y carga el plan B
            }
        }

        onLoaded: {
            item.state_ = Qt.binding(function () { return core.state_; });
            item.level = Qt.binding(function () { return core.level; });
            item.base = Qt.binding(function () { return core.base; });

            // Los ajustes solo se aplican si la implementacion los declara:
            // el plan B los tiene por compatibilidad, pero no los usa.
            if (item.nodes !== undefined && core.conf.nodes !== undefined)
                item.nodes = core.conf.nodes;
            if (item.spokes !== undefined && core.conf.spokes !== undefined)
                item.spokes = core.conf.spokes;
            if (item.dust !== undefined && core.conf.dust !== undefined)
                item.dust = core.conf.dust;
            if (item.bloom !== undefined && core.conf.bloom !== undefined)
                item.bloom = core.conf.bloom;
            if (item.depthField !== undefined && core.conf.depth_field !== undefined)
                item.depthField = core.conf.depth_field;
            if (item.fov !== undefined && core.conf.fov !== undefined)
                item.fov = core.conf.fov;
        }
    }
}
