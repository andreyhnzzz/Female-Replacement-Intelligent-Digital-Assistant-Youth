"""El enrutador. Yo hablo, FRIDAY decide quien trabaja.

Los caminos, del mas barato al mas caro:

  0. CONFIRMACION  hay una accion esperando un si. Nada mas importa.
  1. SEGUIMIENTO   la frase no se sostiene sola («y eso cuanto cuesta»):
                   es el turno anterior el que la explica.
  2. RAPIDO        regex de las skills. Sin latencia, sin motor. Cubre el 80%.
  2a. EMPATE       dos skills igual de buenas y alguna hace algo: se pregunta
                   cual, en vez de adivinar.
  2b. CHARLA       nadie reconocio nada y no hay verbo de accion: es
                   conversacion, y preguntarselo al motor cuesta un turno
                   entero de latencia para confirmar lo evidente.
  3. PENSADO       el motor clasifica y, si no encaja en nada, responde libre.
  3a. RESCATE      el motor mando una frase sin verbo a una skill con efecto
                   que no reconocio nada suyo: cae a conversacion.

Y transversal a todos: si la frase venia de un dictado dudoso y la ruta
tiene consecuencias, se repite en voz alta antes de hacer nada (`_eco`).
"""
from __future__ import annotations

import asyncio
import inspect
import re
import time
from dataclasses import dataclass
from typing import Any

from memory.graph import Graph
from memory.vault import Vault
from skills import PendingAction, Skill, SkillContext, SkillResult

from .chat import Conversation, build_conversation
from .config import Config
from .engine import Engine, ask_json, enum_schema
from .lang import ENCLITICO, limpia
from .policy import Policy

# Cuanta confianza hace falta para que el enrutado rapido decida solo.
#
# Dos umbrales y no uno, y la diferencia es el **coste de equivocarse**, no
# la dificultad de acertar. Enrutar mal a una skill que lee cuesta una
# respuesta rara: el usuario repite la frase y ya. Enrutar mal a una que
# lanza, mueve o apaga cuesta que pase. El 17/08/2026 «Describete a ti misma
# en dos palabras» puntuo 0.45 contra un acceso directo y FRIDAY abrio el
# changelog de WinRAR; el enrutado siempre sera probabilistico, asi que la
# defensa es pedirle mas a lo que tiene consecuencias.
FAST_THRESHOLD = 0.62
FAST_THRESHOLD_EFECTO = 0.72

# Si las dos mejores estan mas cerca que esto, no hay ganadora: hay empate.
# Con una skill de efecto en el empate, se pregunta en vez de elegir.
MARGEN_AMBIGUO = 0.08

# Por debajo de esta confianza del STT, una orden con efecto se repite antes
# de ejecutarla. Es la exponencial del `avg_logprob` de faster-whisper.
#
# **Este numero esta puesto por criterio, no medido** — el cableado y la
# logica si estan probados, pero cual es el corte correcto depende de tu
# microfono y de tu voz, y eso solo se sabe dictando un rato. Ver el ROADMAP.
# Equivocarse por arriba es peor que por abajo: preguntar de mas entrena a
# decir «si» sin escuchar, y entonces se pierde la confirmacion que importaba.
OIDO_DUDOSO = 0.55

CONFIRM = re.compile(r"^\s*(s[ií]|dale|adelante|confirmo?|confirmado|"
                     r"hazlo|procede|correcto|ok|okay|va)\s*[.!]?\s*$", re.I)
CANCEL = re.compile(r"^\s*(no|cancela|cancelar|olv[ií]dalo|d[eé]jalo|"
                    r"detente|para|abortar?|mejor no|stop)\s*[.!]?\s*$", re.I)

# ── seguimiento de conversacion ───────────────────────────────────
# Frases que no se sostienen solas, por anafora («eso») o por ser conectivo
# mas pregunta pelada («y por que?»). Tiene que ganarle al enrutado rapido:
# «y eso cuanto cuesta» dispara el `\bcuanto\b` de `metricas` y devuelve la
# CPU. Contra un disparador corto y comun el puntaje no puede ayudar.
FOLLOWUP = re.compile(
    r"(\b(eso|esa|ese|esos|esas|aquello|lo mismo|lo anterior|lo de antes|"
    r"lo que (dijiste|me dijiste|acabas de decir))\b"
    r"|^\s*(y|pero|entonces|osea|o sea)\s+(por\s+qu[eé]|para\s+qu[eé]|c[oó]mo|"
    r"cu[aá]ndo|d[oó]nde|qui[eé]n|cu[aá]nto|qu[eé])\b"
    r"|^\s*(y|pero|entonces)\s*[.?!]*\s*$"
    r"|^\s*(por\s+qu[eé]|c[oó]mo\s+as[ií])\s*[.?!]*\s*$"
    r"|^\s*(explicam?e|expl[ií]came|ampl[ií]a|profundiza|dame m[aá]s|"
    r"cu[eé]ntame m[aá]s|sigue|contin[uú]a)\b"
    r"|^\s*no\s+(te\s+)?entend[ií]\b)", re.I)

# Un verbo de accion cancela el seguimiento: «abre eso» lleva anafora pero
# es una orden, y las ordenes son de las skills.
#
# El sufijo `(?:me|te|se|lo|la|le|los|las|nos)*` no es adorno: en español el
# pronombre se pega al imperativo, y `\babre\b` **no casa con «abrelo»** —
# la frontera de palabra exige un no-alfanumerico detras y ahi hay una «l».
# Sin eso, «abrelo» no contaba como orden: se tomaba por continuacion de la
# conversacion (`is_followup` pide que NO haya verbo) y acababa en charla en
# vez de abrir nada. Es la forma mas natural de pedirlo y era la que menos
# funcionaba.
# Y con el pronombre pegado el imperativo **lleva tilde**: «ábrelo»,
# «guárdalo», «ciérralas». Es lo que transcribe el STT, asi que los verbos
# que admiten enclitico llevan su clase de acento.
ACTION = re.compile(
    r"\b([aá]bre|abrir|l[aá]nza|ejec[uú]ta|inicia|arranca|c[ií]erra|enfoca|"
    r"organiza|mu[eé]ve|renombra|borra|recuerda|ap[uú]nta|an[oó]ta|gu[aá]rda|"
    r"escribe|b[uú]sca|investiga|s[uú]be|b[aá]ja|silencia|pausa|reproduce|"
    r"bloquea|c[oó]pia|pega|cambia a)" + ENCLITICO + r"\b", re.I)


# comandos literales — no gastan motor
DIRECT = {
    r"^\s*(silencio|c[aá]llate|mute)\s*[.!]?\s*$": "_mute",
    r"^\s*(escucha|unmute|habla)\s*[.!]?\s*$": "_unmute",
    r"^\s*(repite|otra vez|de nuevo)\s*[.!]?\s*$": "_repeat",
    r"^\s*(reparar? (el )?grafo|arregla (los )?enlaces|heal)\s*[.!]?\s*$": "_heal",
    r"^\s*(qu[eé] puedes hacer|ayuda|capacidades)\s*[.!?]?\s*$": "_help",
    r"^\s*(cambiemos de tema|nuevo tema|empecemos de cero|"
    r"olvida (la conversaci[oó]n|el hilo))\s*[.!?]?\s*$": "_reset_chat",
}


@dataclass
class Route:
    skill: str
    confidence: float
    how: str              # fast | engine | fallback | direct | confirm | ambiguo
    scores: dict[str, float]
    # Las candidatas que empataron, cuando `how == "ambiguo"`. La decision
    # de cual es se la queda el usuario, que es quien sabe.
    opciones: tuple[str, ...] = ()
    # Cuando la frase pedia dos cosas: la mitad que atiende esta ruta y la
    # que queda. Vacias en el caso normal, que es casi siempre.
    primera: str = ""
    resto: str = ""


class Router:
    def __init__(self, cfg: Config, vault: Vault, graph: Graph, engine: Engine,
                 skills: dict[str, Skill], system: Any = None,
                 policy: Policy | None = None):
        self.cfg = cfg
        self.vault = vault
        self.graph = graph
        self.engine = engine
        self.skills = skills
        self.system = system
        self.policy = policy
        self.last_result: SkillResult | None = None
        self.pending: PendingAction | None = None
        self.chat: Conversation = build_conversation(cfg)
        self.fast_chat = bool(cfg.get("chat.fast_conversation", True))
        self.smalltalk_words = int(cfg.get("chat.smalltalk_max_words", 12))

    # ── contexto ──────────────────────────────────────────────────
    def _ctx(self, text: str = "") -> SkillContext:
        return SkillContext(cfg=self.cfg, vault=self.vault, graph=self.graph,
                            engine=self.engine, text=text,
                            system=self.system, policy=self.policy)

    # ── seguimiento ───────────────────────────────────────────────
    def is_followup(self, text: str) -> bool:
        """¿Continua el turno anterior en vez de empezar uno? Hilo vivo,
        anafora y ningun verbo de accion — las tres."""
        if not self.chat.active:
            return False
        return bool(FOLLOWUP.search(text)) and not ACTION.search(text)

    def _is_smalltalk(self, text: str, scores: dict[str, float]) -> bool:
        """¿Se puede dar por conversacion sin preguntarle al motor?

        La condicion fuerte es que **ninguna** skill haya reconocido nada: el
        paso pensado existe para rescatar frases que las regex no cubren, y
        si algo puntuo, esa duda vale los cuatro segundos.
        """
        if not self.fast_chat or any(scores.values()):
            return False
        return (not ACTION.search(text)
                and len(text.split()) <= self.smalltalk_words)

    # ── cuanta confianza hace falta, y cuando no hay ganadora ─────
    def _umbral(self, nombre: str, text: str) -> float:
        """Lo que se le exige a esta skill para actuar sin preguntar.

        La primera version de esto subia el listón a **toda** skill de
        efecto, y estaba mal: «abre eso» es una orden de tres palabras,
        perfectamente clara, y se quedaba fuera del camino rapido para
        acabar costando un turno de motor. Castigar la brevedad es castigar
        justo el caso en que FRIDAY tiene que ser instantanea.

        Lo que separa una orden de un accidente no es el puntaje, es el
        **verbo**. «Abre eso» pide algo; «describete a ti misma en dos
        palabras» no pide nada y aun asi rozaba a `sistema` por compartir
        una palabra. Asi que el listón sube solo cuando la frase no tiene
        verbo de accion ni nombra a la skill: ahi, que una skill que lanza
        programas sea la mejor candidata es mas sospechoso que informativo.
        """
        skill = self.skills.get(nombre)
        if skill is None or not skill.tiene_efecto:
            return FAST_THRESHOLD
        if ACTION.search(text) or re.search(rf"\b{re.escape(nombre)}\b", text, re.I):
            return FAST_THRESHOLD
        return FAST_THRESHOLD_EFECTO

    def _empate(self, scores: dict[str, float], best: str) -> tuple[str, ...]:
        """Las candidatas que empatan con la mejor, si hay algo que perder.

        Solo se declara empate cuando **alguna de las dos tiene efecto**. Dos
        skills que solo leen peleandose por una frase no merecen una
        pregunta: elegir la que sea da una respuesta rara y ya. Pero
        «organiza esto» empatado entre `archivos` (mueve cuarenta ficheros) y
        otra cosa no es una duda que convenga resolver adivinando.

        Preguntar cuesta una frase. Equivocarse de skill con efecto puede
        costar una tarde.
        """
        mejor = scores[best]
        if mejor < FAST_THRESHOLD:
            # Nadie destaca: esto no es un empate, es que nadie lo reconocio.
            # Ya hay un camino para eso —el motor— y es mejor que preguntar.
            return ()
        cerca = [n for n, s in scores.items()
                 if n != best and mejor - s <= MARGEN_AMBIGUO and s > 0]
        if not cerca:
            return ()
        candidatas = (best, *sorted(cerca, key=lambda n: -scores[n]))
        if not any(self.skills[n].tiene_efecto for n in candidatas
                   if n in self.skills):
            return ()
        return candidatas[:3]

    # ── una frase, dos peticiones ─────────────────────────────────
    @staticmethod
    def _partir(text: str) -> tuple[str, str]:
        """Parte «busca el informe y abrelo» en sus dos mitades.

        Devuelve `("", "")` si no hay dos peticiones, que es el caso normal.

        **Partir de mas es el riesgo entero de esta funcion**, asi que las
        reglas son deliberadamente estrechas y ninguna es opcional:

          1. Se corta por un conector explicito (`y`, `y luego`, `despues`).
          2. **Las dos mitades tienen que llevar verbo de accion.** Esto es
             lo que salva «busca el informe y el contrato», que es UNA
             busqueda de dos cosas y no dos peticiones. Sin verbo detras del
             conector, no se parte.
          3. Se corta por el **ultimo** conector que cumpla, no por el
             primero: en «busca el pdf de ventas y marketing y abrelo», el
             primer «y» esta dentro del nombre.
          4. Una sola vez. Esto no es un planificador y no debe parecerlo:
             dos mitades, tope duro. Encadenar tres cosas seguidas sin que
             el usuario vea nada intermedio es justo donde una frase mal
             oida deja de poder repararse.
        """
        limpio = text.strip()
        if len(limpio.split()) < 4:
            return "", ""

        corte = None
        for m in re.finditer(r"\s+(?:y\s+luego|y\s+despu[eé]s|y\s+ahora|luego|"
                             r"despu[eé]s|y)\s+", limpio, re.I):
            izquierda, derecha = limpio[:m.start()], limpio[m.end():]
            if (len(izquierda.split()) >= 2 and len(derecha.split()) >= 1
                    and ACTION.search(izquierda) and ACTION.search(derecha)):
                corte = m
        if corte is None:
            return "", ""
        return limpio[:corte.start()].strip(), limpio[corte.end():].strip()

    # ── decidir ───────────────────────────────────────────────────
    async def decide(self, text: str, encadenar: bool = True) -> Route:
        clean = text.strip()

        # Si la frase pide dos cosas, esta ruta atiende la PRIMERA y se
        # queda con el resto. `encadenar=False` en la segunda vuelta: dos
        # mitades es el tope, y sin este freno una frase con tres conectores
        # se enrutaria en cascada sin que nadie vea los pasos intermedios.
        primera, resto = self._partir(clean) if encadenar else ("", "")
        if resto:
            ruta = await self.decide(primera, encadenar=False)
            ruta.primera, ruta.resto = primera, resto
            return ruta

        # 0. una accion espera confirmacion: tiene prioridad sobre todo
        if self.pending is not None:
            if self.pending.expired:
                self.pending = None
            elif CONFIRM.match(clean):
                return Route("_confirm", 1.0, "confirm", {})
            elif CANCEL.match(clean):
                return Route("_cancel_pending", 1.0, "confirm", {})

        for pat, name in DIRECT.items():
            if re.match(pat, clean, re.I):
                return Route(name, 1.0, "direct", {})

        # 1. continuacion del hilo: la frase depende del turno anterior
        if self.is_followup(clean):
            return Route("none", 0.9, "chat", {})

        scores = {n: s.matches(clean) for n, s in self.skills.items()}
        best = max(scores, key=scores.get) if scores else ""

        if best and scores[best] > 0:
            empate = self._empate(scores, best)
            if empate:
                return Route(best, scores[best], "ambiguo", scores,
                             opciones=empate)
            if scores[best] >= self._umbral(best, clean):
                return Route(best, scores[best], "fast", scores)

        # 2b. charla evidente: nadie reconocio nada, no hay verbo de accion y
        # la frase es corta. Un turno de conversacion gastaba DOS llamadas al
        # motor —clasificar y luego responder— y por `claude_code` cada una
        # ronda los cuatro segundos. Esta es la que sobra.
        if self._is_smalltalk(clean, scores):
            return Route("none", 0.6, "chat-fast", scores)

        catalog = "\n".join(f"- {n}: {s.description}" for n, s in self.skills.items())
        prompt = (
            f"SKILLS:\n{catalog}\n"
            "- none: conversacion. Charla, opiniones, preguntas generales, "
            "desahogos, o cualquier cosa que no pida una accion concreta.\n\n"
            # «none» se nombra dos veces: un modelo pequeño casi nunca elige
            # la ultima opcion de una lista de catorce.
            "Si el usuario no te esta PIDIENDO que hagas algo, es \"none\".\n"
            "Tambien es \"none\" si te pregunta por TI (quien eres, como "
            "estas, que sabes hacer) o si es una pregunta de conocimiento "
            "general que se contesta hablando.\n\n"
            # La peticion al final, pegada a la respuesta: con un 8B, es lo
            # que mas mueve el acierto de esta llamada.
            f"PETICION DE VOZ:\n\"{clean}\"\n\n"
            "Enruta esa peticion a UNA skill de la lista.\n\n"
            'Responde SOLO: {"skill": "nombre", "confidence": 0.85, '
            '"why": "5 palabras"}'
        )
        schema = enum_schema({"skill": list(self.skills) + ["none"],
                              "confidence": "number", "why": "string"},
                             requeridos=["skill"])
        try:
            data = await ask_json(self.engine, prompt, schema=schema) or {}
            name = str(data.get("skill", "none")).strip().lower()
            try:
                conf = float(data.get("confidence", 0.5))
            except (TypeError, ValueError):
                conf = 0.5          # el numero es informativo; el nombre manda
            elegida = name if name in self.skills else "none"
            if self._sospechoso(elegida, clean, scores):
                # El motor mando una frase sin verbo a una skill que actua, y
                # ninguno de los disparadores de esa skill reconocio nada.
                # Es exactamente la forma del 17/08/2026: «Describete a ti
                # misma en dos palabras» -> `sistema`, confianza 0.85, y
                # FRIDAY abrio el changelog de WinRAR. La confianza que
                # declara el modelo no vale como guardia porque **es el
                # modelo el que se esta equivocando**; lo que si vale es que
                # dos señales independientes no coincidan.
                return Route("none", conf, "chat-rescate", scores)
            return Route(elegida, conf, "engine", scores)
        except Exception:
            return Route(best or "none", scores.get(best, 0.0), "fallback", scores)

    def _sospechoso(self, elegida: str, text: str, scores: dict[str, float]) -> bool:
        """¿El motor mando esto a una skill con efecto sin ningun apoyo?

        Tres condiciones a la vez, y las tres hacen falta:

          1. La skill **hace** algo (si solo lee, equivocarse sale barato).
          2. La frase no tiene **ningun verbo de accion**: no esta pidiendo.
          3. Los disparadores de esa skill puntuaron **cero**: ni una palabra
             suya aparece.

        Con las tres, lo probable no es que el usuario haya pedido algo raro:
        es que el modelo haya elegido mal. Cae a conversacion, que es la
        respuesta correcta a una frase que no pide nada.
        """
        skill = self.skills.get(elegida)
        if skill is None or not skill.tiene_efecto:
            return False
        return not ACTION.search(text) and scores.get(elegida, 0.0) <= 0.0

    # ── ejecutar ──────────────────────────────────────────────────
    async def dispatch(self, text: str, route: Route | None = None,
                       oido: float = 1.0) -> tuple[Route, SkillResult]:
        """Ejecuta la ruta. `oido` es lo seguro que estaba el STT (0..1).

        Un turno escrito llega con 1.0 y no cambia nada. Uno dictado llega
        con lo que dijo faster-whisper, y ahi si: ver `_eco`.
        """
        route = route or await self.decide(text)
        t0 = time.time()

        # Con la frase partida, esta ruta atiende solo su mitad: pasarle la
        # frase entera a `archivos` le haria buscar «el informe y abrelo».
        propio = route.primera or text

        if route.how == "ambiguo":
            res = self._preguntar_cual(text, route)
        elif route.skill.startswith("_"):
            res = await self._builtin(route.skill)
        elif route.skill in self.skills:
            # El eco repite la frase ENTERA, no la mitad: lo que hay que
            # confirmar es lo que se dijo, y confirmarlo relanza la cadena
            # completa desde el principio.
            duda = self._eco(text, route, oido)
            if duda is not None:
                res = duda
            else:
                ctx = self._ctx(propio)
                try:
                    res = await self.skills[route.skill].run(ctx)
                except Exception as exc:
                    res = SkillResult(
                        ok=False, error=f"{type(exc).__name__}: {exc}",
                        speak=f"La skill {route.skill} fallo.",
                        display=f"# Error en `{route.skill}`\n\n```\n{exc}\n```")
                if route.resto:
                    res = await self._encadenar(res, route)
        else:
            res = await self._freeform(text)

        # una skill que devuelve accion pendiente la deja armada aqui
        if res.pending is not None:
            self.pending = res.pending

        res.data["_ms"] = int((time.time() - t0) * 1000)
        res.data["_route"] = {"skill": route.skill, "how": route.how,
                              "confidence": route.confidence}
        res.data["_pending"] = self.pending.describe if self.pending else ""

        if res.ok and not route.skill.startswith("_"):
            self.last_result = res

        # El hilo recoge tambien lo que atendio una skill, o «y eso cuanto
        # pesa» tras un briefing no tendria a que referirse. Se guarda lo
        # hablado, no el markdown: es lo que el usuario oyo.
        if not route.skill.startswith("_"):
            self.chat.add("user", text)
            self.chat.add("assistant", res.speak or res.error)

        return route, res

    # ── pasar el testigo ──────────────────────────────────────────
    async def _encadenar(self, primero: SkillResult, route: Route) -> SkillResult:
        """La segunda mitad de la frase, con lo que resolvio la primera.

        Cuatro frenos, y cada uno tapa una forma distinta de hacer daño:

          1. **Si la primera no salio bien, no hay segunda.** Abrir el
             resultado de una busqueda que no encontro nada es abrir
             cualquier cosa.
          2. **Si la primera espera un «si», la cadena se detiene ahi.**
             Encadenar por encima de una confirmacion pendiente seria
             ejecutar lo que el usuario todavia no ha autorizado (regla 6).
          3. **La segunda skill tiene que ACEPTAR el tipo entregado.** No se
             le pasa la frase para que la reinterprete: recibe un objeto ya
             resuelto o no corre. «Abrelo» suelto haria que `sistema`
             buscara una aplicacion llamada «lo».
          4. **La segunda pasa por su politica**, porque es una ejecucion
             normal de skill. Que se la pidieras en la misma frase no la
             convierte en parte de la primera.

        Cuando algo de esto falla, se hace la primera mitad y **se dice** que
        la segunda no. Media tarea anunciada entera es peor que media tarea.
        """
        if not primero.ok or primero.pending is not None:
            return primero

        ruta2 = await self.decide(route.resto, encadenar=False)
        skill2 = self.skills.get(ruta2.skill)
        entrega = primero.entrega

        if entrega is None or skill2 is None or entrega.kind not in skill2.acepta:
            falta = (f"no se encadenar «{route.resto}» con "
                     f"{'eso' if entrega is None else 'un ' + entrega.kind}")
            primero.display += f"\n\n---\n\n> Hice lo primero. Lo segundo, {falta}."
            primero.data["cadena"] = {"resto": route.resto, "hecho": False,
                                      "motivo": falta}
            return primero

        ctx = self._ctx(route.resto)
        ctx.slots["entrega"] = entrega
        try:
            segundo = await skill2.run(ctx)
        except Exception as exc:
            primero.display += f"\n\n---\n\n> Lo segundo fallo: `{exc}`"
            primero.data["cadena"] = {"resto": route.resto, "hecho": False,
                                      "motivo": str(exc)[:120]}
            return primero

        return SkillResult(
            speak=" ".join(p for p in (primero.speak, segundo.speak) if p),
            display=f"{primero.display}\n\n---\n\n{segundo.display}",
            data={**primero.data, **segundo.data,
                  "cadena": {"resto": route.resto, "hecho": True,
                             "skill": skill2.name, "entrega": str(entrega)}},
            writes=[*primero.writes, *segundo.writes],
            ok=segundo.ok, error=segundo.error,
            # La confirmacion de la segunda mitad sube tal cual: si abrir
            # aquello necesitaba un «si», sigue necesitandolo.
            pending=segundo.pending)

    # ── no adivinar: preguntar ────────────────────────────────────
    def _preguntar_cual(self, text: str, route: Route) -> SkillResult:
        """Dos skills empatadas y una de ellas hace algo. Se pregunta.

        No arma una accion pendiente: la respuesta no es «si» ni «no», es un
        nombre, y esa frase se enruta sola en el turno siguiente con la
        ventaja de que ahora el usuario esta nombrando la skill — que es la
        señal mas fuerte que tiene el puntaje.
        """
        nombres = [n for n in route.opciones if n in self.skills]
        humanos = [f"**{n}** ({self.skills[n].description.split('.')[0].lower()})"
                   for n in nombres]
        hablado = " o ".join(n for n in nombres[:2])
        return SkillResult(
            speak=f"No se si te refieres a {hablado}. ¿Cual?",
            display=("# ¿Cual de las dos?\n\nEsa frase encaja igual de bien en "
                     "mas de un sitio, y alguna de ellas cambia cosas. Dime "
                     "cual:\n\n" + "\n".join(f"- {h}" for h in humanos)),
            data={"ambiguo": nombres,
                  "scores": {n: route.scores.get(n, 0.0) for n in nombres}})

    def _eco(self, text: str, route: Route, oido: float) -> SkillResult | None:
        """Repetir lo que se entendio antes de hacer algo con consecuencias.

        None = adelante. Un `SkillResult` = espera un «si».

        El STT no falla de golpe: falla poco a poco y con seguridad aparente.
        Cuando `avg_logprob` viene bajo, lo transcrito suele ser parecido a
        lo dicho pero no igual — «Desactual Bluetooth» por «desactiva el
        Bluetooth»— y ahi el enrutado hace su trabajo sobre un texto que
        nunca se dijo. Ninguno de los guardias de despues puede verlo: la
        politica autoriza la accion correcta para la frase equivocada.

        Asi que el eco solo mira dos cosas, y las dos importan:

        - **La skill tiene efecto.** Repetir una pregunta que solo iba a leer
          algo es hacer perder el tiempo, y confirmar de mas entrena a decir
          «si» sin escuchar, que es como se pierde la confirmacion que si
          importaba.
        - **El oido venia dudoso.** Un turno escrito llega con 1.0 y no pasa
          por aqui nunca.
        """
        skill = self.skills.get(route.skill)
        if skill is None or not skill.tiene_efecto or oido >= OIDO_DUDOSO:
            return None

        limpio = limpia(text)

        async def _seguir() -> SkillResult:
            # Se rearranca el turno entero, no solo la skill: si lo que
            # confirmo fue el TEXTO, la ruta hay que volver a calcularla
            # sobre el mismo texto, con `oido` ya resuelto por el «si».
            _r, res = await self.dispatch(text, route, oido=1.0)
            return res

        return SkillResult(
            speak=f"¿Dijiste «{limpio}»?",
            display=(f"# ¿Te oi bien?\n\n> {limpio}\n\nTe entendi con poca "
                     f"claridad ({oido:.0%}) y esto **{skill.name}** lo "
                     f"cambia. Di «si» y voy."),
            pending=PendingAction(describe=limpio, run=_seguir, ttl_s=90.0),
            data={"eco": limpio, "oido": round(oido, 3), "skill": skill.name})

    # ── conversacion libre ────────────────────────────────────────
    def _recall(self, text: str) -> tuple[list, str]:
        """Notas que vienen al caso, con su vecindad en el grafo.

        Recorre y parsea el vault entero (no hay indice, regla 1), asi que va
        en un hilo: hacerlo en el bucle de eventos congela el HUD y retrasa
        cualquier evento del bus justo antes de la parte lenta del turno.
        """
        hits = self.vault.search(text, limit=3)
        ctxt = self.graph.context_for([h.title for h in hits], depth=1,
                                      max_chars=3500) if hits else ""
        return hits, ctxt

    async def _freeform(self, text: str) -> SkillResult:
        """Conversar: prosa, sin contrato JSON.

        Pedir JSON aqui encoge las respuestas a una frase de tramite y con un
        8B rompe el formato cada tanto. La persona da el tono, no la
        estructura.
        """
        historia = self.chat.transcript(limit=int(self.cfg.get("chat.max_chars", 4000)))
        hits, ctxt = await asyncio.to_thread(self._recall, text)

        prompt = (
            (f"CONVERSACION HASTA AHORA:\n{historia}\n\n" if historia else "") +
            (f"NOTAS DEL VAULT QUE PUEDEN VENIR AL CASO:\n{ctxt}\n\n" if ctxt else "") +
            f"{self.chat.user_title} dice: \"{text}\"\n\n"
            "Responde como en una conversacion hablada: directo, sin preambulo "
            "y sin ofrecer ayuda al final. Si la frase se refiere a algo dicho "
            "antes, resuelvelo con la conversacion de arriba. Si no lo sabes, "
            "dilo. Texto plano o markdown simple; nada de JSON."
        )
        try:
            raw = (await self.engine.complete(prompt, system=self.cfg.persona())).strip()
            if not raw:
                return SkillResult(ok=False, error="respuesta vacia",
                                   speak="Me quede en blanco, Jefe.",
                                   display="# Sin respuesta")
            return SkillResult(speak=self._for_voice(raw), display=raw,
                               data={"sources": [h.rel for h in hits],
                                     "turns": len(self.chat)})
        except Exception as exc:
            return SkillResult(ok=False, error=str(exc),
                               speak="El motor no responde.",
                               display=f"# Motor caido\n\n```\n{exc}\n```")

    def _for_voice(self, text: str) -> str:
        """Recorta por frases enteras, nunca a media palabra: cortarse a
        mitad de una idea suena peor que una respuesta corta. El panel
        siempre lleva el texto completo."""
        limit = int(self.cfg.get("chat.speak_max_chars", 700))
        plain = re.sub(r"\s+", " ", text).strip()
        if len(plain) <= limit:
            return plain

        out = ""
        for frase in re.split(r"(?<=[.!?])\s+", plain):
            if len(out) + len(frase) + 1 > limit:
                break
            out = f"{out} {frase}".strip()
        return out or plain[:limit].rsplit(" ", 1)[0]

    # ── comandos internos ─────────────────────────────────────────
    async def _builtin(self, name: str) -> SkillResult:
        if name == "_confirm":
            action = self.pending
            self.pending = None
            if action is None or action.expired:
                return SkillResult(speak="Ya no hay nada pendiente.",
                                   display="# Nada pendiente")
            try:
                salida = action.run()
                # Casi todas las acciones pendientes son sincronas; la que
                # rearranca un turno tras el eco de una transcripcion dudosa
                # no puede serlo, porque vuelve a pasar por el motor.
                if inspect.isawaitable(salida):
                    salida = await salida
                return salida
            except Exception as exc:
                return SkillResult(ok=False, error=str(exc),
                                   speak="Fallo al aplicar.",
                                   display=f"# Fallo\n\n```\n{exc}\n```")

        if name == "_cancel_pending":
            desc = self.pending.describe if self.pending else ""
            self.pending = None
            return SkillResult(
                speak="Cancelado." if desc else "No habia nada pendiente.",
                display=f"# Cancelado\n\n~~{desc}~~" if desc else "# Nada pendiente")

        if name == "_reset_chat":
            previos = len(self.chat)
            self.chat.clear()
            return SkillResult(
                speak="Hilo limpio, Jefe." if previos else "No habia hilo que limpiar.",
                display=f"# Conversacion reiniciada\n\n{previos} turnos descartados.",
                data={"cleared": previos})

        if name == "_repeat":
            return self.last_result or SkillResult(speak="No hay nada que repetir.",
                                                   display="—")

        if name == "_heal":
            created = self.graph.heal()
            return SkillResult(
                speak=f"Cree {len(created)} stubs. Grafo reparado." if created
                      else "No hay enlaces rotos.",
                display="# Reparacion del grafo\n\n" +
                        ("\n".join(f"- [[{c}]]" for c in created) or "Nada roto."),
                data={"created": created}, writes=created)

        if name == "_help":
            lines = ["# Capacidades", ""]
            for s in self.skills.values():
                falta = ""
                if s.needs and self.system is not None:
                    missing = [n for n in s.needs if getattr(self.system, n, None) is None]
                    falta = f"  _(sin {', '.join(missing)})_" if missing else ""
                lines.append(f"- **{s.name}** — {s.description}{falta}")
            return SkillResult(speak=f"{len(self.skills)} capacidades activas.",
                               display="\n".join(lines),
                               data={"skills": list(self.skills)})

        return SkillResult(speak="", display="", data={"command": name})

    def catalog(self) -> list[dict[str, Any]]:
        return [s.spec() for s in self.skills.values()]
