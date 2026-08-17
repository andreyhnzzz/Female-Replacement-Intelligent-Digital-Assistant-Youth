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
