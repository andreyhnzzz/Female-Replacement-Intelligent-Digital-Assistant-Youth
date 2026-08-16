"""Pruebas de la capa de sistema: politica, puertos, archivos y confirmacion.

Todo corre sobre un directorio temporal y una politica de juguete. No toca
tus carpetas reales, no lanza aplicaciones y no gasta llamadas al motor.

    python scripts/system_test.py
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
from core.policy import Policy, Verdict
from core.router import Router
from memory.graph import Graph
from memory.vault import Vault
from skills import build_skills
from skills.base import SkillContext
from system.files import LocalFileIndex, LocalFileOrganizer, family_of
from system.ports import FileInfo, OpKind, SystemAccess

PASS, FAIL = "\033[92m ok \033[0m", "\033[91mFALLA\033[0m"
results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, note: str = "") -> None:
    results.append((name, bool(cond), note))
    print(f"  [{PASS if cond else FAIL}] {name}{'  — ' + note if note else ''}")


class FakeCfg:
    """Config minima con una politica acotada al sandbox."""

    def __init__(self, sandbox: Path, **overrides):
        self.root = ROOT
        self._d = {
            "policy.enabled": True,
            "policy.allow_launch": True,
            "policy.allow_file_write": True,
            "policy.allow_shell": False,
            "policy.allow_web": True,
            "policy.allow_web_fetch": True,
            "policy.confirm_over_files": 3,
            "policy.write_roots": [str(sandbox)],
            "policy.read_roots": [str(sandbox)],
            "policy.blocked_apps": ["regedit*", "cmd.exe"],
            "policy.blocked_hosts": [],
        }
        # `FakeCfg(sandbox, allow_web_fetch=False)` para probar un solo
        # interruptor sin escribir otra clase de config entera.
        self._d.update({f"policy.{k}": v for k, v in overrides.items()})

    def get(self, key: str, default=None):
        return self._d.get(key, default)


class FakeEngine(Engine):
    name = "fake"

    def __init__(self, cfg):
        super().__init__(cfg)

    async def complete(self, prompt: str, system: str = "", **kw) -> str:
        return '{"skill": "none", "confidence": 0.2}'


def seed(sandbox: Path) -> None:
    """Un desorden realista para organizar."""
    for name in ("foto1.jpg", "foto2.png", "informe.pdf", "notas.txt",
                 "datos.csv", "musica.mp3", "paquete.zip", "script.py",
                 "video.mp4", "raro.xyz"):
        (sandbox / name).write_text("x" * 32, encoding="utf-8")


async def main() -> int:
    sandbox = Path(tempfile.mkdtemp(prefix="friday_sys_"))
    print(f"\n  F.R.I.D.A.Y — pruebas de sistema\n  sandbox: {sandbox}\n")

    cfg = FakeCfg(sandbox)
    policy = Policy(cfg)
    seed(sandbox)

    # ══════════════════ POLITICA ══════════════════
    print("  ── politica ──")
    check("escribe dentro del sandbox",
          policy.can_write(sandbox / "algo.txt").allowed)
    check("bloquea fuera del sandbox",
          not policy.can_write(Path.home() / "peligro.txt").allowed,
          policy.can_write(Path.home() / "peligro.txt").reason)
    check("bloquea C:/Windows",
          not policy.can_write(Path("C:/Windows/system32/x.txt")).allowed)
    check("bloquea extension critica",
          not policy.can_write(sandbox / "driver.sys").allowed,
          policy.can_write(sandbox / "driver.sys").reason)
    check("bloquea app en lista negra",
          not policy.can_launch("regedit.exe").allowed)
    check("permite app normal", policy.can_launch("notepad.exe").allowed)
    check("shell apagado por defecto",
          policy.can_shell("dir").verdict is Verdict.DENY)

    # ── salir a la red es un permiso propio, no el de abrir el navegador ──
    check("descarga una web publica",
          policy.can_fetch("https://feeds.bbci.co.uk/mundo/rss.xml").allowed)
    check("bloquea la red local",
          not policy.can_fetch("http://192.168.1.1/admin").allowed,
          policy.can_fetch("http://192.168.1.1/admin").reason)
    check("bloquea loopback",
          not policy.can_fetch("http://127.0.0.1:8080/x").allowed)
    check("bloquea esquemas que no son http",
          not policy.can_fetch("file:///C:/Windows/win.ini").allowed,
          policy.can_fetch("file:///C:/Windows/win.ini").reason)
    check("respeta la lista negra de hosts",
          not Policy(FakeCfg(sandbox, blocked_hosts=["*.malo.com"]))
          .can_fetch("https://x.malo.com/a").allowed)
    check("allow_web_fetch=false lo apaga todo",
          not Policy(FakeCfg(sandbox, allow_web_fetch=False))
          .can_fetch("https://ejemplo.com").allowed)

    # ══════════════════ INDICE (solo lectura) ══════════════════
    print("\n  ── indice de archivos ──")
    index = LocalFileIndex(policy)
    hits = index.search("foto", roots=[sandbox])
    check("busca por nombre", len(hits) == 2, f"{[h.name for h in hits]}")
    check("indice no puede escribir",
          not any(hasattr(index, m) for m in ("apply", "move", "delete", "rename")),
          "sin metodos de escritura")
    fuera = index.search("foto", roots=[Path.home()])
    check("respeta las raices de lectura", fuera == [], f"{len(fuera)} resultados")

    check("familias por extension",
          family_of(".jpg") == "Imagenes" and family_of(".xyz") == "Otros")

    # ══════════════════ ORGANIZADOR ══════════════════
    print("\n  ── organizador ──")
    org = LocalFileOrganizer(policy, index)
    ops = org.plan_organize(sandbox)
    check("planea sin tocar nada",
          len(ops) == 10 and len(list(sandbox.glob("*.jpg"))) == 1,
          f"{len(ops)} operaciones planeadas")

    dry = org.apply(ops, dry_run=True)
    check("dry-run no mueve",
          len(dry.done) == 10 and (sandbox / "foto1.jpg").exists())

    gate = policy.can_apply_batch(ops)
    check("lote grande pide confirmacion",
          gate.verdict is Verdict.CONFIRM, gate.reason)

    res = org.apply(ops)
    check("aplica de verdad", res.ok and len(res.done) == 10, res.summary())
    check("agrupa por familia",
          (sandbox / "Imagenes" / "foto1.jpg").exists()
          and (sandbox / "Codigo" / "script.py").exists())
    check("origen queda vacio", not (sandbox / "foto1.jpg").exists())

    # no sobrescribir
    (sandbox / "foto1.jpg").write_text("otro", encoding="utf-8")
    ops2 = org.plan_organize(sandbox)
    org.apply(ops2)
    copias = list((sandbox / "Imagenes").glob("foto1*.jpg"))
    check("nunca sobrescribe", len(copias) == 2, f"{[c.name for c in copias]}")

    # renombrado
    imgs = [FileInfo(p, p.name, p.stat().st_size, p.stat().st_mtime)
            for p in (sandbox / "Imagenes").iterdir() if p.is_file()]
    rops = org.plan_rename(imgs, "IMG_{n}")
    check("planea renombrado", len(rops) == len(imgs) and rops[0].kind is OpKind.RENAME,
          rops[0].describe() if rops else "")
    org.apply(rops)
    check("renombra", any(p.name.startswith("IMG_")
                          for p in (sandbox / "Imagenes").iterdir()))

    # escape del sandbox
    from system.ports import FileOp
    escape = [FileOp(OpKind.MOVE, sandbox / "Imagenes" / imgs[0].name,
                     Path.home() / "robado.jpg")]
    r = org.apply(escape)
    check("bloquea fuga fuera del sandbox",
          not r.done and r.skipped and not (Path.home() / "robado.jpg").exists(),
          r.skipped[0][1] if r.skipped else "")

    # ══════════════════ PUERTOS ══════════════════
    print("\n  ── puertos ──")
    access = SystemAccess(files=index, organizer=org)
    check("capacidades ausentes se reportan",
          "apps" in access.missing() and "files" not in access.missing(),
          f"faltan: {access.missing()}")

    # ══════════════════ NOTICIAS ══════════════════
    # Se prueba el parseo, no la red: un feed real que cambie no puede
    # convertir esta suite en intermitente.
    print("\n  ── noticias ──")
    from system.news import RssNewsReader, parse_feed
    from system.net import user_agent
    from system.ports import NewsItem

    rss = """<?xml version="1.0"?><rss version="2.0"><channel>
      <item><title>Primero</title><link>https://a.test/1</link>
        <description>&lt;p&gt;Con &lt;b&gt;html&lt;/b&gt; dentro&lt;/p&gt;</description>
        <pubDate>Sat, 15 Aug 2026 10:00:00 GMT</pubDate></item>
      <item><title>Segundo</title><link>https://a.test/2</link>
        <pubDate>Sat, 15 Aug 2026 12:00:00 GMT</pubDate></item>
    </channel></rss>"""
    atom = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
      <entry><title>Atomico</title><link href="https://b.test/1"/>
        <updated>2026-08-15T14:00:00Z</updated>
        <summary>resumen</summary></entry></feed>"""

    got = parse_feed(rss, "Prueba", "tecnologia")
    check("parsea RSS 2.0", len(got) == 2, f"{[g.title for g in got]}")
    check("limpia el html del sumario",
          got[0].summary == "Con html dentro", repr(got[0].summary))
    check("lee la fecha RFC 822", got[1].published > got[0].published)
    check("etiqueta fuente y tema",
          got[0].source == "Prueba" and got[0].topic == "tecnologia")

    atom_items = parse_feed(atom, "Atom", "mundo")
    check("parsea Atom y saca el link del atributo",
          len(atom_items) == 1 and atom_items[0].url == "https://b.test/1",
          atom_items[0].url if atom_items else "—")
    check("xml roto no revienta", parse_feed("<<<no es xml", "x") == [])

    # Un feed de portada pasa del megabyte: el tope de descarga lo parte y el
    # XML llega invalido. Perder cien titulares porque el ultimo venia a
    # medias fue un fallo real, no una hipotesis.
    cortado = rss[:rss.index("<item><title>Segundo")] + "<item><title>Segu"
    rescatados = parse_feed(cortado, "Cortado")
    check("rescata un feed truncado a media descarga",
          len(rescatados) == 1 and rescatados[0].title == "Primero",
          f"{[r.title for r in rescatados]}")

    check("intercala: un titular por medio y ronda",
          [i.source for i in RssNewsReader._interleave(
              [[NewsItem(f"a{n}", "A") for n in range(4)],
               [NewsItem(f"b{n}", "B") for n in range(4)]], 4)]
          == ["A", "B", "A", "B"],
          "ordenar todo por fecha deja que el medio mas rapido copie el briefing")

    feeds = RssNewsReader(policy, sources=[
        {"name": "A", "topic": "tecnologia", "url": "https://a.test/f"},
        {"name": "B", "topic": "mundo", "url": "https://b.test/f"}])
    check("lista los temas", feeds.topics() == ["tecnologia", "mundo"],
          str(feeds.topics()))
    check("filtra por tema", len(feeds._selected("mundo")) == 1)
    check("tema desconocido trae todo, no nada",
          len(feeds._selected("cocina")) == 2,
          "fallar en silencio seria peor que traer de mas")

    # Wikimedia responde 403 a TODO si el user-agent no lleva contacto, y
    # tambien a los que fingen ser Chrome. Es un fallo silencioso y caro de
    # diagnosticar, asi que la forma de la cadena se fija aqui.
    check("el user-agent lleva contacto",
          "(" in user_agent() and ")" in user_agent()
          and "Mozilla" not in user_agent(),
          user_agent("yo@ejemplo.com"))

    # ══════════════════ MOTOR CONMUTABLE ══════════════════
    print("\n  ── motor conmutable ──")
    from core.engine import EngineSwitch, resolve_model

    real_cfg0 = load_config(ROOT / "config" / "friday.toml")
    switch = EngineSwitch(real_cfg0)
    start_key = switch.spec.key if switch.spec else ""
    check("arranca con el modelo del toml", bool(start_key), switch.label)

    check("resuelve «cambia a sonnet»",
          getattr(resolve_model(switch.roster, "cambia a sonnet"), "key", "") == "sonnet")
    check("tolera el STT: «soneto» -> sonnet",
          getattr(resolve_model(switch.roster, "usa el soneto"), "key", "") == "sonnet")
    check("«cambia a Chrome» no es un modelo",
          resolve_model(switch.roster, "cambia a chrome") is None,
          "si compitiera, robaria ventanas a `sistema`")
    check("gana el alias mas largo",
          getattr(resolve_model(switch.roster, "ponme en modo rapido"), "key", "")
          in ("directo", "haiku"))

    target = next(s for s in switch.roster if s.key != start_key)
    ok_sw, detail = await switch.switch(target)
    check("conmuta en caliente", ok_sw and switch.spec.key == target.key, detail)
    check("el nombre del backend sigue al modelo",
          switch.name == target.backend, switch.name)
    again_ok, again_why = await switch.switch(target)
    check("cambiar al mismo no es un error", again_ok, again_why)

    # ══════════════════ PUSH TO TALK ══════════════════
    print("\n  ── push to talk ──")
    from voice.ptt import PushToTalk

    class _CfgPTT:
        def __init__(self, mode): self.mode = mode
        def get(self, k, d=None):
            return {"voice.ptt.key": "f9", "voice.ptt.mode": self.mode}.get(k, d)
        def ptt_hint(self):
            return "pulsa F9" if self.mode == "toggle" else "manten F9"

    class _Bus:
        def emit_threadsafe(self, *a, **k): pass

    def wire(mode):
        """PTT con la grabacion real sustituida: interesa la maquina de
        estados de la tecla, no abrir el microfono."""
        p = PushToTalk(_CfgPTT(mode), _Bus())
        p._begin = lambda: setattr(p, "recording", True)
        p._end = lambda: setattr(p, "recording", False)
        return p

    tg = wire("toggle")
    tg.key_down()
    check("toggle: pulsar abre", tg.recording)
    tg.key_down(); tg.key_down()          # auto-repeticion del teclado
    check("toggle: la repeticion no cierra", tg.recording,
          "sin el flanco, mantener F9 abriria y cerraria decenas de veces")
    tg.key_up()
    check("toggle: soltar no cierra", tg.recording)
    tg.key_down()
    check("toggle: la segunda pulsacion cierra", not tg.recording)

    hd = wire("hold")
    hd.key_down()
    check("hold: bajar abre", hd.recording)
    hd.key_up()
    check("hold: soltar cierra", not hd.recording)

    check("la pista de tecla sale de la config",
          real_cfg0.ptt_hint() == "pulsa F9", real_cfg0.ptt_hint())

    # ══════════════════ SKILLS Y CONFIRMACION ══════════════════
    print("\n  ── skills de sistema ──")
    real_cfg = load_config(ROOT / "config" / "friday.toml")
    vault = Vault(Path(tempfile.mkdtemp(prefix="friday_vault_")))
    graph = Graph(vault, ttl_s=0)
    skills = build_skills(real_cfg)
    router = Router(real_cfg, vault, graph, FakeEngine(real_cfg), skills,
                    system=access, policy=policy)

    # Se comprueba contra el toml, no contra un numero escrito a mano: la
    # cuenta cambia cada vez que se añade una capacidad, y una prueba que hay
    # que editar para que siga pasando no esta probando gran cosa.
    declared = list(real_cfg.get("skills.enabled", []))
    check("cargan todas las skills declaradas en el toml",
          sorted(skills) == sorted(declared),
          f"{len(skills)}/{len(declared)} — " + ", ".join(skills))

    # skill sin su puerto lo dice, no revienta
    ctx = SkillContext(real_cfg, vault, graph, FakeEngine(real_cfg),
                       text="abre spotify", system=access, policy=policy)
    res_s = await skills["sistema"].run(ctx)
    check("skill sin puerto degrada limpio",
          not res_s.ok and "sistema" not in res_s.speak.lower()[:5],
          res_s.speak[:70])

    # flujo de confirmacion completo
    seed(sandbox)
    _, res1 = await router.dispatch(f"organiza {sandbox.name}")
    # la ruta usa nombres hablados; forzamos la skill con una carpeta conocida
    check("router expone lo pendiente", "_pending" in res1.data)

    # confirmacion sintetica sobre una accion real
    from skills.base import PendingAction
    marca = {"corrio": False}

    def _accion():
        marca["corrio"] = True
        from skills.base import SkillResult
        return SkillResult(speak="hecho", display="hecho")

    router.pending = PendingAction("mover 40 archivos", _accion)
    route = await router.decide("si")
    check("«si» enruta a confirmacion", route.skill == "_confirm", route.how)
    await router.dispatch("si", route)
    check("confirmar ejecuta la accion", marca["corrio"])
    check("lo pendiente se limpia", router.pending is None)

    router.pending = PendingAction("otra cosa", _accion)
    route = await router.decide("cancela")
    check("«cancela» enruta a descarte", route.skill == "_cancel_pending")
    await router.dispatch("cancela", route)
    check("cancelar descarta", router.pending is None)

    marca["corrio"] = False
    router.pending = PendingAction("caducada", _accion, ttl_s=-1)
    route = await router.decide("si")
    check("lo pendiente caduca", route.skill != "_confirm" and not marca["corrio"])

    shutil.rmtree(sandbox, ignore_errors=True)
    shutil.rmtree(vault.root, ignore_errors=True)

    bad = [n for n, ok, _ in results if not ok]
    print(f"\n  {len(results) - len(bad)}/{len(results)} pruebas pasaron")
    if bad:
        print(f"  fallaron: {', '.join(bad)}\n")
        return 1
    print("  capa de sistema verde.\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
