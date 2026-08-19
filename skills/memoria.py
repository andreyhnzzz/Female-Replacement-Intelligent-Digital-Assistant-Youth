"""SKILL — memoria: consolidar el diario viejo y decir cuanto ocupa.

    «Consolida la memoria»      resume las diarias viejas y retira los originales
    «Cuanto ocupa la memoria»   el estado del vault, sin tocar nada

El trabajo de verdad lo hace `memory/consolidate.py`; esta skill es la boca:
traduce el informe a una frase y, cuando la politica pide un si, lo pide.

FRIDAY tambien consolida sola cada tantas horas (`friday.py::_memory_keeper`).
Que exista la orden hablada no es redundante: cuando el disco aprieta, nadie
quiere esperar al siguiente ciclo, y ver el plan antes de que se ejecute solo
es posible si se puede preguntar.
"""
from __future__ import annotations

import re

from memory.consolidate import Consolidator

from .base import PendingAction, Skill, SkillContext, SkillResult

# «consolida», «compacta», «limpia»... sobre la memoria.
COMPACTA = re.compile(
    r"\b(consolida|consolidar|compacta|compactar|comprime|comprimir|"
    r"limpia|limpiar|depura|depurar|resume|resumir|adelgaza|ordena)\b", re.I)

# Lo que hace que la frase hable de la memoria y no de otra cosa.
MEMORIA = re.compile(
    r"\b(memoria|vault|b[oó]veda|diario|diarias|notas viejas|d[ií]as viejos|"
    r"apuntes viejos)\b", re.I)

# Preguntar el tamaño no es pedir que se toque nada.
CUANTO = re.compile(
    r"\b(cu[aá]nto (ocupa|pesa|espacio)|qu[eé] tan grande|tama[ñn]o (de|del)|"
    r"estado (de|del) (la memoria|vault)|c[oó]mo (esta|va) la memoria)\b", re.I)

# La RAM no es esto. Sin esta salida, «cuanta memoria me queda» acabaria aqui
# en vez de en `metricas`, porque esta skill se llama justamente «memoria».
RAM = re.compile(
    r"\bram\b|\bmemoria (libre|disponible|f[ií]sica|del sistema)\b|\bcpu\b", re.I)


class MemoriaSkill(Skill):
    name = "memoria"
    description = ("Consolida las notas diarias viejas en un solo markdown, "
                   "omite lo rutinario y retira los originales.")
    triggers = [
        r"\bconsolida (la )?memoria\b", r"\bcompacta (la )?memoria\b",
        r"\blimpia (la )?memoria\b", r"\bresume (los )?d[ií]as viejos\b",
        r"\bcu[aá]nto ocupa\b", r"\bmemoria consolidada\b",
    ]
    needs = ()

    def __init__(self, ctx_cfg) -> None:
        super().__init__(ctx_cfg)
        self._cfg = ctx_cfg

    # ── enrutado ──────────────────────────────────────────────────
    def matches(self, text: str) -> float:
        """Puntaje propio, y la razon es el nombre de la skill.

        El puntaje generico regala 0.35 a quien se llame como una palabra de
        la frase, y «memoria» sale en «cuanta memoria RAM me queda», que es
        de `metricas`. Aqui manda el par verbo+objeto: compactar algo, y que
        ese algo sea la memoria. Si solo hay una de las dos, se devuelve 0 y
        se le deja la ventana a quien corresponda.
        """
        low = text.lower()
        if RAM.search(low):
            return 0.0
        if COMPACTA.search(low) and MEMORIA.search(low):
            return 0.96
        if CUANTO.search(low) and MEMORIA.search(low):
            return 0.9
        return super().matches(text)

    # ── ejecucion ─────────────────────────────────────────────────
    async def run(self, ctx: SkillContext) -> SkillResult:
        con = Consolidator.from_config(self._cfg, ctx.vault)
        low = ctx.text.lower()

        # Preguntar cuanto ocupa no puede ejecutar nada: `plan()` no escribe.
        if CUANTO.search(low) and not COMPACTA.search(low):
            return self._estado(ctx, con)

        p = con.plan()
        if not p:
            st = ctx.vault.stats()
            return SkillResult(
                speak=(f"No hay nada que consolidar. Tengo {st['notes']} notas "
                       f"y ninguna diaria pasa de {con.keep_days} dias."),
                display=(f"# Memoria al dia\n\n{st['notes']} notas · "
                         f"{st['bytes'] // 1024} KB\n\nNinguna nota diaria "
                         f"supera los {con.keep_days} dias, que es el umbral "
                         f"para consolidar."),
                data={"pending_notes": 0, "vault": st})

        rep = await con.run(ctx.engine, ctx.policy)

        if not rep.ok:
            return SkillResult(
                ok=False, error=rep.reason,
                speak=f"No pude consolidar: {rep.reason}.",
                display=f"# Consolidacion detenida\n\n> {rep.reason}",
                data=rep.to_json())

        # La politica pidio un si antes de retirar. El resumen YA esta escrito
        # —eso no borra nada— y lo que espera confirmacion es solo la retirada.
        if rep.confirm:
            return SkillResult(
                speak=(f"Resumi {rep.notes} dias en una nota. Retiro los "
                       f"originales? {rep.confirm}."),
                display=self._panel(rep, con, retirado=False),
                data=rep.to_json(),
                writes=[rep.target],
                pending=PendingAction(
                    describe=f"retirar {rep.notes} notas diarias ya resumidas",
                    run=lambda: self._retirar(ctx, con, rep),
                    ttl_s=180.0))

        return SkillResult(
            speak=self._frase(rep),
            display=self._panel(rep, con, retirado=True),
            data=rep.to_json(),
            writes=[rep.target])

    # ── la confirmacion ───────────────────────────────────────────
    def _retirar(self, ctx: SkillContext, con: Consolidator, rep) -> SkillResult:
        """Se ejecuta cuando el usuario dice que si.

        Se recalcula el plan en vez de reusar el de hace un minuto: entre la
        pregunta y el si pudo escribirse otra nota, y la lista de rutas es lo
        unico que aqui no puede estar rancio.
        """
        p = con.plan()
        rep.retired, rep.shrunk = con.retirar(p.sources)
        _, rep.freed = ctx.vault.purge_trash(con.trash_days)
        return SkillResult(
            speak=self._frase(rep),
            display=self._panel(rep, con, retirado=True),
            data=rep.to_json(), writes=[rep.target])

    # ── informes ──────────────────────────────────────────────────
    def _estado(self, ctx: SkillContext, con: Consolidator) -> SkillResult:
        st = ctx.vault.stats()
        p = con.plan()
        speak = (f"El vault son {st['notes']} notas, {st['bytes'] // 1024} "
                 f"kilobytes.")
        if p:
            speak += (f" Hay {len(p.sources)} diarias viejas que puedo "
                      f"consolidar en una.")
        return SkillResult(
            speak=speak,
            display=(f"# Memoria\n\n**{st['notes']}** notas · "
                     f"**{st['bytes'] // 1024} KB** · {st['links']} enlaces\n\n"
                     f"- `raw/` — {st['raw']}\n- `wiki/` — {st['wiki']}\n"
                     f"- `outputs/` — {st['outputs']}\n\n"
                     + (f"### Consolidable\n{len(p.sources)} diarias del "
                        f"{p.rango} · {p.bytes // 1024} KB · "
                        f"{len(p.esencia)} apuntes con fondo y {p.rutina} "
                        f"rutinas.\n\nDi «consolida la memoria».\n"
                        if p else "Nada pendiente de consolidar.\n")),
            data={"vault": st, "pending_notes": len(p.sources),
                  "pending_bytes": p.bytes})

    @staticmethod
    def _frase(rep) -> str:
        trozos = [f"Consolide {rep.notes} dias en una sola nota"]
        if rep.dropped:
            trozos.append(f"omiti {rep.dropped} rutinas")
        if rep.retired:
            kb = rep.shrunk // 1024
            # Bajo el kilobyte no se dice el peso: «cero kilobytes menos»
            # suena a que no sirvio de nada, y lo que sirvio fue quitar
            # archivos del recorrido, no los bytes.
            trozos.append(f"el vault tiene {kb} kilobytes menos" if kb
                          else f"retire {rep.retired} notas del recorrido")
        return ", ".join(trozos) + "."

    @staticmethod
    def _panel(rep, con: Consolidator, retirado: bool) -> str:
        lineas = [
            "# Memoria consolidada",
            "",
            f"**{rep.rango}**",
            "",
            f"- {rep.notes} notas diarias → [[Memoria consolidada]]",
            f"- {rep.kept} apuntes retenidos · {rep.dropped} omitidos o fundidos",
        ]
        disco = f"- {rep.shrunk // 1024} KB fuera del vault vivo"
        if rep.freed:
            disco += f" · {rep.freed // 1024} KB liberados del disco"
        lineas.append(disco)
        lineas.append(
            f"- Originales en la papelera, se borran solos a los "
            f"{con.trash_days} dias" if retirado else
            "- Los originales siguen donde estaban")
        lineas += ["", "_Resumen del motor._" if rep.by_engine else
                   "_Sin motor: los apuntes esenciales pasaron tal cual._"]
        return "\n".join(lineas) + "\n"
