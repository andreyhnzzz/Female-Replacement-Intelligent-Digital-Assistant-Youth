// El nucleo holografico de F.R.I.D.A.Y.
//
// Capas concentricas girando a distintas velocidades y en distintos ejes,
// con un nucleo incandescente al centro. El color y el ritmo responden al
// estado: escuchar acelera y aclara, pensar gira mas rapido, error vira.

import QtQuick

Item {
    id: orb

    property string state_: "idle"      // idle · listening · thinking · speaking · error · waiting
    property real   level: 0.0          // nivel de audio 0..1
    property real   base: 92            // radio exterior

    // ── paleta segun estado ───────────────────────────────────────
    readonly property color amber:  "#FFB300"
    readonly property color gold:   "#FFD700"
    readonly property color deep:   "#FF8C00"
    readonly property color danger: "#FF5F56"
    readonly property color calm:   "#FFC14D"

    readonly property color tone:
        state_ === "error"     ? danger :
        state_ === "listening" ? gold   :
        state_ === "speaking"  ? calm   : amber

    readonly property real tempo:
        state_ === "thinking"  ? 0.32 :
        state_ === "listening" ? 0.55 :
        state_ === "speaking"  ? 0.75 : 1.0

    readonly property real energy:
        state_ === "idle" ? 0.72 :
        state_ === "waiting" ? 0.85 : 1.0

    width: base * 2.4
    height: base * 2.4

    Behavior on scale { NumberAnimation { duration: 420; easing.type: Easing.OutCubic } }
    scale: state_ === "listening" ? 1.0 + orb.level * 0.55 : 1.0

    // ══════════════════ resplandor exterior (halo proyectado)
    Rectangle {
        anchors.centerIn: parent
        width: orb.base * 2.75
        height: width
        radius: width / 2
        color: "transparent"
        gradient: Gradient {
            GradientStop { position: 0.0; color: Qt.rgba(orb.tone.r, orb.tone.g, orb.tone.b, 0.0) }
            GradientStop { position: 0.62; color: Qt.rgba(orb.tone.r, orb.tone.g, orb.tone.b, 0.05 * orb.energy) }
            GradientStop { position: 1.0; color: Qt.rgba(orb.tone.r, orb.tone.g, orb.tone.b, 0.0) }
        }
        opacity: 0.9
        Behavior on opacity { NumberAnimation { duration: 500 } }
    }

    // ══════════════════ anillos: el giroscopio
    Ring {
        radius: orb.base
        tint: orb.tone
        variant: 0
        density: 60
        alpha: 0.80 * orb.energy
        period: 26000 * orb.tempo
        tilt: 0.0
    }

    Ring {
        radius: orb.base * 0.86
        tint: orb.tone
        variant: 1
        alpha: 0.95 * orb.energy
        thickness: 1.8
        period: 15000 * orb.tempo
        reverse: true
        tilt: 0.42                    // inclinado: rompe la planitud
    }

    Ring {
        radius: orb.base * 0.70
        tint: orb.gold
        variant: 2
        density: 54
        alpha: 0.70 * orb.energy
        period: 34000 * orb.tempo
        tilt: 0.18
    }

    Ring {
        radius: orb.base * 0.52
        tint: orb.tone
        variant: 3
        density: 40
        alpha: 0.85 * orb.energy
        period: 11000 * orb.tempo
        reverse: true
        tilt: 0.55
    }

    Ring {
        radius: orb.base * 0.36
        tint: orb.gold
        variant: 0
        density: 24
        alpha: 0.9 * orb.energy
        thickness: 1.0
        period: 8000 * orb.tempo
        tilt: 0.30
    }

    // ══════════════════ nucleo incandescente
    Item {
        anchors.centerIn: parent
        width: orb.base * 0.46
        height: width

        // halo suave del nucleo
        Rectangle {
            anchors.fill: parent
            radius: width / 2
            gradient: Gradient {
                GradientStop { position: 0.0; color: Qt.rgba(1, 1, 0.92, 0.95) }
                GradientStop { position: 0.30; color: Qt.rgba(orb.gold.r, orb.gold.g, orb.gold.b, 0.55) }
                GradientStop { position: 0.65; color: Qt.rgba(orb.deep.r, orb.deep.g, orb.deep.b, 0.20) }
                GradientStop { position: 1.0; color: "transparent" }
            }

            SequentialAnimation on opacity {
                loops: Animation.Infinite
                running: true
                NumberAnimation { to: 0.62; duration: 1500 * orb.tempo; easing.type: Easing.InOutSine }
                NumberAnimation { to: 1.00; duration: 1500 * orb.tempo; easing.type: Easing.InOutSine }
            }
        }

        // punto focal: de aqui emana todo
        Rectangle {
            anchors.centerIn: parent
            width: parent.width * (0.26 + orb.level * 0.30)
            height: width
            radius: width / 2
            color: "#FFFDF2"
            Behavior on width { NumberAnimation { duration: 90 } }
        }
    }

    // ══════════════════ particulas orbitales
    Repeater {
        model: 7
        delegate: Item {
            anchors.centerIn: parent
            width: orb.base * 2
            height: orb.base * 2

            Rectangle {
                x: parent.width / 2 + orb.base * (0.62 + (index % 3) * 0.14)
                y: parent.height / 2
                width: 2.6
                height: 2.6
                radius: 1.3
                color: index % 2 ? orb.gold : orb.tone
                opacity: 0.55 + (index % 4) * 0.11
            }

            RotationAnimator on rotation {
                from: index * 51
                to: index * 51 + (index % 2 ? -360 : 360)
                duration: (7000 + index * 1900) * orb.tempo
                loops: Animation.Infinite
                running: true
            }
        }
    }
}
