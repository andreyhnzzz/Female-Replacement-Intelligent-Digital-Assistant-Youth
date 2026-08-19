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
from dataclasses import dataclass
from typing import Any, Callable

from core.engine import ask_json, enum_schema

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
)


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
    ]
    needs = ()          # cada accion declara el suyo; la skill degrada sola

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
        if propuesta is None:
            return SkillResult(
                speak="No me quedo claro que quieres que haga.",
                display="# No lo tengo claro\n\nDimelo de otra forma, o mas "
                        "concreto.\n\n" + self._catalogo_md(disponibles))

        accion, args, porque = propuesta
        return await self._ejecutar(ctx, accion, args, porque)

    # ══════════════════════════════ decidir (el motor, no un guion)
    async def _decidir(self, ctx: SkillContext,
                       disponibles: list[Accion]) -> tuple[Accion, dict, str] | None:
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
            # La peticion AL FINAL, pegada a la respuesta: arriba del
            # catalogo, un 8B elegia la primera entrada de la lista (6/12).
            f"EL USUARIO DIJO:\n\"{ctx.text.strip()}\"\n\n"
            "Elige la accion de la lista que corresponde a esa frase.\n\n"
            "Responde SOLO este JSON, sin nada mas:\n"
            # Valores de ejemplo plausibles, nunca ceros: el hueco que dejas
            # es la respuesta que te dan, y con `0.0` devolvia 0.0 siempre.
            '{"accion": "nombre_de_la_lista", "args": {"cuanto": 20}, '
            '"confianza": 0.9, "porque": "por que la elegiste"}'
        )

        # El `enum` hace imposible inventarse un nombre donde el backend lo
        # soporte. `confianza` queda opcional: exigirla no hace que el modelo
        # la estime, hace que la rellene con 0 y el umbral tire buenas
        # acciones.
        schema = enum_schema(
            {"accion": [a.nombre for a in disponibles] + ["ninguna"],
             "args": "object", "confianza": "number", "porque": "string"},
            requeridos=["accion", "args"])

        try:
            data = await ask_json(ctx.engine, prompt, schema=schema) or {}
        except Exception:
            return None

        # El catalogo es la lista blanca: lo que no esta aqui no existe,
        # diga el modelo lo que diga.
        nombre = self._normaliza(data.get("accion", ""))
        accion = next((a for a in disponibles
                       if self._normaliza(a.nombre) == nombre), None)
        if accion is None:
            return None

        if self._confianza(data.get("confianza")) < CONFIANZA_MINIMA:
            return None

        return accion, self._args(data.get("args")), str(data.get("porque", ""))

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
            decision = ctx.policy.can_control(accion.control)

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

    def _aplicar(self, ctx: SkillContext, accion: Accion,
                 args: dict[str, Any]) -> SkillResult:
        sys_ = ctx.system
        try:
            handler: Callable[[], SkillResult] = {
                "volumen_cambiar": lambda: self._volumen(sys_, args),
                "volumen_fijar": lambda: self._volumen_fijo(sys_, args),
                "silenciar": lambda: self._silenciar(sys_),
                "reproduccion": lambda: self._reproduccion(sys_, args),
                "copiar": lambda: self._copiar(sys_, args),
                "leer_portapapeles": lambda: self._leer(sys_),
                "bloquear": lambda: self._sesion(sys_, "lock"),
                "suspender": lambda: self._sesion(sys_, "sleep"),
                "minimizar": lambda: self._minimizar(sys_, args),
            }[accion.nombre]
        except KeyError:
            return SkillResult(ok=False, error=f"sin implementacion: {accion.nombre}",
                               speak="Esa capacidad esta declarada pero no cableada.")
        return handler()

    # ══════════════════════════════ las manos
    @staticmethod
    def _entero(args: dict[str, Any], clave: str, por_defecto: int) -> int:
        try:
            return int(float(args.get(clave, por_defecto)))
        except (TypeError, ValueError):
            return por_defecto

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
