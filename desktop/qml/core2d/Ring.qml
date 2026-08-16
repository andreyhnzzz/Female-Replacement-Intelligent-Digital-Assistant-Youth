// Un anillo del giroscopio.
//
// Clave de rendimiento: el Canvas se pinta UNA vez y despues solo se anima
// su rotacion. Qt Quick reutiliza la textura, asi que la animacion vive en
// el hilo de render (GPU) y no vuelve a ejecutar JavaScript ni un frame.
// Por eso el orbe puede girar todo el dia sin calentar el CPU.

import QtQuick

Item {
    id: ring

    property real radius: 80
    property color tint: "#FFB300"
    property real thickness: 1.4
    property real alpha: 0.85
    property int  variant: 0        // 0 ticks · 1 segmentos · 2 bloques · 3 circuito
    property int  density: 48
    property real period: 18000     // ms por vuelta
    property bool reverse: false
    property real tilt: 0           // aplastado vertical: ilusion 3D

    width: radius * 2
    height: radius * 2
    anchors.centerIn: parent

    transform: Scale {
        origin.x: ring.width / 2
        origin.y: ring.height / 2
        yScale: 1.0 - ring.tilt
    }

    Canvas {
        id: painter
        anchors.fill: parent
        antialiasing: true
        renderStrategy: Canvas.Cooperative

        onPaint: {
            const ctx = getContext("2d");
            ctx.reset();
            const cx = width / 2, cy = height / 2, r = ring.radius - 2;
            const col = ring.tint;

            ctx.strokeStyle = col;
            ctx.fillStyle = col;
            ctx.lineWidth = ring.thickness;
            ctx.globalAlpha = ring.alpha;

            if (ring.variant === 0) {
                // ── marcas radiales: una regla de precision
                ctx.globalAlpha = ring.alpha * 0.30;
                ctx.beginPath();
                ctx.arc(cx, cy, r, 0, Math.PI * 2);
                ctx.stroke();

                for (let i = 0; i < ring.density; i++) {
                    const a = (i / ring.density) * Math.PI * 2;
                    const major = (i % 6 === 0);
                    const len = major ? 9 : 4;
                    ctx.globalAlpha = ring.alpha * (major ? 1.0 : 0.45);
                    ctx.lineWidth = major ? ring.thickness * 1.6 : ring.thickness;
                    ctx.beginPath();
                    ctx.moveTo(cx + Math.cos(a) * (r - len), cy + Math.sin(a) * (r - len));
                    ctx.lineTo(cx + Math.cos(a) * r, cy + Math.sin(a) * r);
                    ctx.stroke();
                }

            } else if (ring.variant === 1) {
                // ── segmentos tipo radar, de largo irregular
                const gaps = 7;
                for (let i = 0; i < gaps; i++) {
                    const start = (i / gaps) * Math.PI * 2;
                    const span = (Math.PI * 2 / gaps) * (0.30 + (i % 3) * 0.18);
                    ctx.globalAlpha = ring.alpha * (0.45 + (i % 2) * 0.5);
                    ctx.lineWidth = ring.thickness * (i % 2 ? 2.6 : 1.2);
                    ctx.beginPath();
                    ctx.arc(cx, cy, r, start, start + span);
                    ctx.stroke();
                }

            } else if (ring.variant === 2) {
                // ── bloques de datos: informacion codificada, ilegible a proposito
                for (let i = 0; i < ring.density; i++) {
                    if (i % 3 === 1) continue;
                    const a = (i / ring.density) * Math.PI * 2;
                    const h = 2 + (i % 5);
                    const w = 1.6 + (i % 3) * 0.9;
                    ctx.globalAlpha = ring.alpha * (0.35 + (i % 4) * 0.20);
                    ctx.save();
                    ctx.translate(cx + Math.cos(a) * r, cy + Math.sin(a) * r);
                    ctx.rotate(a + Math.PI / 2);
                    ctx.fillRect(-w / 2, -h / 2, w, h);
                    ctx.restore();
                }

            } else {
                // ── circuito: nodos conectados por cuerdas
                const nodes = [];
                const n = Math.max(8, ring.density / 4);
                for (let i = 0; i < n; i++) {
                    const a = (i / n) * Math.PI * 2;
                    const rr = r * (i % 3 === 0 ? 1.0 : 0.86);
                    nodes.push([cx + Math.cos(a) * rr, cy + Math.sin(a) * rr]);
                }
                ctx.globalAlpha = ring.alpha * 0.28;
                ctx.lineWidth = ring.thickness * 0.8;
                for (let i = 0; i < nodes.length; i++) {
                    const j = (i + 3) % nodes.length;
                    ctx.beginPath();
                    ctx.moveTo(nodes[i][0], nodes[i][1]);
                    ctx.lineTo(nodes[j][0], nodes[j][1]);
                    ctx.stroke();
                }
                ctx.globalAlpha = ring.alpha;
                for (let i = 0; i < nodes.length; i++) {
                    const s = (i % 4 === 0) ? 2.4 : 1.3;
                    ctx.beginPath();
                    ctx.arc(nodes[i][0], nodes[i][1], s, 0, Math.PI * 2);
                    ctx.fill();
                }
            }
        }

        // repintar solo cuando cambia el aspecto, nunca por frame
        Connections {
            target: ring
            function onTintChanged() { painter.requestPaint(); }
            function onAlphaChanged() { painter.requestPaint(); }
            function onRadiusChanged() { painter.requestPaint(); }
        }
    }

    // Animator: corre en el hilo de render, no bloquea la UI ni gasta JS
    RotationAnimator {
        target: ring
        from: ring.reverse ? 360 : 0
        to: ring.reverse ? 0 : 360
        duration: ring.period
        loops: Animation.Infinite
        running: true
    }
}
