// El nucleo holografico de F.R.I.D.A.Y — escena 3D real.
//
// No es un circulo con anillos aplastados: es un objeto con volumen visto
// por una camara en perspectiva. Los meridianos del fondo pasan POR DETRAS
// del nucleo, los nodos cercanos son mas grandes que los lejanos y el brillo
// se derrama sobre lo que tiene alrededor.
//
// Cuatro capas, de dentro hacia fuera:
//
//   nucleo    la fuente. Blanco caliente, respira.
//   radios    lineas que salen del nucleo hacia la superficie.
//   armazon   meridianos y paralelos — la estructura del globo.
//   nodos     la nube de puntos luminosos. ESTA es la que reacciona.
//   picos     las agujas del pensamiento. Solo salen cuando algo tarda.
//
// La reaccion de los nodos no es un cambio de color: al pensar se **agitan**
// de verdad, se separan de su posicion de reposo y aceleran. Escuchar los
// hace respirar con tu voz. Es la diferencia entre un adorno y un indicador.
//
// Los picos son la capa que mide **cuanto** tarda, no si esta ocupada. La
// agitacion satura en cuanto empieza a pensar y a partir de ahi un turno de
// dos segundos y un encargo de cuatro minutos se ven igual. Cada aguja es un
// tramo de espera cumplido, asi que la silueta erizada dice de un vistazo si
// esto va a tardar. El resto de la escena no se toca: los picos se suman.

import QtQuick
import QtQuick3D
import QtQuick3D.Helpers
import QtQuick3D.Particles3D
import Friday.Geometry 1.0

Item {
    id: holo

    property string state_: "idle"     // idle · listening · thinking · speaking · error · waiting
    property real   level: 0.0         // nivel de audio 0..1
    property real   base: 96           // radio del globo, en unidades de escena
    property real   effort: 0.0        // cuanto lleva trabajando, 0..1
    property int    thoughts: 0        // picos de pensamiento acumulados

    // ── ajustes que vienen del toml ───────────────────────────────
    property int  nodes: 1400
    property int  spokes: 28
    property int  dust: 260
    property bool bloom: true
    property bool depthField: true
    property real fov: 42

    // ══════════════════ paleta y ritmo segun estado
    readonly property color amber:  "#FFB300"
    readonly property color gold:   "#FFD700"
    readonly property color danger: "#FF5F56"
    readonly property color calm:   "#FFC14D"

    readonly property color tone:
        state_ === "error"     ? danger :
        state_ === "listening" ? gold   :
        state_ === "speaking"  ? calm   : amber

    // Multiplicador de duracion: menor = mas rapido.
    readonly property real tempo:
        state_ === "thinking"  ? 0.30 :
        state_ === "listening" ? 0.55 :
        state_ === "speaking"  ? 0.78 :
        state_ === "error"     ? 0.45 : 1.0

    readonly property real energy:
        state_ === "idle"    ? 0.68 :
        state_ === "waiting" ? 0.84 : 1.0

    // Cuanto se salen los nodos de su reposo. Es LA señal de que esta
    // trabajando: al pensar la nube hierve, en reposo apenas respira.
    // No es `readonly`: un Behavior necesita poder escribir la propiedad para
    // interpolarla, y sin la transicion los nodos saltarian de golpe.
    property real agitation:
        state_ === "thinking"  ? 1.0 :
        state_ === "error"     ? 0.85 :
        state_ === "listening" ? 0.30 + holo.level * 0.9 :
        state_ === "speaking"  ? 0.35 : 0.08

    Behavior on agitation { NumberAnimation { duration: 520; easing.type: Easing.OutCubic } }

    // ══════════════════ el brote de un pico nuevo
    // Escala momentanea de la capa entera. Se dispara desde `thoughts`, no
    // desde una señal del puente: asi la escena sigue siendo autonoma y la
    // vista previa la reproduce sin cablear nada.
    property real pop: 1.0

    onThoughtsChanged: if (thoughts > 0) brote.restart()

    SequentialAnimation {
        id: brote
        NumberAnimation {
            target: holo; property: "pop"; to: 0.90
            duration: 90; easing.type: Easing.OutQuad
        }
        NumberAnimation {
            target: holo; property: "pop"; to: 1.0
            duration: 420; easing.type: Easing.OutBack
        }
    }

    View3D {
        id: view
        anchors.fill: parent
        renderMode: View3D.Offscreen        // obligatorio para el post-proceso

        environment: ExtendedSceneEnvironment {
            // El acompanante flota sobre el escritorio: el fondo de la escena
            // tiene que ser agujero, no color.
            backgroundMode: SceneEnvironment.Transparent
            antialiasingMode: SceneEnvironment.MSAA
            antialiasingQuality: SceneEnvironment.High

            // Sin tonemapping. Los operadores cinematograficos asumen una
            // escena con rango dinamico completo; aqui solo hay luz sobre
            // nada, asi que lo unico que hacen es levantar los negros y
            // convertir el ambar en crema.
            tonemapMode: SceneEnvironment.TonemapModeNone

            // El desbordamiento de luz. Contenido a proposito: el brillo
            // tiene que salir de las lineas, no sustituirlas. Con niveles
            // altos el halo se come la estructura y queda una nube pastel.
            glowEnabled: holo.bloom
            glowIntensity: 0.62 * holo.energy
            glowBloom: 0.28
            glowStrength: 0.95
            glowQualityHigh: true
            glowUseBicubicUpscale: true
            glowHDRMinimumValue: 0.6      // solo desborda lo que ya arde
            glowHDRMaximumValue: 6.0
            glowHDRScale: 1.8
            glowBlendMode: ExtendedSceneEnvironment.GlowBlendMode.Additive
            glowLevel: ExtendedSceneEnvironment.GlowLevel.Two
                     | ExtendedSceneEnvironment.GlowLevel.Three

            // Profundidad de campo: el frente y el fondo del globo pierden
            // definicion y la franja central queda nitida. Es lo que
            // convence al ojo de que el objeto ocupa espacio.
            depthOfFieldEnabled: holo.depthField
            depthOfFieldFocusDistance: 330
            depthOfFieldFocusRange: 240
            depthOfFieldBlurAmount: 1.6

            vignetteEnabled: false
        }

        PerspectiveCamera {
            id: cam
            position: Qt.vector3d(0, 42, 340)
            eulerRotation.x: -7
            fieldOfView: holo.fov
            clipNear: 10
            clipFar: 3000
        }

        // ══════════════════ el giroscopio
        Node {
            id: rig
            eulerRotation.x: -18            // inclinado: nunca de frente

            NumberAnimation on eulerRotation.y {
                from: 0; to: 360
                duration: 46000 * holo.tempo
                loops: Animation.Infinite
                running: true
            }

            // ── armazon: meridianos y paralelos ──────────────────
            Model {
                geometry: WireGlobe {
                    radius: holo.base
                    rings: 13
                    meridians: 26
                    segments: 84
                }
                materials: holoLine
                scale: Qt.vector3d(1, 1, 1)
            }

            // Un segundo armazon mas pequeño girando al reves: el detalle
            // que hace que el objeto se lea como mecanismo y no como pelota.
            Node {
                NumberAnimation on eulerRotation.y {
                    from: 360; to: 0
                    duration: 27000 * holo.tempo
                    loops: Animation.Infinite
                    running: true
                }
                eulerRotation.z: 24

                Model {
                    geometry: WireGlobe {
                        radius: holo.base * 0.62
                        rings: 5
                        meridians: 12
                        segments: 52
                    }
                    materials: holoFaint
                }
            }

            // ── radios: la luz sale del nucleo ───────────────────
            Model {
                geometry: RadialSpokes {
                    radius: holo.base * 1.04
                    count: holo.spokes
                    inner: 0.16
                }
                materials: holoLine
            }

            // ── arcos de datos ───────────────────────────────────
            Model {
                geometry: DataArcs {
                    radius: holo.base
                    count: 34
                    seed: 11
                }
                materials: holoFaint

                NumberAnimation on eulerRotation.y {
                    from: 0; to: 360
                    duration: 71000 * holo.tempo
                    loops: Animation.Infinite
                    running: true
                }
            }

            // ══════════════════ los picos de pensamiento
            // Se reconstruye la malla cuando cambia el numero de agujas o su
            // alcance. Es barato —una aguja son tres segmentos y hay catorce
            // como mucho— y a cambio la posicion de cada una vive en Python,
            // donde ya vive el resto de la geometria.
            Node {
                visible: holo.thoughts > 0

                Model {
                    geometry: ThoughtSpikes {
                        radius: holo.base
                        count: holo.thoughts
                        // Cuanto mas lleva trabajando, mas lejos llegan. Es
                        // la segunda lectura: el numero de agujas cuenta los
                        // tramos, el largo dice cuanto pesa la espera.
                        //
                        // El techo es corto a proposito. Una aguja que pasa
                        // de un tercio del radio deja de leerse como pico del
                        // objeto y pasa a leerse como un arañazo sobre la
                        // escena: cruza el encuadre, no sale del globo.
                        reach: 0.15 + holo.effort * 0.19
                        seed: 41
                    }
                    materials: holoSpike

                    // El brote. Una aguja que aparece a tamaño final no se
                    // ve aparecer: la escena entera esta en movimiento y el
                    // ojo la toma por una que ya estaba.
                    scale: Qt.vector3d(holo.pop, holo.pop, holo.pop)
                }
            }

            // ══════════════════ los nodos: la capa que reacciona
            ParticleSystem3D {
                id: cloud
                running: true

                SpriteParticle3D {
                    id: nodeDot
                    sprite: Texture { source: "image://friday/glow" }
                    maxAmount: holo.nodes + 8
                    color: holo.tone
                    colorVariation: Qt.vector4d(0.10, 0.16, 0.22, 0.34)
                    // El sprite es un disco de 64px con halo: a escala 3 cada
                    // nodo taparia media esfera y mil nodos serian una nube
                    // lechosa. Un nodo tiene que leerse como un punto.
                    particleScale: 0.82
                    fadeInDuration: 900
                    fadeOutDuration: 900
                    billboard: true
                    blendMode: SpriteParticle3D.Screen
                    sortMode: SpriteParticle3D.SortDistance
                }

                // Cascara: las particulas nacen SOBRE la superficie
                // (`fill: false`), no dentro del volumen.
                ParticleEmitter3D {
                    id: shell
                    system: cloud
                    particle: nodeDot
                    scale: Qt.vector3d(holo.base / 50, holo.base / 50, holo.base / 50)
                    shape: ParticleShape3D {
                        type: ParticleShape3D.Sphere
                        fill: false
                    }
                    // Vida larguisima + rafaga unica = nube estable. No es un
                    // surtidor: es un objeto que respira.
                    lifeSpan: 600000
                    particleScaleVariation: 1.5
                    particleRotationVariation: Qt.vector3d(0, 0, 180)
                    velocity: VectorDirection3D {
                        direction: Qt.vector3d(0, 0, 0)
                        directionVariation: Qt.vector3d(1.5, 1.5, 1.5)
                    }
                    emitBursts: [
                        EmitBurst3D { time: 0; amount: holo.nodes; duration: 700 }
                    ]
                }

                // Aqui vive la reaccion. `Wander3D` empuja cada particula por
                // su cuenta con una fase propia, asi que la nube no late en
                // bloque —eso pareceria un unico objeto escalando— sino que
                // hierve nodo a nodo.
                Wander3D {
                    system: cloud
                    enabled: holo.agitation > 0.02
                    // 8 unidades sobre un radio de 96: los nodos se despegan
                    // de la cascara lo justo para verse hervir. Mas y la
                    // esfera se deshilacha en una nube sin borde.
                    uniqueAmount: Qt.vector3d(8, 8, 8).times(holo.agitation)
                    uniquePace: Qt.vector3d(0.7, 0.9, 0.6).times(0.4 + holo.agitation)
                    uniqueAmountVariation: 0.7
                    fadeInDuration: 400
                    fadeOutDuration: 700
                }

                // Vuelve a pegar los nodos a la cascara. Sin esto, `Wander3D`
                // los va dispersando y en un minuto la esfera es una nube sin
                // forma: el vagabundeo no tiene memoria de donde nacio.
                Attractor3D {
                    system: cloud
                    position: Qt.vector3d(0, 0, 0)
                    scale: Qt.vector3d(holo.base / 50, holo.base / 50, holo.base / 50)
                    shape: ParticleShape3D {
                        type: ParticleShape3D.Sphere
                        fill: false
                    }
                    duration: 2600
                    durationVariation: 900
                }
            }

            // ══════════════════ polvo orbital
            ParticleSystem3D {
                id: motes
                running: true

                SpriteParticle3D {
                    id: mote
                    sprite: Texture { source: "image://friday/spark" }
                    maxAmount: holo.dust + 8
                    color: holo.gold
                    colorVariation: Qt.vector4d(0.08, 0.12, 0.2, 0.5)
                    particleScale: 0.34
                    billboard: true
                    blendMode: SpriteParticle3D.Screen
                    fadeInDuration: 1200
                    fadeOutDuration: 1600
                }

                ParticleEmitter3D {
                    system: motes
                    particle: mote
                    scale: Qt.vector3d(holo.base / 26, holo.base / 34, holo.base / 26)
                    shape: ParticleShape3D { type: ParticleShape3D.Sphere; fill: true }
                    lifeSpan: 9000
                    lifeSpanVariation: 4000
                    emitRate: holo.dust / 9
                    particleScaleVariation: 1.1
                    velocity: VectorDirection3D {
                        direction: Qt.vector3d(0, 3, 0)
                        directionVariation: Qt.vector3d(9, 6, 9)
                    }
                }

                Gravity3D {
                    system: motes
                    direction: Qt.vector3d(0, 1, 0)
                    magnitude: -1.6          // caen hacia el nucleo, no al suelo
                }
            }

            // ══════════════════ el nucleo incandescente
            Model {
                source: "#Sphere"
                scale: Qt.vector3d(holo.base * 0.0030, holo.base * 0.0030, holo.base * 0.0030)
                materials: PrincipledMaterial {
                    lighting: PrincipledMaterial.NoLighting
                    baseColor: "#FFFDF2"
                    opacity: 0.92
                    blendMode: PrincipledMaterial.Screen
                    depthDrawMode: Material.NeverDepthDraw
                }

                SequentialAnimation on scale {
                    loops: Animation.Infinite
                    running: true
                    Vector3dAnimation {
                        to: Qt.vector3d(holo.base * 0.0038, holo.base * 0.0038, holo.base * 0.0038)
                        duration: 1500 * holo.tempo
                        easing.type: Easing.InOutSine
                    }
                    Vector3dAnimation {
                        to: Qt.vector3d(holo.base * 0.0028, holo.base * 0.0028, holo.base * 0.0028)
                        duration: 1500 * holo.tempo
                        easing.type: Easing.InOutSine
                    }
                }
            }

            // Halo del nucleo: una segunda esfera mayor y casi transparente.
            // Es lo que le da al bloom algo grande que desbordar.
            Model {
                source: "#Sphere"
                scale: Qt.vector3d(holo.base * 0.0072, holo.base * 0.0072, holo.base * 0.0072)
                opacity: (0.16 + holo.level * 0.28) * holo.energy
                materials: PrincipledMaterial {
                    lighting: PrincipledMaterial.NoLighting
                    baseColor: holo.tone
                    blendMode: PrincipledMaterial.Screen
                    depthDrawMode: Material.NeverDepthDraw
                }
                Behavior on opacity { NumberAnimation { duration: 140 } }
            }
        }
    }

    // ══════════════════ materiales compartidos
    // Uno solo por aspecto, no uno por modelo: cada material es un estado de
    // pipeline distinto en la GPU y duplicarlos no gana nada.
    // `SourceOver` y no `Screen`: sobre un fondo transparente, mezclar por
    // pantalla suma luz contra la nada y todo tiende a blanco. El aspecto
    // aditivo del holograma lo da el post-proceso de brillo, que sabe lo que
    // es fondo; el material solo tiene que dibujar una linea con su alfa.
    PrincipledMaterial {
        id: holoLine
        lighting: PrincipledMaterial.NoLighting
        vertexColorsEnabled: true            // el degradado va horneado en la malla
        baseColor: holo.tone
        alphaMode: PrincipledMaterial.Blend
        opacity: 0.85 * holo.energy
        cullMode: Material.NoCulling
        depthDrawMode: Material.NeverDepthDraw
        Behavior on opacity { NumberAnimation { duration: 420 } }
    }

    // Los picos van mas opacos que el armazon aunque compartan paleta: nacen
    // sobre la nube de nodos y con la opacidad del armazon se perderian
    // dentro de ella justo cuando tienen algo que decir.
    PrincipledMaterial {
        id: holoSpike
        lighting: PrincipledMaterial.NoLighting
        vertexColorsEnabled: true
        baseColor: holo.gold
        alphaMode: PrincipledMaterial.Blend
        opacity: 0.55 + holo.effort * 0.45
        cullMode: Material.NoCulling
        depthDrawMode: Material.NeverDepthDraw
        Behavior on opacity { NumberAnimation { duration: 300 } }
    }

    PrincipledMaterial {
        id: holoFaint
        lighting: PrincipledMaterial.NoLighting
        vertexColorsEnabled: true
        baseColor: holo.gold
        alphaMode: PrincipledMaterial.Blend
        opacity: 0.38 * holo.energy
        cullMode: Material.NoCulling
        depthDrawMode: Material.NeverDepthDraw
        Behavior on opacity { NumberAnimation { duration: 420 } }
    }
}
