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

    # ── seguridad de rutas ───────────────────────────────────
    try:
        vault.write("../../fuera.md", "no")
        check("bloquea escape del vault", False, "dejo escribir fuera")
    except ValueError:
        check("bloquea escape del vault", True)

    # ── enrutado rapido ──────────────────────────────────────
    cases = {
        "dame las metricas": "metricas",
        "resumen del dia": "inbox",
        "arma el plan de hoy": "plan",
        "recuerda que el servidor se cae los martes": "vault",
        "que tengo en la agenda": "agenda",
    }
    for text, expected in cases.items():
        r = await router.decide(text)
        check(f"ruta «{text[:30]}»", r.skill == expected,
              f"-> {r.skill} ({r.how}, {r.confidence})")

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
