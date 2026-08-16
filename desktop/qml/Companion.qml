// El acompañante. Nucleo siempre presente; el panel de cristal se despliega
// cuando hay algo que decir y se repliega cuando no.
//
// Nada de cortes abruptos: todo entra por desvanecimiento luminoso.

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root
    width: 760
    height: 460

    // ── paleta ────────────────────────────────────────────────────
    readonly property color bgDeep:  "#0B101D"
    readonly property color bgPanel: "#121621"
    readonly property color amber:   "#FFB300"
    readonly property color gold:    "#FFD700"
    readonly property color ink:     "#E8E2D4"
    readonly property color dim:     "#8A8272"

    property bool expanded: friday.response.length > 0

    // ══════════════════════ cuadricula de fondo (hilos vectoriales)
    Canvas {
        anchors.fill: parent
        opacity: root.expanded ? 0.16 : 0.0
        Behavior on opacity { NumberAnimation { duration: 600 } }
        onPaint: {
            const ctx = getContext("2d");
            ctx.reset();
            ctx.strokeStyle = root.amber;
            ctx.lineWidth = 0.5;
            ctx.globalAlpha = 0.5;
            for (let x = 0; x < width; x += 26) {
                ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, height); ctx.stroke();
            }
            for (let y = 0; y < height; y += 26) {
                ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(width, y); ctx.stroke();
            }
        }
    }

    // ══════════════════════ panel de cristal
    Rectangle {
        id: panel
        anchors {
            left: parent.left; top: parent.top; bottom: parent.bottom
            leftMargin: 14; topMargin: 14; bottomMargin: 14
        }
        width: 470
        radius: 14
        border.width: 1
        border.color: Qt.rgba(root.amber.r, root.amber.g, root.amber.b, 0.28)

        // Placa de cristal, no una ventana. La translucidez es sutil a
        // proposito: sin desenfoque de fondo, mas transparencia solo vuelve
        // ilegible el texto contra lo que haya en el escritorio.
        gradient: Gradient {
            GradientStop { position: 0.0; color: Qt.rgba(0.055, 0.075, 0.115, 0.965) }
            GradientStop { position: 1.0; color: Qt.rgba(0.035, 0.048, 0.078, 0.935) }
        }

        opacity: root.expanded ? 1 : 0
        x: root.expanded ? 14 : -30
        visible: opacity > 0.01
        Behavior on opacity { NumberAnimation { duration: 380; easing.type: Easing.OutCubic } }
        Behavior on x { NumberAnimation { duration: 420; easing.type: Easing.OutCubic } }

        // filo superior luminoso
        Rectangle {
            anchors { top: parent.top; left: parent.left; right: parent.right }
            anchors.margins: 1
            height: 1
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0.0; color: "transparent" }
                GradientStop { position: 0.5; color: root.gold }
                GradientStop { position: 1.0; color: "transparent" }
            }
            opacity: 0.7
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 18
            spacing: 10

            // ── encabezado ────────────────────────────────────────
            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                Rectangle {
                    width: 6; height: 6; radius: 3
                    color: root.gold
                    opacity: friday.state === "idle" ? 0.5 : 1.0
                    Behavior on opacity { NumberAnimation { duration: 300 } }
                }
                Text {
                    text: "F.R.I.D.A.Y"
                    color: root.amber
                    font { family: "Cascadia Mono, Consolas, monospace"; pixelSize: 11; letterSpacing: 3.4; bold: true }
                }
                Item { Layout.fillWidth: true }

                // Quien esta pensando. Se puede cambiar hablando, asi que
                // tiene que verse: un cambio de modelo invisible es un cambio
                // en el que no puedes confiar.
                Text {
                    text: friday.model
                    color: root.gold
                    opacity: 0.75
                    visible: text.length > 0
                    font { family: "Cascadia Mono, Consolas, monospace"; pixelSize: 10; letterSpacing: 1.2 }
                }
                Rectangle {
                    width: 1; height: 9
                    visible: friday.model.length > 0 && friday.skill.length > 0
                    color: Qt.rgba(root.amber.r, root.amber.g, root.amber.b, 0.3)
                }
                Text {
                    text: friday.skill
                    color: root.dim
                    font { family: "Cascadia Mono, Consolas, monospace"; pixelSize: 10; letterSpacing: 1.6 }
                }
            }

            Rectangle {
                Layout.fillWidth: true; height: 1
                color: Qt.rgba(root.amber.r, root.amber.g, root.amber.b, 0.15)
            }

            // ── respuesta ─────────────────────────────────────────
            Flickable {
                id: flick
                Layout.fillWidth: true
                Layout.fillHeight: true
                contentWidth: width
                contentHeight: body.implicitHeight
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                TextEdit {
                    id: body
                    width: flick.width
                    text: friday.response
                    textFormat: TextEdit.MarkdownText
                    wrapMode: TextEdit.Wrap
                    readOnly: true
                    selectByMouse: true
                    color: root.ink
                    selectionColor: Qt.rgba(root.amber.r, root.amber.g, root.amber.b, 0.35)
                    font { family: "Segoe UI, Inter, sans-serif"; pixelSize: 14 }

                    onTextChanged: {
                        flick.contentY = 0;
                        fadeIn.restart();
                    }
                    NumberAnimation on opacity {
                        id: fadeIn
                        from: 0; to: 1; duration: 340; easing.type: Easing.OutCubic
                    }
                }
            }

            // ── confirmacion pendiente ────────────────────────────
            Rectangle {
                Layout.fillWidth: true
                visible: friday.pending.length > 0
                height: visible ? 46 : 0
                radius: 8
                color: Qt.rgba(root.gold.r, root.gold.g, root.gold.b, 0.10)
                border.width: 1
                border.color: Qt.rgba(root.gold.r, root.gold.g, root.gold.b, 0.45)
                Behavior on height { NumberAnimation { duration: 240 } }

                RowLayout {
                    anchors.fill: parent
                    anchors.margins: 9
                    spacing: 8

                    Text {
                        Layout.fillWidth: true
                        text: friday.pending
                        color: root.gold
                        elide: Text.ElideRight
                        font { family: "Cascadia Mono, Consolas, monospace"; pixelSize: 11 }
                    }
                    GlowButton { label: "confirmar"; onClicked: friday.confirm() }
                    GlowButton { label: "cancelar"; subdued: true; onClicked: friday.cancel() }
                }
            }

            // ── entrada ───────────────────────────────────────────
            Rectangle {
                Layout.fillWidth: true
                height: 38
                radius: 9
                color: Qt.rgba(1, 1, 1, 0.04)
                border.width: 1
                border.color: input.activeFocus
                    ? Qt.rgba(root.gold.r, root.gold.g, root.gold.b, 0.55)
                    : Qt.rgba(root.amber.r, root.amber.g, root.amber.b, 0.18)
                Behavior on border.color { ColorAnimation { duration: 200 } }

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 12
                    anchors.rightMargin: 12
                    spacing: 8

                    Text {
                        text: "›"
                        color: root.gold
                        font { family: "Cascadia Mono, Consolas, monospace"; pixelSize: 16 }
                    }
                    TextInput {
                        id: input
                        Layout.fillWidth: true
                        color: root.ink
                        selectionColor: Qt.rgba(root.amber.r, root.amber.g, root.amber.b, 0.35)
                        font { family: "Segoe UI, Inter, sans-serif"; pixelSize: 13 }
                        clip: true

                        onAccepted: {
                            if (text.trim().length > 0) { friday.submit(text); text = ""; }
                        }

                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: friday.ptt
                                ? "escribe, o " + friday.ptt + " y habla"
                                : "escribe tu peticion"
                            color: root.dim
                            visible: !input.text && !input.activeFocus
                            font: input.font
                        }
                    }
                }
            }
        }
    }

    // ══════════════════════ el nucleo
    Item {
        id: orbHost
        width: 268
        height: 268
        anchors {
            right: parent.right
            verticalCenter: parent.verticalCenter
            rightMargin: 12
        }

        HoloCore {
            id: holo
            anchors.fill: parent
            state_: friday.state
            level: friday.level
            base: 96
        }

        // arrastrar la ventana desde el nucleo
        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.LeftButton | Qt.RightButton
            cursorShape: Qt.OpenHandCursor
            onPressed: (m) => { if (m.button === Qt.LeftButton) appWindow.startSystemMove(); }
            onClicked: (m) => { if (m.button === Qt.RightButton) trayMenu.popup(); }
            onDoubleClicked: input.forceActiveFocus()
        }
    }

    // ══════════════════════ estado bajo el nucleo
    Text {
        anchors { horizontalCenter: orbHost.horizontalCenter; top: orbHost.bottom; topMargin: -18 }
        text: friday.state === "listening" ? "escuchando"
            : friday.state === "thinking"  ? "sincronizando capas"
            : friday.state === "speaking"  ? "transmitiendo"
            : friday.state === "waiting"   ? "esperando confirmacion"
            : friday.state === "error"     ? "anomalia"
            : ""
        color: root.dim
        font { family: "Cascadia Mono, Consolas, monospace"; pixelSize: 10; letterSpacing: 2.4 }
        opacity: text.length > 0 ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 300 } }
    }

    Menu {
        id: trayMenu
        MenuItem { text: "Escribir…"; onTriggered: input.forceActiveFocus() }
        MenuItem { text: "Ocultar panel"; onTriggered: friday.submit("cancela") }
        MenuItem { text: "Salir"; onTriggered: Qt.quit() }
    }
}
