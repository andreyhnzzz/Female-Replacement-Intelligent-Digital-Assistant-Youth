// Boton de cristal con resplandor. Sin cortes: todo por transicion.

import QtQuick

Rectangle {
    id: btn

    property string label: ""
    property bool subdued: false
    signal clicked()

    readonly property color amber: "#FFB300"
    readonly property color gold: "#FFD700"

    implicitWidth: text.implicitWidth + 22
    implicitHeight: 26
    radius: 6

    color: area.containsMouse
        ? Qt.rgba(gold.r, gold.g, gold.b, subdued ? 0.12 : 0.22)
        : Qt.rgba(gold.r, gold.g, gold.b, subdued ? 0.04 : 0.10)
    border.width: 1
    border.color: Qt.rgba(gold.r, gold.g, gold.b, area.containsMouse ? 0.75 : 0.35)

    Behavior on color { ColorAnimation { duration: 180 } }
    Behavior on border.color { ColorAnimation { duration: 180 } }
    scale: area.pressed ? 0.96 : 1.0
    Behavior on scale { NumberAnimation { duration: 110 } }

    Text {
        id: text
        anchors.centerIn: parent
        text: btn.label
        color: btn.subdued ? "#8A8272" : btn.gold
        font { family: "Cascadia Mono, Consolas, monospace"; pixelSize: 11; letterSpacing: 1.2 }
    }

    MouseArea {
        id: area
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: btn.clicked()
    }
}
