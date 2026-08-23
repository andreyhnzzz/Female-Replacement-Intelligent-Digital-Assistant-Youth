"""Prueba de humo sin voz ni motor: vault, grafo, skills, enrutador.

    python scripts/smoke_test.py
"""
from __future__ import annotations

import asyncio
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# La salida lleva flechas y acentos. Si stdout no es UTF-8 —tuberia,
# redireccion, CI— `print` revienta con UnicodeEncodeError y aborta la
# suite a media pasada, que parece un fallo de las pruebas y no lo es.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from core.config import load as load_config
from core.engine import Engine
from core.router import Router
from memory.graph import Graph
from memory.vault import Vault, parse_frontmatter, render_frontmatter
from skills import SkillContext, build_skills

PASS, FAIL = "\033[92m ok \033[0m", "\033[91mFALLA\033[0m"
results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, note: str = "") -> None:
    results.append((name, bool(cond), note))
    print(f"  [{PASS if cond else FAIL}] {name}{'  — ' + note if note else ''}")


class FakeEngine(Engine):
    """Motor de mentira: determinista, sin red. Para probar el cableado."""
    name = "fake"

    def __init__(self, cfg):
        super().__init__(cfg)
        self.calls: list[str] = []

    async def complete(self, prompt: str, system: str = "", **kw) -> str:
        self.calls.append(prompt)
        if '"esencial"' in prompt:
            return ('{"titulo": "Lo que quedo", '
                    '"esencial": ["El deploy es los viernes"]}')
        if '"skill"' in prompt:
            return '{"skill": "none", "confidence": 0.3, "why": "prueba"}'
        if '"title"' in prompt:
            return ('{"title": "Prueba de captura", "tags": ["test"], '
                    '"body": "Nota de prueba enlazada a [[Agenda]].", "links": ["Agenda"]}')
        if '"add"' in prompt:
            return '{"add": false}'
        return "## Lo que importa hoy\n- [[Agenda]] revisada\n\n## Se movio\n- nada"


async def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="friday_test_"))
    print(f"\n  F.R.I.D.A.Y OS — prueba de humo\n  vault temporal: {tmp}\n")

    cfg = load_config(ROOT / "config" / "friday.toml")
    vault = Vault(tmp)

    # Regresion: el runner de Windows de CI daba `%TEMP%` en forma corta
    # (8.3, "RUNNER~1") mientras `Path.resolve()` la expandia a la larga
    # ("runneradmin"). `Vault.root` sin resolver comparado contra una nota
    # ya resuelta ("p.relative_to(self.root)") reventaba escribiendo una
    # nota RECIEN CREADA, dentro del propio vault. Se reproduce con el
    # nombre corto real de Windows, no con un truco de string: pathlib ya
    # normaliza "." y compara mayus/minus sin distinguir en Windows, asi
    # que ninguno de los dos reproduce esto — hace falta el alias 8.3 de
    # verdad.
    if sys.platform == "win32":
        import ctypes
        buf = ctypes.create_unicode_buffer(260)
        ok = ctypes.windll.kernel32.GetShortPathNameW(str(tmp), buf, 260)
        corto = Path(buf.value) if ok else tmp
        if str(corto) != str(tmp):     # el volumen tiene nombres 8.3 activos
            vault_corto = Vault(corto)
            nota_regresion = vault_corto.write("wiki/Nota.md", "cuerpo")
            check("una raiz en su forma corta (8.3) no revienta al escribir",
                  nota_regresion.rel == "wiki/Nota.md", nota_regresion.rel)

    graph = Graph(vault, ttl_s=0)
    engine = FakeEngine(cfg)
    skills = build_skills(cfg)
    router = Router(cfg, vault, graph, engine, skills)

    # ── frontmatter ──────────────────────────────────────────
    meta, body = parse_frontmatter("---\ntitle: X\ntags: [a, b]\nmetric: 42\n---\nCuerpo\n")
    check("frontmatter parse", meta.get("tags") == ["a", "b"] and meta.get("metric") == 42,
          f"{meta}")
    check("frontmatter render", "tags: [a, b]" in render_frontmatter(meta))

    # ── escritura y enlaces ──────────────────────────────────
    a = vault.write("wiki/Proyecto Alfa.md",
                    "Depende de [[Proyecto Beta]] y de [[Agenda]].\n\n"
                    "- [ ] Terminar el diseno\n- [x] Kickoff\n\nvelocidad:: 12 pts\n",
                    meta={"tags": ["proyecto"], "metric": 12})
    vault.write("wiki/Proyecto Beta.md", "Bloquea a [[Proyecto Alfa]].\n\n- [ ] Definir alcance\n")
    vault.write("wiki/Agenda.md",
                "## Eventos\n- 2099-01-01 10:00 | Revision anual | #trabajo\n")
    check("write + parse links", a.links == ["Agenda", "Proyecto Beta"], str(a.links))
    check("tags detectados", "proyecto" in a.title.lower() or "proyecto" in a.tags, str(a.tags))

    # ── append no destruye ───────────────────────────────────
    before = vault.read("wiki/Proyecto Alfa.md").body
    after = vault.write("wiki/Proyecto Alfa.md", "Linea nueva.", mode="append").body
    check("append preserva", before.strip() in after and "Linea nueva" in after)

    # ── seccion y log diario ─────────────────────────────────
    vault.log("evento de prueba", kind="test")
    daily = vault.read(vault.daily_path())
    check("log diario", "evento de prueba" in daily.body)
    vault.append_section(vault.daily_path(), "Log", ["- segunda linea"])
    check("append_section reusa heading",
          vault.read(vault.daily_path()).body.count("## Log") == 1)

    # ── grafo ────────────────────────────────────────────────
    graph.build(force=True)
    check("backlinks", "Proyecto Beta" in graph.backlinks("Proyecto Alfa"),
          str(graph.backlinks("Proyecto Alfa")))
    check("vecinos", "Agenda" in graph.neighbors("Proyecto Alfa", 1))
    gj = graph.to_json()
    check("grafo json", gj["stats"]["total"] >= 3 and len(gj["edges"]) >= 2,
          f"{gj['stats']['total']} nodos, {len(gj['edges'])} aristas")

    # ── busqueda ─────────────────────────────────────────────
    hits = vault.search("proyecto alcance")
    check("busqueda", any("Beta" in h.title for h in hits),
          ", ".join(h.title for h in hits[:3]))

    # Las palabras vacias no pueden traer notas. Con «que» y «los» puntuando,
    # cualquier pregunta coincidia con cualquier nota — y esas notas se
    # inyectan como contexto en la conversacion libre. Un modelo grande
    # ignora el ruido; uno pequeño responde sobre la nota equivocada.
    check("las palabras vacias no traen notas", vault.search("que es esto") == [],
          f"{len(vault.search('que es esto'))} notas por «que es esto»")
    check("y no rompen una busqueda con contenido",
          any("Beta" in h.title for h in vault.search("que es el proyecto alcance")))

    # ── seguridad de rutas ───────────────────────────────────
    try:
        vault.write("../../fuera.md", "no")
        check("bloquea escape del vault", False, "dejo escribir fuera")
    except ValueError:
        check("bloquea escape del vault", True)

    # ── enrutado rapido ──────────────────────────────────────
    # Los casos interesantes son los que se pisan entre si. El puntaje mide
    # la ESPECIFICIDAD del disparador, no su cobertura, y estas parejas son
    # las que lo comprueban: si alguien cambia esa regla, aqui se rompe.
    cases = {
        "dame las metricas": "metricas",
        "resumen del dia": "inbox",
        "arma el plan de hoy": "plan",
        "recuerda que el servidor se cae los martes": "vault",
        "que tengo en la agenda": "agenda",

        # noticias vs inbox: los dos reconocen «ponme al dia»
        "ponme al dia con las noticias": "noticias",
        "ponme al dia": "inbox",
        "dame los titulares": "noticias",

        # motor vs sistema: los dos reconocen «cambia a»
        "cambia a sonnet": "motor",
        "cambia a chrome": "sistema",
        "que modelos tienes": "motor",

        # web vs sistema vs vault: leer, abrir el navegador, o buscar en notas
        "investiga que es una TPU": "web",
        "busca gatos en google": "sistema",
        "resume esta pagina https://ejemplo.com": "web",
        "busca el archivo presupuesto": "archivos",

        "que tengo abierto": "sistema",

        # memoria vs metricas: la skill se llama como una palabra que sale en
        # las dos preguntas, asi que el puntaje generico no puede decidir
        "consolida la memoria": "memoria",
        "limpia las notas viejas": "memoria",
        "cuanta memoria ram me queda": "metricas",

        # taller vs el resto: encargarle trabajo a un agente en un repo
        "metete en mi-proyecto y revisa por que fallan los tests": "taller",
    }
    for text, expected in cases.items():
        r = await router.decide(text)
        check(f"ruta «{text[:34]}»", r.skill == expected,
              f"-> {r.skill} ({r.how}, {r.confidence})")

    # ── configuracion publica vs local ───────────────────────
    # Este repo es publico y su toml es a la vez ejemplo y config viva. La
    # separacion no es comodidad: es lo que evita que las rutas de tus
    # proyectos acaben en un commit.
    import tomllib

    from core.config import Config, _merge

    with open(ROOT / "config" / "friday.toml", "rb") as fh:
        publico = tomllib.load(fh)
    check("el toml publico no declara ninguna raiz de agente",
          publico.get("policy", {}).get("agent_roots") == [],
          f"{publico.get('policy', {}).get('agent_roots')}")

    fusion = _merge({"policy": {"agent_roots": [], "allow_agent": True},
                     "system": {"search_engine": "default"}},
                    {"policy": {"agent_roots": ["~/proyectos"]}})
    check("lo local pisa solo lo que menciona",
          fusion["policy"]["agent_roots"] == ["~/proyectos"]
          and fusion["policy"]["allow_agent"] is True
          and fusion["system"]["search_engine"] == "default",
          str(fusion))
    check("una lista se reemplaza entera, no se concatena",
          _merge({"a": [1, 2]}, {"a": [3]})["a"] == [3],
          "si declaras tus raices, quieres ESAS")
    check("el archivo local se busca junto al publico",
          Config(ROOT / "config" / "friday.toml").local_path.name
          == "friday.local.toml")

    # ── el hilo de conversacion ──────────────────────────────
    # Lo que se prueba aqui es que una frase que NO se sostiene sola acabe
    # en conversacion y no en una skill. «y eso cuanto cuesta» dispara el
    # `\bcuanto\b` de `metricas`: sin el paso de seguimiento, preguntar por
    # un precio te devuelve el uso de CPU.
    import time

    from core.chat import Conversation, Turn

    hilo = Conversation(max_turns=4, max_chars=4000, ttl_s=900)
    hilo.add("user", "cuanto cuesta una TPU")
    hilo.add("assistant", "Depende del modelo.")
    check("el hilo guarda los turnos", len(hilo) == 2)
    check("la transcripcion usa etiquetas habladas, no roles de API",
          "Jefe: cuanto cuesta una TPU" in hilo.transcript(),
          hilo.transcript()[:40])
    for i in range(6):
        hilo.add("user", f"linea {i}")
    check("el hilo recorta por numero de turnos", len(hilo) == 4, f"{len(hilo)} turnos")

    gordo = Conversation(max_turns=10, max_chars=50)
    gordo.add("user", "x" * 40)
    gordo.add("assistant", "y" * 40)
    check("el tope de caracteres tira lo mas viejo",
          len(gordo) == 1 and gordo.turns[0].text.startswith("y"),
          f"{len(gordo)} turnos")

    frio = Conversation(ttl_s=600)
    frio.turns.append(Turn("user", "algo dicho hace una hora", time.time() - 3600))
    check("un hilo frio no aporta contexto", not frio.active and frio.transcript() == "",
          "un «y eso?» media hora despues no es una continuacion")

    router.chat.clear()
    router.chat.add("user", "cuanto cuesta una TPU")
    router.chat.add("assistant", "Depende del modelo.")

    r = await router.decide("y eso cuanto cuesta")
    check("seguimiento: la anafora le gana al enrutado rapido",
          r.skill == "none" and r.how == "chat", f"-> {r.skill} ({r.how})")
    r = await router.decide("explicame mas")
    check("seguimiento: «explicame mas» continua el hilo", r.how == "chat", r.how)
    r = await router.decide("y abre spotify")
    check("una orden NO es seguimiento aunque empiece por «y»",
          r.how != "chat", f"-> {r.skill} ({r.how})")
    r = await router.decide("abre eso")
    check("«abre eso» lleva anafora pero es una orden",
          r.skill == "sistema", f"-> {r.skill} ({r.how})")

    router.chat.clear()
    r = await router.decide("y eso cuanto cuesta")
    check("sin hilo vivo no hay seguimiento", r.how != "chat", f"-> {r.skill} ({r.how})")

    # ── charla sin gastar motor ──────────────────────────────
    # Un turno de conversacion gastaba dos llamadas: una para preguntar a
    # quien enrutarlo y otra para responder. Con `claude_code` eso es la
    # mitad del tiempo de respuesta, gastada en confirmar lo evidente.
    r = await router.decide("que opinas de los lunes")
    check("la charla evidente no pasa por el motor",
          r.how == "chat-fast" and r.skill == "none", f"-> {r.skill} ({r.how})")
    check("una orden sin skill reconocida NO es charla",
          not router._is_smalltalk("cierra la lampara del salon", {"x": 0.0}),
          "el verbo de accion manda")
    check("una frase larga tampoco",
          not router._is_smalltalk(" ".join(["palabra"] * 20), {"x": 0.0}))
    check("y si alguna skill puntuo, arbitra el motor",
          not router._is_smalltalk("que opinas", {"x": 0.3}),
          "esa duda vale los cuatro segundos")

    # la conversacion libre responde en prosa: pedir JSON aqui encoge las
    # respuestas y, con un 8B local, cada tanto rompe el formato
    res = await router._freeform("y eso que significa")
    check("conversacion libre responde en prosa",
          res.ok and res.speak and not res.speak.strip().startswith("{"),
          res.speak[:50])

    largo = " ".join(f"Frase numero {i}." for i in range(80))
    dicho = router._for_voice(largo)
    check("la voz corta por frases enteras, no a media palabra",
          dicho.endswith(".") and len(dicho) <= 700, f"{len(dicho)} caracteres")

    router.chat.clear()
    await router.dispatch("dame las metricas")
    check("el hilo recoge tambien lo que atendio una skill",
          len(router.chat) == 2, f"{len(router.chat)} turnos")

    route = await router.decide("cambiemos de tema")
    check("«cambiemos de tema» es comando directo", route.skill == "_reset_chat",
          route.how)
    await router.dispatch("cambiemos de tema", route)
    check("reiniciar el hilo lo vacia", len(router.chat) == 0)

    # ── skills de verdad ─────────────────────────────────────
    ctx = SkillContext(cfg, vault, graph, engine)

    ctx.text = "dame las metricas"
    res = await skills["metricas"].run(ctx)
    check("skill metricas", res.ok and res.data["vault"]["notes"] >= 3,
          f"{res.data['vault']['notes']} notas, cpu={res.data['vitals'].get('cpu')}")
    check("metricas jala numeros del vault",
          any("velocidad" in k.lower() for k in res.data["metrics"]),
          str(list(res.data["metrics"])[:4]))

    ctx.text = "que sigue"
    res = await skills["agenda"].run(ctx)
    check("skill agenda", res.ok and res.data["total"] >= 1,
          f"{res.data['total']} eventos")

    ctx.text = "resumen"
    res = await skills["inbox"].run(ctx)
    check("skill inbox escribe", res.ok and res.writes and vault.exists(res.writes[0]),
          str(res.writes))

    ctx.text = "plan de hoy"
    res = await skills["plan"].run(ctx)
    check("skill plan escribe top 3", res.ok and res.writes and vault.exists(res.writes[0]),
          str(res.writes))
    check("plan espeja en diaria", "Top 3" in vault.read(vault.daily_path()).body)

    ctx.text = "recuerda que el deploy es los viernes"
    res = await skills["vault"].run(ctx)
    check("skill vault escribe nota", res.ok and res.writes and vault.exists(res.writes[0]),
          str(res.writes))
    check("nota nueva queda enlazada", res.data.get("links"), str(res.data.get("links")))

    ctx.text = "que sabes de Proyecto Alfa"
    res = await skills["vault"].run(ctx)
    check("skill vault lee", res.ok and res.data["hits"] > 0, f"{res.data['hits']} hits")

    # ── dispatch completo ────────────────────────────────────
    route, res = await router.dispatch("dame las metricas")
    check("dispatch end-to-end", res.ok and res.data.get("_ms") is not None,
          f"{route.skill} en {res.data.get('_ms')}ms")

    # ── reparacion del grafo ─────────────────────────────────
    vault.write("wiki/Suelta.md", "Apunta a [[Nota Inexistente]].")
    graph.build(force=True)
    created = graph.heal()
    check("heal crea stubs", "Nota Inexistente" in created, str(created))
    check("heal cierra el enlace", not graph.build(force=True).broken(),
          f"{len(graph.broken())} rotos")

    # ── consolidacion de la memoria ──────────────────────────
    # Lo que se prueba: que lo rutinario se queda fuera, que lo dicho para
    # ser recordado sobrevive, que nada se retira antes de estar escrito y
    # que solo se tocan las diarias de raw/.
    from core.policy import Policy
    from memory.consolidate import Consolidator

    def diaria(fecha: str, lineas: list[str]) -> None:
        vault.write(f"raw/{fecha}.md",
                    f"# {fecha}\n\n## Log\n" + "\n".join(lineas),
                    meta={"type": "daily", "date": fecha, "tags": ["daily"]})

    diaria("2020-03-01", [
        "- `09:02` **voz** — abre Spotify",
        "- `09:40` **voz** — sube el volumen",
        "- `10:15` **vault** — «el deploy es los viernes» → [[Deploy]]",
        "- `11:00` **pantalla** — Lectura de pantalla — Visual Studio Code",
    ])
    diaria("2020-03-02", [
        "- `08:30` **voz** — que hora es",
        "- `12:00` **agenda** — Agendado: revision con Ana el 2020-03-09",
        "- `18:20` **voz** — el servidor de staging se cae los martes",
    ])
    antes = vault.stats()

    con = Consolidator(vault, keep_days=7, min_notes=2,
                       target="raw/Memoria consolidada.md", trash_days=30)
    p = con.plan()
    check("plan agarra las diarias viejas", len(p.sources) == 2, f"{len(p.sources)}")
    check("plan omite lo rutinario", p.rutina == 4, f"{p.rutina} rutinas")
    frases = " | ".join(a.text for a in p.esencia)
    check("«recuerda que» y la agenda sobreviven",
          "deploy" in frases and "Ana" in frases, frases[:90])
    check("la orden cumplida no sobrevive",
          "Spotify" not in frases and "volumen" not in frases, frases[:90])

    # El guardia primero: por defecto el vault del toml no es este temporal,
    # asi que retirar aqui tiene que estar denegado.
    policy = Policy(cfg)
    check("no se retira nada fuera del vault declarado",
          policy.can_prune(p.sources).verdict.value == "deny",
          policy.can_prune(p.sources).reason)
    policy.vault_root = Path(tmp).resolve()
    check("dentro del vault si", policy.can_prune(p.sources).allowed)
    check("y nunca algo que no sea una nota",
          policy.can_prune([Path(tmp) / "raw" / "cosa.exe"]).verdict.value == "deny")

    rep = await con.run(engine, policy)
    check("consolidacion escribe una sola nota",
          rep.ok and vault.exists("raw/Memoria consolidada.md"), rep.reason)
    consolidada = vault.read("raw/Memoria consolidada.md").body
    check("el consolidado lleva el rango", "2020-03-01 → 2020-03-02" in consolidada,
          consolidada[:60])
    check("el motor comprimio", rep.by_engine and "deploy" in consolidada.lower(),
          f"by_engine={rep.by_engine}")
    check("los originales se retiran", rep.retired == 2 and rep.shrunk > 0,
          f"{rep.retired} notas, {rep.shrunk} bytes")
    check("y salen de la vista del vault",
          not vault.exists("raw/2020-03-01.md")
          and all("2020-03-01" not in n.rel for n in vault.all_notes()))
    check("pero siguen en la papelera",
          any(p.name.startswith("raw__2020-03-01") for p in vault.trash_dir.glob("*.md")),
          str([p.name for p in vault.trash_dir.glob('*.md')]))
    check("el vault vivo pesa menos", vault.stats()["bytes"] < antes["bytes"],
          f"{antes['bytes']} → {vault.stats()['bytes']} bytes")
    check("wiki y outputs no se tocan",
          vault.exists("wiki/Proyecto Alfa.md") and vault.stats()["wiki"] >= 3)

    # ── una diaria que cambia mientras el motor resume no se retira ──
    # `plan` corre fuera del candado del turno y `commit` dentro: entre los
    # dos hay una llamada al motor que puede tardar minutos, y ahi el usuario
    # puede escribir. Retirar lo que cambio despues de leerlo seria tirar
    # justo lo que el resumen no vio.
    for dia in ("2019-11-01", "2019-11-02", "2019-11-03"):
        vault.write(vault.raw / f"{dia}.md", f"- nota: apunte de {dia}",
                    meta={"type": "daily"})
    con2 = Consolidator(vault, keep_days=7, min_notes=2,
                        target="raw/Otro consolidado.md", trash_days=30)
    p6 = con2.plan()
    check("hay plan para el segundo consolidado", len(p6.sources) >= 3,
          f"{len(p6.sources)} diarias")
    check("el plan anoto la huella de cada fuente",
          len(p6.huellas) == len(p6.sources))

    tocada = p6.sources[0]
    time.sleep(0.01)
    tocada.write_text(tocada.read_text(encoding="utf-8") +
                      "\n- nota: esto lo escribi mientras resumias\n",
                      encoding="utf-8")
    vault._cache.pop(tocada, None)
    rep6 = con2.commit(p6, await con2.summarize(engine, p6), policy)
    check("la nota que cambio NO se retira", tocada.exists(),
          "sigue en su sitio")
    check("y lo escrito despues sigue ahi",
          "mientras resumias" in tocada.read_text(encoding="utf-8"))
    check("las que no cambiaron si se retiran",
          rep6.retired == len(p6.sources) - 1,
          f"retiradas {rep6.retired} de {len(p6.sources)}")
    check("y se dice por que se quedo una",
          "cambiaron" in rep6.reason, rep6.reason)
    # Esa diaria se queda a proposito, asi que se limpia aqui: si no, las
    # pruebas de mas abajo la encuentran vieja y la cuentan como suya.
    tocada.unlink()
    vault._cache.pop(tocada, None)

    # Sin permiso no se retira, pero el resumen se escribe igual: perder el
    # resumen porque no se puede borrar seria cambiar una cosa por otra.
    diaria("2020-04-01", ["- `09:00` **voz** — el proveedor cambia en mayo"])
    diaria("2020-04-02", ["- `09:00` **voz** — la migracion la lleva Beto"])
    policy.allow_memory_prune = False
    rep2 = await con.run(engine, policy)
    check("sin permiso el resumen se escribe igual", rep2.ok and rep2.kept > 0,
          rep2.reason)
    check("pero no se retira nada",
          rep2.retired == 0 and vault.exists("raw/2020-04-01.md"), rep2.reason)

    rep3 = await con.run(engine, None)
    check("sin guardia se resume pero no se retira",
          rep3.notes == 2 and rep3.retired == 0 and vault.exists("raw/2020-04-01.md"),
          rep3.reason)

    policy.allow_memory_prune = True
    await con.run(engine, policy)
    rep4 = await con.run(engine, policy)
    check("sin diarias viejas la pasada no hace nada",
          rep4.notes == 0 and not rep4.retired, rep4.reason)

    # ── consulta y comando separados ─────────────────────────
    # `plan` y `summarize` no tocan disco: es lo que permite que el ciclo
    # autonomo los corra FUERA del candado del turno. Si alguien vuelve a
    # meter escritura en la fase lenta, FRIDAY deja de responder mientras
    # el motor resume — y eso ya paso una vez.
    for dia in ("2018-01-01", "2018-01-02", "2018-01-03"):
        diaria(dia, [f"- `09:00` **voz** — el contrato de {dia} vence en junio"])
    p5 = con.plan()
    huella = vault.stats()
    res5 = await con.summarize(engine, p5)
    check("summarize es una consulta: no escribe nada",
          vault.stats() == huella and res5.lineas, str(res5.lineas)[:60])
    rep5 = con.commit(p5, res5, policy)
    check("commit es el unico que muta", rep5.retired == 3 and rep5.ok, rep5.reason)

    # ── cache de notas del vault ─────────────────────────────
    parseos = {"n": 0}
    original = vault._parse

    def contando(p, st):
        parseos["n"] += 1
        return original(p, st)

    vault._parse = contando
    vault._cache.clear()             # el vault ya lleva rato caliente
    vault.all_notes()
    primera, parseos["n"] = parseos["n"], 0
    vault.all_notes()
    check("la segunda pasada del vault no reparsea nada",
          primera > 0 and parseos["n"] == 0,
          f"{primera} parseos la primera, {parseos['n']} la segunda")
    vault.write("wiki/Proyecto Alfa.md", "linea que invalida", mode="append")
    check("una escritura invalida su entrada del cache",
          "linea que invalida" in vault.read("wiki/Proyecto Alfa.md").body)
    vault._parse = original

    # ── la skill, con los ajustes del toml de verdad ─────────
    mem = skills["memoria"]
    ctx.policy = policy
    ctx.text = "cuanto ocupa la memoria"
    res = await mem.run(ctx)
    check("preguntar el tamaño no escribe nada",
          res.ok and not res.writes, str(res.writes))

    for dia in ("2019-05-01", "2019-05-02", "2019-05-03"):
        diaria(dia, [f"- `09:00` **voz** — el contrato de {dia} vence en junio",
                     "- `09:05` **voz** — abre el navegador"])
    ctx.text = "consolida la memoria"
    res = await mem.run(ctx)
    check("la skill consolida y lo dice",
          res.ok and res.writes and res.data["notes"] == 3, res.speak)
    check("y deja de haber tres diarias",
          not vault.exists("raw/2019-05-01.md"), str(res.data))

    # ── limpieza de TTS (sin audio) ──────────────────────────
    from voice.tts import LocalTTS
    spoken = LocalTTS.clean("## Titulo\n- **Punto** con [[Enlace|alias]] y `codigo`.")
    check("tts limpia markdown",
          "*" not in spoken and "[[" not in spoken and "alias" in spoken, spoken)

    # ── candado de privacidad ────────────────────────────────
    import socket
    import threading

    from core import privacy

    privacy.install()

    def try_connect(host: str) -> str:
        s = socket.socket()
        s.settimeout(0.4)
        try:
            s.connect((host, 9))
            return "conecto"
        except privacy.AudioLeak:
            return "BLOQUEADO"
        except OSError:
            return "rechazado por red"
        finally:
            s.close()

    with privacy.sealed():
        check("sello bloquea salida a internet", try_connect("1.1.1.1") == "BLOQUEADO",
              try_connect("1.1.1.1"))
        check("sello deja pasar loopback", try_connect("127.0.0.1") != "BLOQUEADO",
              try_connect("127.0.0.1"))
    check("sin sello no bloquea", try_connect("1.1.1.1") != "BLOQUEADO")

    # el sello es por hilo: probamos que aplica DENTRO del worker
    box: dict[str, str] = {}

    def worker() -> None:
        with privacy.sealed():
            box["sealed"] = try_connect("1.1.1.1")
        box["free"] = try_connect("1.1.1.1")

    t = threading.Thread(target=worker)
    t.start(); t.join()
    check("sello funciona en otro hilo", box.get("sealed") == "BLOQUEADO", str(box))
    check("sello no se filtra fuera del bloque", box.get("free") != "BLOQUEADO", str(box))
    privacy.uninstall()

    # ══════════════════ EL HABLA SE NORMALIZA ANTES DE DECIDIR ═════
    print()
    print("  -- lo que llega del STT no es lo que escribiria nadie --")
    from core.lang import es_narrativo, es_pregunta, limpia, numero, slug_words

    check("un numero dictado con letras es un numero",
          numero("volumen al veinte") == 20 and numero("treinta y cinco") == 35,
          "int('veinte') lanza, y se caia al valor por defecto")
    check("los digitos ganan a las frases hechas",
          numero("ponlo a 5") == 5)
    check("una cantidad vaga tambien es una cantidad",
          numero("bajale un poco") == 10 and numero("ponlo al maximo") == 100,
          "«un poco» daba 1 por el «un»")
    check("sin numero no se inventa uno", numero("sube el volumen") is None)
    check("las tres formas del mismo nombre coinciden",
          slug_words("mi-proyecto") == slug_words("Mi Proyecto") == "mi proyecto")
    check("el eco no repite las muletillas",
          limpia("oye, friday, a ver, sube el volumen") == "sube el volumen")

    check("preguntar por la maquina y quejarse de ella no es lo mismo",
          es_pregunta("cuanta RAM me queda")
          and es_narrativo("se me cayo el servidor de produccion"),
          "misma familia de palabras, intenciones opuestas")

    # ══════════════════ EL RELOJ DECIDE SIN EFECTOS ════════════════
    print()
    print("  -- el reloj: puro, y no repite --")
    from datetime import datetime as _dt

    from core.scheduler import Job, Scheduler, parse_dias, parse_intervalo

    trabajos = [Job(name="briefing", do="dame el briefing", at=(8, 30),
                    days=parse_dias("laborables"))]
    reloj = Scheduler(trabajos, lead_min=15, gracia_min=10)

    lunes = _dt(2026, 8, 24, 8, 31)
    d1 = reloj.due(lunes)
    check("un trabajo vencido dentro de la gracia dispara", len(d1) == 1,
          d1[0].clave if d1 else "nada")
    check("y no vuelve a disparar con la marca puesta",
          reloj.due(lunes, ya_disparado={d1[0].clave}) == [],
          "la marca sobrevive al reinicio: se escribe en la diaria")
    check("un sabado no es laborable", reloj.due(_dt(2026, 8, 22, 8, 31)) == [])
    check("fuera de la ventana de gracia tampoco",
          reloj.due(_dt(2026, 8, 24, 9, 30)) == [],
          "enterarse de la reunion cuando ya termino no es avisar")

    evento = {"when": "2026-08-24T09:00", "title": "Revision de sprint",
              "time": "09:00", "ts": _dt(2026, 8, 24, 9, 0).timestamp(),
              "done": False}
    todo_el_dia = {"when": "2026-08-24T00:00", "title": "Entrega", "time": "",
                   "ts": _dt(2026, 8, 24, 0, 0).timestamp(), "done": False}
    avisos = [x for x in reloj.due(_dt(2026, 8, 24, 8, 50),
                                   eventos=[evento, todo_el_dia])
              if x.kind == "recordatorio"]
    check("un evento con hora avisa antes de la hora", len(avisos) == 1,
          avisos[0].texto if avisos else "nada")
    check("y dice cuanto falta, no la hora",
          bool(avisos) and "10 minutos" in avisos[0].texto, avisos[0].texto)
    check("un evento de todo el dia no despierta a nadie a las 00:00",
          all("Entrega" not in a.titulo for a in avisos),
          "de esos habla el briefing, que es donde tienen sentido")
    check("un recordatorio sale tambien fuera del equipo",
          bool(avisos) and avisos[0].notify)
    check("decidir no ejecuta nada",
          all(hasattr(x, "texto") for x in avisos),
          "due() devuelve intenciones; los efectos son de friday.py")
    check("un intervalo mal escrito no revienta el arranque",
          parse_intervalo("cada tanto") == 0.0)

    # El primer tick tras arrancar no dispara los intervalos.
    porintervalo = Scheduler([Job(name="pulso", do="metricas", every_s=1800)])
    check("encender FRIDAY no lanza de golpe lo declarado «cada 6h»",
          porintervalo.due(lunes) == [])

    # ══════════════════ VOCABULARIO COMPARTIDO, INTENCIONES DISTINTAS ══
    print()
    print("  -- una palabra del dominio no es una peticion del dominio --")
    met = skills["metricas"]
    ag = skills["agenda"]
    check("un desahogo con vocabulario tecnico no pide metricas",
          met.matches("se me cayo el servidor de produccion y tengo "
                      "una demo en veinte minutos") == 0.0,
          "el caso del ROADMAP: contestaba con el uso de CPU")
    check("pero preguntar por la maquina si",
          met.matches("cuanta RAM me queda") > 0.6)
    check("y un disparador propio no depende de la forma",
          met.matches("dame las metricas") > 0.9)
    check("«toda la mañana» es un momento, no una fecha",
          ag.matches("llevo toda la mañana dandole vueltas") == 0.0,
          "mañana tiene dos significados y solo uno es del calendario")
    check("«que tengo mañana» sigue siendo la agenda",
          ag.matches("que tengo mañana") > 0.5)

    shutil.rmtree(tmp, ignore_errors=True)

    bad = [n for n, ok, _ in results if not ok]
    print(f"\n  {len(results) - len(bad)}/{len(results)} pruebas pasaron")
    if bad:
        print(f"  fallaron: {', '.join(bad)}\n")
        return 1
    print("  todo verde.\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
