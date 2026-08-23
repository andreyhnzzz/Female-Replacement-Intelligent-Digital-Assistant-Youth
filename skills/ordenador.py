"""SKILL — ordenador: control directo de la maquina, decidido por el motor.

La regex solo lleva **a la skill**; que accion es y con que argumentos lo
elige el motor contra `CATALOGO`, declarado como datos. Es la excepcion al
enrutado por regex del resto: «bajale», «esto suena altisimo» y «ponlo a la
mitad» son la misma intencion con cero palabras en comun, y una regex por
variante es una carrera que se pierde.

**El motor propone, no dispone.** Lo que devuelve se valida contra el catalogo
(lista blanca), contra el puerto disponible y contra la politica. Un
`borrar_disco` alucinado se estrella contra un catalogo que no lo contiene.
Añadir una capacidad es una entrada en la tupla mas su rama en `_aplicar`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from core.engine import ask_json, enum_schema
from core.lang import numero

from .base import PendingAction, Skill, SkillContext, SkillResult

CONFIANZA_MINIMA = 0.55

# Un modelo pequeño escribe la confianza con palabras tan a menudo como con
# numeros. Tirar su respuesta por eso seria castigar la forma, no el fondo.
CONFIANZA_TEXTO: dict[str, float] = {
    "muy alta": 0.95, "alta": 0.9, "high": 0.9, "very high": 0.95,
    "media": 0.65, "moderada": 0.65, "medium": 0.65, "normal": 0.65,
    "baja": 0.3, "low": 0.3, "muy baja": 0.15, "ninguna": 0.0,
}


@dataclass(frozen=True, slots=True)
class Propuesta:
    """Lo que el motor propuso, con el motivo cuando no propuso nada.

    Antes esto era `tuple | None`, y el `None` cargaba con tres situaciones
    que no se parecen: no entendi la frase, la entendi y no tengo esa
    capacidad, y la tengo pero no en esta maquina. Al colapsarlas en una
    sola respuesta, FRIDAY contestaba «no me quedo claro» a peticiones que
    habia entendido perfectamente.
    """
    accion: "Accion | None" = None
    args: dict[str, Any] = field(default_factory=dict)
    porque: str = ""
    motivo: str = "no_entendi"        # ok | no_entendi | fuera_de_catalogo | fuera_de_aqui
    pedido: str = ""                  # lo que el motor entendio que se pedia
    accion_ausente: "Accion | None" = None


@dataclass(frozen=True, slots=True)
class Accion:
    """Una capacidad, declarada como dato.

    `describe` y `ejemplos` van al prompt: son lo unico que el motor ve para
    elegir, asi que se escriben para que los lea un modelo, no un humano.
    """
    nombre: str
    describe: str
    puerto: str                       # campo de SystemAccess que hace falta
    control: str = ""                 # tipo para policy.can_control
    args: tuple[str, ...] = ()
    ejemplos: tuple[str, ...] = ()


CATALOGO: tuple[Accion, ...] = (
    Accion("volumen_cambiar",
           "sube o baja el volumen. 'cuanto' es positivo para subir y "
           "negativo para bajar, en puntos porcentuales (10 = un poco, 30 = mucho)",
           puerto="media", control="media", args=("cuanto",),
           # Los ejemplos llevan el ARGUMENTO, no solo la frase: la
           # descripcion explica el signo en abstracto, el ejemplo lo enseña.
           # Sin eso un 8B acertaba la accion y erraba la direccion.
           ejemplos=("subele -> +15", "no te oigo -> +20",
                     "mas alto -> +20", "baja el volumen -> -15",
                     "esto suena altisimo -> -30", "bajale un poco -> -10")),
    Accion("volumen_fijar",
           "pone el volumen en un nivel absoluto de 0 a 100",
           puerto="media", control="media", args=("nivel",),
           ejemplos=("ponlo a la mitad", "volumen al 20", "dejalo en 70")),
    Accion("silenciar",
           "activa o desactiva el silencio del sistema (alterna)",
           puerto="media", control="media",
           ejemplos=("silencia", "mutea", "quita el sonido")),
    Accion("reproduccion",
           "controla QUE suena, no a que volumen. 'accion' es exactamente uno "
           "de: play_pause, next, prev, stop",
           puerto="media", control="media", args=("accion",),
           # «Saltate esta cancion» se la llevaba `volumen_cambiar`: ambas son
           # «de audio» y sin ejemplo cercano gana la accion mas comun. Los
           # ejemplos son lo unico que separa dos acciones vecinas.
           ejemplos=("pausa", "siguiente cancion", "saltate esta cancion",
                     "quita esta cancion", "vuelve a la anterior", "para la musica")),
    Accion("copiar",
           "escribe un texto en el portapapeles para que el usuario lo pegue",
           puerto="clipboard", control="clipboard", args=("texto",),
           ejemplos=("copiame eso", "ponlo en el portapapeles")),
    Accion("leer_portapapeles",
           "lee lo que hay copiado ahora mismo",
           puerto="clipboard", control="clipboard",
           ejemplos=("que tengo copiado", "lee el portapapeles")),
    Accion("bloquear",
           "bloquea la sesion de Windows",
           puerto="session", control="session",
           ejemplos=("bloquea el equipo", "me voy", "bloquea la sesion")),
    Accion("suspender",
           "suspende el equipo",
           puerto="session", control="session",
           ejemplos=("suspende", "duerme el equipo")),
    Accion("minimizar",
           "minimiza una ventana. 'cual' es parte del titulo o del proceso",
           puerto="window_ctl", args=("cual",),
           ejemplos=("minimiza Chrome", "quita eso de en medio")),
    Accion("radio_encender",
           "enciende una radio del equipo. 'radio' es exactamente bluetooth o wifi",
           puerto="radios", control="radio", args=("radio",),
           ejemplos=("enciende el bluetooth -> bluetooth",
                     "activa el wifi -> wifi",
                     "pon el blue tooth -> bluetooth",
                     "conectate a la red -> wifi")),
    Accion("radio_apagar",
           "apaga una radio del equipo. 'radio' es exactamente bluetooth o wifi",
           puerto="radios", control="radio", args=("radio",),
           # El caso que abrio esto: se pidio dos veces «desactiva el
           # Bluetooth» y no habia accion que elegir.
           ejemplos=("desactiva el bluetooth -> bluetooth",
                     "apaga el wifi -> wifi",
                     "quita el blue tooth -> bluetooth",
                     "modo avion -> wifi")),
    Accion("radio_estado",
           "dice si una radio esta encendida, sin tocarla. "
           "'radio' es exactamente bluetooth o wifi",
           puerto="radios", args=("radio",),
           ejemplos=("esta encendido el bluetooth -> bluetooth",
                     "tengo wifi -> wifi")),
    Accion("brillo_fijar",
           "pone el brillo de la pantalla en un nivel absoluto de 0 a 100",
           puerto="display", control="display", args=("nivel",),
           ejemplos=("brillo al 30 -> 30", "pon la pantalla a la mitad -> 50",
                     "brillo al maximo -> 100")),
    Accion("brillo_cambiar",
           "sube o baja el brillo de la pantalla. 'cuanto' es positivo para "
           "subir y negativo para bajar, en puntos (20 = bastante)",
           puerto="display", control="display", args=("cuanto",),
           ejemplos=("sube el brillo -> +20", "baja el brillo -> -20",
                     "no veo nada -> +30", "esto ciega -> -30",
                     "la pantalla esta muy oscura -> +25")),
)

# Todas las acciones que existen, esten o no disponibles aqui. Es lo que
# permite responder «no se hacer eso» distinguiendolo de «no te entendi»:
# sin esta lista, una peticion perfectamente entendida y fuera del catalogo
# se confunde con una frase incomprensible, y son dos fallos distintos.
NOMBRES = tuple(a.nombre for a in CATALOGO)


class OrdenadorSkill(Skill):
    name = "ordenador"
    description = ("Controla la maquina directamente: volumen, reproduccion, "
                   "portapapeles, bloqueo de sesion y ventanas.")
    # Estos patrones solo deciden que la peticion es MIA. Cual de las nueve
    # acciones es, y con que argumentos, lo resuelve el motor.
    triggers = [
        r"\bvolumen\b", r"\bsube(le)?\b", r"\bbaja(le)?\b", r"\bsilencia\b",
        r"\bmutea?\b", r"\bpausa\b", r"\breanuda\b", r"\bsiguiente canci[oó]n\b",
        r"\bs[aá]ltate\b", r"\bsalta (esta|la) canci[oó]n\b",
        r"\bcanci[oó]n anterior\b", r"\bportapapeles\b", r"\bcopia(me)?\b",
        r"\bqu[eé] tengo copiado\b", r"\bbloquea\b", r"\bsuspende\b",
        r"\bminimiza\b", r"\bno te (oigo|escucho)\b", r"\bqu[ií]tale (el )?sonido\b",
        # Formas sin verbo propio: llegan a la skill igual.
        r"\bponlo (a|en)\b", r"\bd[eé]jalo en\b", r"\ba la mitad\b",
        r"\bm[aá]s (alto|bajo|fuerte|flojo)\b", r"\bsuena (muy|demasiado)\b",
        # radios y pantalla
        r"\bbluetooth\b", r"\bblue tooth\b", r"\bwifi\b", r"\bwi[ -]?fi\b",
        r"\bbrillo\b", r"\bpantalla (muy )?(oscura|clara)\b",
        r"\bdesactiva\b", r"\bactiva\b", r"\benciende\b", r"\bapaga\b",
        r"\bmodo avi[oó]n\b", r"\bno veo nada\b",
    ]
    needs = ()          # cada accion declara el suyo; la skill degrada sola
    riesgo = "efecto"        # toca volumen, radios, brillo y sesion

    async def run(self, ctx: SkillContext) -> SkillResult:
        if ctx.system is None:
            return SkillResult(ok=False, error="sin acceso al sistema",
                               speak="No tengo acceso a la maquina en esta plataforma.")

        disponibles = [a for a in CATALOGO
                       if getattr(ctx.system, a.puerto, None) is not None]
        if not disponibles:
            return SkillResult(
                ok=False, error="sin puertos de control",
                speak="No tengo control del escritorio en esta plataforma.",
                display="# Sin control\n\nNinguna capacidad de escritorio esta "
                        "disponible aqui.")

        propuesta = await self._decidir(ctx, disponibles)

        if propuesta.accion is None:
            return self._no_puedo(propuesta, disponibles, ctx)

        return await self._ejecutar(ctx, propuesta.accion, propuesta.args,
                                    propuesta.porque)

    # ══════════════════════════════ decir cual de los dos fallos fue
    def _no_puedo(self, propuesta: "Propuesta", disponibles: list[Accion],
                  ctx: SkillContext) -> SkillResult:
        """No hay accion. Ahora bien: ¿no te entendi, o no se hacerlo?

        Antes las dos salidas eran la misma frase —«no me quedo claro que
        quieres que haga»— y eso es engañoso justo cuando mas importa: la
        peticion se entendio perfectamente y lo que falta es la capacidad.
        El usuario que oye «no me quedo claro» lo repite mas despacio; el
        que oye «no se apagar el Bluetooth» sabe que puede dejar de
        intentarlo.

        Hay un tercer caso, y es el que mas rabia da: la capacidad **existe**
        pero no esta cableada en esta maquina. Decir «no se hacerlo» ahi
        seria mentir; lo que falta es una pieza, y se nombra.
        """
        pedido = propuesta.pedido.strip()

        if propuesta.motivo == "fuera_de_aqui" and propuesta.accion_ausente:
            falta = self._que_falta(propuesta.accion_ausente, ctx)
            humano = propuesta.accion_ausente.nombre.replace("_", " ")
            return SkillResult(
                ok=False, error=f"puerto ausente: {propuesta.accion_ausente.puerto}",
                speak=f"Se hacerlo, pero en este equipo no puedo: {falta}.",
                display=(f"# Aqui no puedo\n\n**{humano}** existe, pero en esta "
                         f"maquina falta algo.\n\n> {falta}"),
                data={"motivo": "puerto_ausente",
                      "accion": propuesta.accion_ausente.nombre})

        if propuesta.motivo == "fuera_de_catalogo":
            que = f" {pedido}" if pedido else " eso"
            return SkillResult(
                # Sin `ok=False`: entender la peticion y no tener la
                # capacidad no es un fallo de FRIDAY, es un limite suyo. Un
                # error rojo en el panel diria que algo se rompio.
                speak=f"No se{que}, Jefe. Eso todavia no lo tengo.",
                display=(f"# Eso no lo tengo\n\nEntendi que quieres"
                         f"{que}, pero no esta entre las cosas que se hacer.\n\n"
                         + self._catalogo_md(disponibles)),
                data={"motivo": "sin_capacidad", "pedido": pedido})

        return SkillResult(
            speak="No me quedo claro que quieres que haga.",
            display="# No lo tengo claro\n\nDimelo de otra forma, o mas "
                    "concreto.\n\n" + self._catalogo_md(disponibles),
            data={"motivo": "no_entendi"})

    @staticmethod
    def _que_falta(accion: Accion, ctx: SkillContext) -> str:
        """Por que una accion del catalogo no esta disponible aqui."""
        detalle = {
            "radios": "faltan las proyecciones WinRT (pip install winsdk)",
            "display": "ningun panel de este equipo acepta control de brillo",
            "media": "no hay control de audio en esta plataforma",
            "clipboard": "no hay portapapeles accesible",
            "session": "no hay control de sesion en esta plataforma",
            "window_ctl": "no puedo manipular ventanas aqui",
        }
        return detalle.get(accion.puerto, f"me falta el acceso «{accion.puerto}»")

    # ══════════════════════════════ decidir (el motor, no un guion)
    async def _decidir(self, ctx: SkillContext,
                       disponibles: list[Accion]) -> "Propuesta":
        # Los ejemplos van en su propia linea: mezclados con la descripcion,
        # un 8B lee el bloque como un parrafo y confunde acciones vecinas.
        catalogo = "\n\n".join(
            f"{a.nombre}({', '.join(a.args)})\n  que hace: {a.describe}"
            + (f"\n  se pide asi: {'; '.join(a.ejemplos)}" if a.ejemplos else "")
            for a in disponibles)

        prompt = (
            f"ACCIONES POSIBLES:\n\n{catalogo}\n\n"
            "Nombres validos, copia uno tal cual:\n"
            + ", ".join(a.nombre for a in disponibles) + ", ninguna\n\n"
            "Si ninguna de la lista sirve, responde \"ninguna\" y rellena "
            "\"pidio\" con lo que el usuario queria, en tres o cuatro "
            "palabras. Ese campo es lo unico que le permite a FRIDAY "
            "contestar «no se hacer eso» en vez de «no te entendi».\n\n"
            # La peticion AL FINAL, pegada a la respuesta: arriba del
            # catalogo, un 8B elegia la primera entrada de la lista (6/12).
            f"EL USUARIO DIJO:\n\"{ctx.text.strip()}\"\n\n"
            "Elige la accion de la lista que corresponde a esa frase.\n\n"
            "Responde SOLO este JSON, sin nada mas:\n"
            # Valores de ejemplo plausibles, nunca ceros: el hueco que dejas
            # es la respuesta que te dan, y con `0.0` devolvia 0.0 siempre.
            '{"accion": "nombre_de_la_lista", "args": {"cuanto": 20}, '
            '"confianza": 0.9, "porque": "por que la elegiste", '
            '"pidio": "apagar el bluetooth"}'
        )

        # El `enum` lleva TODO el catalogo, no solo lo disponible aqui: si el
        # modelo solo pudiera nombrar lo cableado, una peticion de brillo en
        # un equipo sin brillo saldria como «ninguna» y se contestaria «no te
        # entendi». Que pueda nombrar lo ausente es lo que permite decir
        # «se hacerlo, pero aqui no puedo». La lista blanca de EJECUCION
        # sigue siendo `disponibles`, unas lineas mas abajo.
        schema = enum_schema(
            {"accion": list(NOMBRES) + ["ninguna"],
             "args": "object", "confianza": "number",
             "porque": "string", "pidio": "string"},
            requeridos=["accion", "args"])

        try:
            data = await ask_json(ctx.engine, prompt, schema=schema) or {}
        except Exception:
            return Propuesta(motivo="no_entendi")

        pedido = str(data.get("pidio", "")).strip()[:80]
        nombre = self._normaliza(data.get("accion", ""))

        # El catalogo es la lista blanca: lo que no esta aqui no existe,
        # diga el modelo lo que diga.
        accion = next((a for a in disponibles
                       if self._normaliza(a.nombre) == nombre), None)
        if accion is not None:
            if self._confianza(data.get("confianza")) < CONFIANZA_MINIMA:
                return Propuesta(motivo="no_entendi", pedido=pedido)
            return Propuesta(accion=accion, args=self._args(data.get("args")),
                             porque=str(data.get("porque", "")), motivo="ok",
                             pedido=pedido)

        # Nombro algo del catalogo que aqui no esta cableado: la capacidad
        # existe, la maquina no la tiene.
        ausente = next((a for a in CATALOGO
                        if self._normaliza(a.nombre) == nombre), None)
        if ausente is not None:
            return Propuesta(motivo="fuera_de_aqui", accion_ausente=ausente,
                             pedido=pedido)

        # «ninguna», o un nombre que no existe. Si dijo que pidio algo,
        # entendio la frase y no tiene con que; si no dijo nada, no entendio.
        return Propuesta(motivo="fuera_de_catalogo" if pedido else "no_entendi",
                         pedido=pedido)

    # ── tolerancia con la forma, no con el fondo ──────────────────
    @staticmethod
    def _normaliza(nombre: Any) -> str:
        """«Volumen Cambiar» y «volumen-cambiar» son `volumen_cambiar`.
        Normaliza la forma; no admite nombres fuera de la lista blanca."""
        return re.sub(r"[\s\-]+", "_", str(nombre).strip().lower())

    @staticmethod
    def _confianza(valor: Any) -> float:
        """Cuanta confianza declaro el modelo.

        **Que falte no es que dude**: un modelo pequeño omite metadatos todo
        el rato, y tratar la ausencia como cero tiraba acciones bien elegidas
        contestando «no me quedo claro». No afloja nada — el guardia es el
        catalogo, el puerto y la politica; esto es solo una señal.
        """
        if valor is None or (isinstance(valor, str) and not valor.strip()):
            return CONFIANZA_MINIMA
        if isinstance(valor, str):
            clave = valor.strip().lower().rstrip("%")
            if clave in CONFIANZA_TEXTO:
                return CONFIANZA_TEXTO[clave]
        try:
            n = float(valor)
        except (TypeError, ValueError):
            return CONFIANZA_MINIMA          # lo dijo, pero no lo entendimos
        return n / 100.0 if n > 1.0 else n   # «85» es 0.85, no un 8500%

    @staticmethod
    def _args(valor: Any) -> dict[str, Any]:
        """Los argumentos, vengan como vengan: un modelo pequeño a veces mete
        el objeto anidado como texto. Misma respuesta, una comilla de mas."""
        if isinstance(valor, dict):
            return valor
        if isinstance(valor, str) and valor.strip():
            from core.engine import Engine
            return Engine.extract_json(valor) or {}
        return {}

    # ══════════════════════════════ ejecutar, con el guardia delante
    async def _ejecutar(self, ctx: SkillContext, accion: Accion,
                        args: dict[str, Any], porque: str) -> SkillResult:
        if accion.control and ctx.policy is not None:
            # Apagar una radio se confirma; encenderla no. La politica sabe
            # decidirlo, pero necesita saber el sentido: desde fuera, «radio»
            # a secas no distingue entre devolverte el wifi y quitartelo.
            decision = ctx.policy.can_control(
                accion.control, desconecta=accion.nombre == "radio_apagar")

            if decision.verdict.value == "deny":
                return SkillResult(
                    ok=False, error=decision.reason,
                    speak=f"No puedo. {decision.reason}.",
                    display=(f"# Bloqueado\n\n**{accion.nombre}** — {decision.reason}\n\n"
                             f"Si lo quieres, activa `{decision.rule}` en "
                             f"`config/friday.toml`."),
                    data={"accion": accion.nombre, "motivo": decision.reason})

            if decision.verdict.value == "confirm":
                describe = f"{accion.nombre}: {decision.reason}"
                return SkillResult(
                    speak=f"Voy a {self._frase(accion, args)}. ¿Confirmas?",
                    display=f"# Espera tu «sí»\n\n**{self._frase(accion, args)}**\n\n"
                            f"> {decision.reason}",
                    pending=PendingAction(
                        describe=describe,
                        run=lambda: self._aplicar(ctx, accion, args)),
                    data={"accion": accion.nombre, "pendiente": True})

        return self._aplicar(ctx, accion, args)

    def _manos(self, sys_, args: dict[str, Any]) -> dict[str, Callable[[], SkillResult]]:
        """La tabla de despacho: nombre del catalogo -> lo que lo hace.

        Metodo y no un dict enterrado dentro de `_aplicar` para que la
        invariante sea **comprobable**: `scripts/system_test.py` compara sus
        claves contra `CATALOGO` y falla si declaras una capacidad sin
        cablearla. Antes esa prueba llevaba la lista de nombres transcrita a
        mano, o sea que declarar una accion nueva rompia la prueba hasta que
        la editabas — que es la forma de prueba que no prueba nada.
        """
        return {
            "volumen_cambiar": lambda: self._volumen(sys_, args),
            "volumen_fijar": lambda: self._volumen_fijo(sys_, args),
            "silenciar": lambda: self._silenciar(sys_),
            "reproduccion": lambda: self._reproduccion(sys_, args),
            "copiar": lambda: self._copiar(sys_, args),
            "leer_portapapeles": lambda: self._leer(sys_),
            "bloquear": lambda: self._sesion(sys_, "lock"),
            "suspender": lambda: self._sesion(sys_, "sleep"),
            "minimizar": lambda: self._minimizar(sys_, args),
            "radio_encender": lambda: self._radio(sys_, args, True),
            "radio_apagar": lambda: self._radio(sys_, args, False),
            "radio_estado": lambda: self._radio_estado(sys_, args),
            "brillo_fijar": lambda: self._brillo_fijo(sys_, args),
            "brillo_cambiar": lambda: self._brillo(sys_, args),
        }

    def _aplicar(self, ctx: SkillContext, accion: Accion,
                 args: dict[str, Any]) -> SkillResult:
        handler = self._manos(ctx.system, args).get(accion.nombre)
        if handler is None:
            return SkillResult(ok=False, error=f"sin implementacion: {accion.nombre}",
                               speak="Esa capacidad esta declarada pero no cableada.")
        return handler()

    # ══════════════════════════════ las manos
    def _entero(self, args: dict[str, Any], clave: str, por_defecto: int) -> int:
        """El argumento como numero, aunque venga dictado con letras.

        El motor devuelve `{"nivel": 40}` casi siempre, pero con un 8B
        devuelve `{"nivel": "cuarenta"}` o `{"nivel": "a la mitad"}` lo
        bastante a menudo como para que `int(float(...))` lanzando fuera un
        problema real: se caia al valor por defecto y FRIDAY ponia el
        volumen al 50 cuando le habias pedido veinte.
        """
        crudo = args.get(clave, por_defecto)
        try:
            return int(float(crudo))
        except (TypeError, ValueError):
            pass
        # El signo lo lleva el texto, no el numero: «menos veinte» y
        # «bajale veinte» son el mismo -20 escrito de dos formas.
        valor = numero(str(crudo))
        if valor is None:
            return por_defecto
        negativo = re.search(r"\b(menos|baja|bajar|reduce|menor)\b",
                             str(crudo), re.I)
        return -valor if negativo else valor

    def _volumen(self, sys_, args) -> SkillResult:
        cuanto = self._entero(args, "cuanto", 10)
        aplicado = sys_.media.volume(cuanto)
        if not aplicado:
            return self._fallo(sys_.media, "No pude tocar el volumen")
        verbo = "Subido" if aplicado > 0 else "Bajado"
        return SkillResult(speak=f"{verbo}.",
                           display=f"# Volumen\n\n{verbo} {abs(aplicado)} puntos.",
                           data={"delta": aplicado})

    def _volumen_fijo(self, sys_, args) -> SkillResult:
        nivel = max(0, min(100, self._entero(args, "nivel", 50)))
        sys_.media.set_volume(nivel)
        return SkillResult(speak=f"Volumen al {nivel}.",
                           display=f"# Volumen\n\nFijado en **{nivel}**.",
                           data={"nivel": nivel})

    def _silenciar(self, sys_) -> SkillResult:
        if not sys_.media.mute():
            return self._fallo(sys_.media, "No pude silenciar")
        return SkillResult(speak="Silencio.", display="# Silencio\n\nAlternado.",
                           data={"accion": "mute"})

    def _reproduccion(self, sys_, args) -> SkillResult:
        accion = str(args.get("accion", "play_pause")).strip().lower()
        if not sys_.media.playback(accion):
            return self._fallo(sys_.media, f"No pude aplicar «{accion}»")
        etiqueta = {"play_pause": "Pausa o reanuda", "next": "Siguiente",
                    "prev": "Anterior", "stop": "Detenido"}.get(accion, accion)
        return SkillResult(speak=f"{etiqueta}.",
                           display=f"# Reproduccion\n\n{etiqueta}.",
                           data={"accion": accion})

    def _copiar(self, sys_, args) -> SkillResult:
        texto = str(args.get("texto", "")).strip()
        if not texto:
            return SkillResult(speak="¿Que copio?", display="# ¿Que copio?")
        if not sys_.clipboard.write(texto):
            return self._fallo(sys_.clipboard, "No pude escribir el portapapeles")
        return SkillResult(speak="Copiado.",
                           display=f"# Copiado\n\n```\n{texto[:400]}\n```",
                           data={"chars": len(texto)})

    def _leer(self, sys_) -> SkillResult:
        texto = sys_.clipboard.read()
        if not texto:
            error = getattr(sys_.clipboard, "last_error", "")
            return SkillResult(
                ok=not error, error=error,
                speak=error and f"No pude leerlo. {error}." or "No hay texto copiado.",
                display="# Portapapeles\n\n" + (f"> {error}" if error else "Vacio."))
        return SkillResult(
            speak=f"Tienes {len(texto)} caracteres copiados.",
            display=f"# Portapapeles\n\n```\n{texto[:1500]}\n```",
            data={"chars": len(texto)})

    def _sesion(self, sys_, que: str) -> SkillResult:
        ok = sys_.session.lock() if que == "lock" else sys_.session.sleep()
        if not ok:
            return self._fallo(sys_.session, "No pude")
        return SkillResult(speak="Hasta ahora, Jefe.",
                           display=f"# Sesion\n\n{'Bloqueada' if que == 'lock' else 'Suspendiendo'}.",
                           data={"accion": que})

    def _minimizar(self, sys_, args) -> SkillResult:
        cual = str(args.get("cual", "")).strip().lower()
        ventanas = sys_.windows.list_windows() if sys_.windows else []
        objetivo = next((w for w in ventanas
                         if cual and cual in f"{w.title} {w.process}".lower()), None)
        if objetivo is None:
            return SkillResult(
                ok=False, error="ventana no encontrada",
                speak=f"No veo ninguna ventana que sea «{cual}».",
                display="# Sin coincidencia\n\n### Abiertas\n"
                        + "\n".join(f"- {w.label}" for w in ventanas[:12]))
        sys_.window_ctl.minimize(objetivo.handle)
        return SkillResult(speak=f"{objetivo.process or objetivo.title} fuera.",
                           display=f"# Minimizada\n\n**{objetivo.title}**",
                           data={"ventana": objetivo.title})

    # ── radios ────────────────────────────────────────────────────
    @staticmethod
    def _que_radio(args: dict[str, Any]) -> str:
        """Que radio nombro, tolerando como la escribe un modelo pequeño.

        La normalizacion vive en `system/win32/radios.py` porque es donde
        estan los alias; aqui solo se pide. Si la plataforma no tiene ese
        modulo, no hay radios que tocar y esta rama no se alcanza.
        """
        from system.win32.radios import normaliza_radio
        return normaliza_radio(str(args.get("radio", "")))

    def _radio(self, sys_, args: dict[str, Any], encender: bool) -> SkillResult:
        tipo = self._que_radio(args)
        if not tipo:
            return SkillResult(
                ok=False, error="radio no reconocida",
                speak="¿El bluetooth o el wifi?",
                display="# ¿Cual?\n\nPuedo con el **bluetooth** y el **wifi**.")

        etiqueta = "Bluetooth" if tipo == "bluetooth" else "wifi"
        if not sys_.radios.set(tipo, encender):
            return self._fallo(sys_.radios, f"No pude tocar el {etiqueta}")
        return SkillResult(
            speak=f"{etiqueta} {'encendido' if encender else 'apagado'}.",
            display=f"# {etiqueta}\n\n{'Encendido' if encender else 'Apagado'}.",
            data={"radio": tipo, "on": encender})

    def _radio_estado(self, sys_, args: dict[str, Any]) -> SkillResult:
        tipo = self._que_radio(args)
        if not tipo:
            return SkillResult(ok=False, error="radio no reconocida",
                               speak="¿El bluetooth o el wifi?",
                               display="# ¿Cual?")
        estado = sys_.radios.state(tipo)
        etiqueta = "Bluetooth" if tipo == "bluetooth" else "wifi"
        if not estado.known:
            # «No lo se» no es «esta apagado»: decir lo segundo mandaria al
            # usuario a arreglar algo que a lo mejor funciona.
            razon = getattr(sys_.radios, "last_error", "") or "no pude leerlo"
            return SkillResult(ok=False, error=razon,
                               speak=f"No puedo leer el {etiqueta}. {razon}.",
                               display=f"# {etiqueta}\n\n> {razon}")
        return SkillResult(
            speak=f"{etiqueta} {'encendido' if estado.on else 'apagado'}.",
            display=f"# {etiqueta}\n\n**{'Encendido' if estado.on else 'Apagado'}**"
                    + (f"\n\n`{estado.name}`" if estado.name else ""),
            data={"radio": tipo, "on": estado.on})

    # ── brillo ────────────────────────────────────────────────────
    def _brillo_fijo(self, sys_, args: dict[str, Any]) -> SkillResult:
        nivel = max(0, min(100, self._entero(args, "nivel", 50)))
        aplicado = sys_.display.set_brightness(nivel)
        if aplicado < 0:
            return self._fallo(sys_.display, "No pude cambiar el brillo")
        return SkillResult(speak=f"Brillo al {aplicado}.",
                           display=f"# Brillo\n\nFijado en **{aplicado}**.",
                           data={"nivel": aplicado})

    def _brillo(self, sys_, args: dict[str, Any]) -> SkillResult:
        """Relativo. A diferencia del volumen, aqui SI se puede leer el nivel
        actual, asi que se lee y se suma en vez de barrer a ciegas."""
        cuanto = self._entero(args, "cuanto", 20)
        actual = sys_.display.brightness()
        if actual < 0:
            return self._fallo(sys_.display, "No pude leer el brillo")
        destino = max(0, min(100, actual + cuanto))
        aplicado = sys_.display.set_brightness(destino)
        if aplicado < 0:
            return self._fallo(sys_.display, "No pude cambiar el brillo")
        verbo = "Subido" if cuanto > 0 else "Bajado"
        return SkillResult(speak=f"{verbo}. Brillo al {aplicado}.",
                           display=f"# Brillo\n\n{verbo} de {actual} a **{aplicado}**.",
                           data={"antes": actual, "nivel": aplicado})

    # ══════════════════════════════ auxiliares
    @staticmethod
    def _fallo(puerto: Any, prefijo: str) -> SkillResult:
        razon = getattr(puerto, "last_error", "") or "bloqueado por politica"
        return SkillResult(ok=False, error=razon,
                           speak=f"{prefijo}. {razon}.",
                           display=f"# No pude\n\n> {razon}")

    @staticmethod
    def _frase(accion: Accion, args: dict[str, Any]) -> str:
        detalle = ", ".join(f"{k}={v}" for k, v in args.items() if v not in ("", None))
        return f"{accion.nombre.replace('_', ' ')}" + (f" ({detalle})" if detalle else "")

    @staticmethod
    def _catalogo_md(disponibles: list[Accion]) -> str:
        return "### Lo que puedo hacer aqui\n" + "\n".join(
            f"- **{a.nombre.replace('_', ' ')}** — {a.describe.split('.')[0]}"
            for a in disponibles)
