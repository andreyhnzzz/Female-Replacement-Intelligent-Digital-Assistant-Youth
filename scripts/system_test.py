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
import time
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

# Directorios de codigo propio a auditar estaticamente. No scripts/ (ahi
# viven pruebas y utilidades de desarrollador, no lo que corre en la app) ni
# .venv (dependencias de terceros).
_PAQUETES_PROPIOS = ("core", "memory", "skills", "system", "voice", "desktop")


def _subprocess_sin_no_window() -> list[str]:
    """Llamadas a `subprocess.run/Popen/call/check_output` sin `creationflags`.

    FRIDAY corre sin consola (`pythonw.exe`): un proceso hijo de consola sin
    `CREATE_NO_WINDOW` le abre una ventana negra propia, parpadeando encima
    del escritorio en cada turno hablado. Es una trampa ya conocida
    (ver CLAUDE.md, "Todo proceso hijo va con NO_WINDOW") y sin este chequeo
    vuelve a colarse cada vez que alguien agrega un `subprocess.*` nuevo sin
    acordarse. Analisis estatico via `ast`, no una regex: una regex se
    confunde con comentarios y strings que mencionen "subprocess".
    """
    import ast

    objetados: list[str] = []
    nombres = {"run", "Popen", "call", "check_output", "check_call"}
    for paquete in _PAQUETES_PROPIOS:
        base = ROOT / paquete
        if not base.is_dir():
            continue
        for archivo in base.rglob("*.py"):
            try:
                arbol = ast.parse(archivo.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            for nodo in ast.walk(arbol):
                if not isinstance(nodo, ast.Call):
                    continue
                fn = nodo.func
                es_subprocess = (
                    isinstance(fn, ast.Attribute) and fn.attr in nombres
                    and isinstance(fn.value, ast.Name) and fn.value.id == "subprocess")
                if not es_subprocess:
                    continue
                tiene_flag = any(kw.arg == "creationflags" for kw in nodo.keywords)
                if not tiene_flag:
                    objetados.append(f"{archivo.relative_to(ROOT)}:{nodo.lineno}")
    return objetados


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


def pruebas_windows(sandbox: Path) -> None:
    """Catalogo de aplicaciones y apps predeterminadas.

    Vive aparte porque `winreg` solo existe en Windows: el resto de la
    suite es multiplataforma y tiene que poder correr igual.
    """
    print("\n  ── catalogo de aplicaciones ──")
    from system.ports import AppInfo, DefaultApp
    from system.web import BrowserWebOpener
    from system.win32.apps import (
        _STEAM_NOISE,
        WindowsAppCatalog,
        _merge_aliases,
        _score,
        steam_libraries,
    )
    from system.win32.defaults import _exe_from_command, _pretty

    check("un alias del toml admite texto suelto o lista",
          _merge_aliases({"mapa": "google maps",
                          "hoja": ["microsoft excel"]})["mapa"]
          == ("google maps",))
    check("los alias del codigo siguen ahi",
          "code" in _merge_aliases(None)["vscode"],
          "«abre vscode» no puede depender de que exista un .lnk")

    # Incidente del 17/08/2026: «Descríbete a ti misma en dos palabras» se
    # enruto a `sistema` y FRIDAY lanzo el changelog de WinRAR. Las dos
    # frases solo comparten la palabra «en», y eso puntuaba 0.45.
    check("una palabra vacia compartida no empareja dos frases ajenas",
          _score("Describete a ti misma en dos palabras",
                 "Que hay de nuevo en la ultima version") == 0.0,
          f"{_score('Describete a ti misma en dos palabras', 'Que hay de nuevo en la ultima version')}")
    check("y las coincidencias de verdad siguen valiendo",
          _score("discord", "Discord") == 1.0
          and _score("visual studio code", "Visual Studio Code 2022") == 0.9
          and _score("geometry dash", "Geometry Dash") == 1.0)

    check("los redistribuibles de Steam no son juegos",
          bool(_STEAM_NOISE.search("Steamworks Common Redistributables"))
          and not _STEAM_NOISE.search("Geometry Dash"))

    # Varias bibliotecas: quien tiene un SSD chico reparte los juegos, y
    # asumir una sola carpeta deja fuera justo los pesados.
    otra = sandbox / "OtroDisco"
    (otra / "steamapps").mkdir(parents=True)
    (sandbox / "steamapps").mkdir()
    (sandbox / "steamapps" / "libraryfolders.vdf").write_text(
        '"libraryfolders"\n{\n "0"\n {\n  "path" "'
        + str(otra).replace("\\", "\\\\") + '"\n }\n}\n', encoding="utf-8")
    libs = steam_libraries(sandbox)
    check("lee todas las bibliotecas de Steam, no solo la primera",
          len(libs) == 2 and (otra / "steamapps") in libs,
          f"{[str(p) for p in libs]}")

    cat = WindowsAppCatalog(ttl_s=999, aliases={"cs": ["counter-strike 2"]},
                            include_store=False, include_steam=False)
    cat._apps = [AppInfo("Counter-Strike 2", "steam://rungameid/730", "uri"),
                 AppInfo("Calculadora", "calc.exe", "exe")]
    cat._built = time.time()
    hits_cs = cat.find("cs")
    check("un alias hablado encuentra el juego",
          bool(hits_cs) and hits_cs[0].name == "Counter-Strike 2",
          str([h.name for h in hits_cs]))
    check("un juego se lanza por URI, no por ejecutable",
          bool(hits_cs) and hits_cs[0].target.startswith("steam://"),
          hits_cs[0].target if hits_cs else "—")

    # ── navegador predeterminado ──
    print("\n  ── navegador predeterminado ──")
    check("saca el ejecutable de la linea de comando del registro",
          _exe_from_command(f'"{sys.executable}" --single-argument %1')
          == sys.executable)
    check("un ProgId no se dice en voz alta",
          _pretty(r"C:\x\brave.exe", "BraveHTML") == "Brave",
          "«BraveHTML» es un identificador, no un nombre")
    check("sin ejecutable resuelto no se inventa una ruta",
          _exe_from_command("no-existe-esto.exe %1") == "")

    class _DefsFalsos:
        def browser(self): return DefaultApp(name="Brave", progid="BraveHTML")
        def for_scheme(self, s): return self.browser()

    opener = BrowserWebOpener(Policy(FakeCfg(sandbox, allow_web=False)),
                              "google", defaults=_DefsFalsos())
    check("FRIDAY sabe COMO SE LLAMA el navegador predeterminado",
          opener.browser_name == "Brave", opener.browser_name)
    check("sin permiso no se abre ninguna busqueda",
          opener.search("gatos") == "" and "deshabilitado" in opener.last_error,
          opener.last_error)


def _con_texto(ctx, texto: str):
    """El mismo contexto con otra frase. `SkillContext` es un dataclass, no
    un objeto vivo: copiarlo es mas honesto que mutarlo entre pruebas."""
    import dataclasses
    return dataclasses.replace(ctx, text=texto)


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

    # Si el toml no declara `blocked_apps`, el piso por defecto sigue
    # cubriendo los binarios de Windows que dan shell o tocan el sistema
    # ("living-off-the-land"): no es solo regedit/cmd, la lista quedaba
    # corta contra pwsh, wt, mshta, rundll32...
    from core.policy import Policy as _PolicyDefault
    cfg_sin_blocklist = FakeCfg(sandbox)
    del cfg_sin_blocklist._d["policy.blocked_apps"]
    politica_default = _PolicyDefault(cfg_sin_blocklist)
    check("sin blocked_apps propio, el piso por defecto sigue activo",
          not politica_default.can_launch("mshta.exe").allowed
          and not politica_default.can_launch("pwsh.exe").allowed
          and not politica_default.can_launch("wt.exe").allowed,
          "regedit y cmd no son la unica forma de dar shell")
    check("el piso por defecto no bloquea apps normales",
          politica_default.can_launch("notepad.exe").allowed)
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
    # Estas siete entraban. El parser partia la cadena a mano y `[::1]`
    # acababa siendo `[`, asi que el propio chequeo de loopback IPv6 que
    # habia escrito no podia dispararse nunca.
    evasiones = {
        "decimal": "http://2130706433/x",
        "hexadecimal": "http://0x7f000001/x",
        "loopback IPv6": "http://[::1]/x",
        "ULA IPv6": "http://[fd00::1]/x",
        "enlace local IPv6": "http://[fe80::1]/x",
        "sin especificar": "http://0.0.0.0/x",
        "userinfo delante": "http://usuario@127.0.0.1:8080/x",
        "metadatos de nube": "http://169.254.169.254/latest/meta-data",
    }
    for nombre, u in evasiones.items():
        check(f"no cuela loopback en {nombre}", not policy.can_fetch(u).allowed, u)
    check("mayusculas no esquivan localhost",
          not policy.can_fetch("http://LOCALHOST/x").allowed)
    check("un puerto roto no revienta el guardia",
          not policy.can_fetch("http://ejemplo.com:puerto/x").allowed)
    check("una web publica normal sigue pasando",
          policy.can_fetch("https://es.wikipedia.org/wiki/Python").allowed)

    check("respeta la lista negra de hosts",
          not Policy(FakeCfg(sandbox, blocked_hosts=["*.malo.com"]))
          .can_fetch("https://x.malo.com/a").allowed)
    check("allow_web_fetch=false lo apaga todo",
          not Policy(FakeCfg(sandbox, allow_web_fetch=False))
          .can_fetch("https://ejemplo.com").allowed)

    # ── delegar en un agente: el permiso mas fuerte del sistema ──
    # Un agente con permiso de escritura dirigido por un STT que se
    # equivoca. La lista blanca no es un filtro: es de donde salen las
    # opciones, y vacia significa que la capacidad no alcanza nada.
    agente = Policy(FakeCfg(sandbox, agent_roots=[str(sandbox)]))
    check("delega dentro de la raiz declarada",
          agente.can_delegate(sandbox / "proyecto").allowed)
    check("una tarea que escribe se confirma antes de lanzar",
          agente.can_delegate(sandbox, writes=True).verdict is Verdict.CONFIRM,
          agente.can_delegate(sandbox, writes=True).reason)
    check("fuera de agent_roots no se delega",
          not agente.can_delegate(Path.home()).allowed,
          agente.can_delegate(Path.home()).reason)
    check("sin agent_roots la capacidad esta apagada entera",
          not policy.can_delegate(sandbox).allowed,
          "poder escribir en Documentos no es poder refactorizar ahi")
    check("allow_agent=false lo apaga aunque haya raices",
          not Policy(FakeCfg(sandbox, allow_agent=False,
                             agent_roots=[str(sandbox)])).can_delegate(sandbox).allowed)

    # ── retirar memoria: el unico permiso que QUITA algo ──
    # No se apoya en `write_roots` a proposito: el vault no esta ahi y no
    # tiene por que estarlo. La frontera es el vault, porque lo que se
    # retira son notas que escribio FRIDAY y que ya viven resumidas en otra.
    boveda = sandbox / "boveda"
    (boveda / "raw").mkdir(parents=True, exist_ok=True)
    diaria = boveda / "raw" / "2020-01-01.md"
    diaria.write_text("x", encoding="utf-8")

    podar = Policy(FakeCfg(sandbox))
    podar.vault_root = boveda.resolve()
    check("retira una nota de dentro del vault",
          podar.can_prune([diaria]).allowed)
    # Un .md, para que lo que decida sea la frontera del vault y no la
    # extension: fuera del vault hay markdown del usuario, y es justo el
    # caso que este permiso tiene que rechazar.
    # En una subcarpeta: el sandbox de arriba es el desorden que organiza la
    # prueba de `archivos`, y un .md suelto ahi le cambia la cuenta.
    papeles = sandbox / "papeles"
    papeles.mkdir(exist_ok=True)
    fuera_md = papeles / "apuntes mios.md"
    fuera_md.write_text("mios", encoding="utf-8")
    check("no retira notas de fuera del vault",
          not podar.can_prune([fuera_md]).allowed,
          podar.can_prune([fuera_md]).reason)
    check("no retira lo que no es una nota",
          not podar.can_prune([boveda / "raw" / "algo.exe"]).allowed,
          "una ruta con otra extension no llego de la consolidacion")
    check("un solo camino malo tumba el lote entero",
          not podar.can_prune([diaria, sandbox / "musica.mp3"]).allowed,
          "gana la decision mas restrictiva")
    apagado = Policy(FakeCfg(sandbox, allow_memory_prune=False))
    apagado.vault_root = boveda.resolve()
    check("allow_memory_prune=false lo apaga",
          not apagado.can_prune([diaria]).allowed)
    check("y escribir archivos sigue permitido",
          apagado.can_write(sandbox / "x.txt").allowed,
          "son dos permisos distintos, no uno con dos nombres")

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
    from system.net import user_agent
    from system.news import RssNewsReader, parse_feed
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

    # ══════════════════ EL TALLER ══════════════════
    # Encargarle trabajo a un agente hablando. Lo que se prueba es el
    # guardia y el reconocimiento, no el agente: elegir mal la carpeta o
    # confundir «revisa» con «arregla» es lo que cuesta una tarde.
    print("\n  ── taller ──")
    from skills.taller import TallerSkill

    taller = TallerSkill(real_cfg0)
    proyectos = [("api", Path("x/api")), ("api_clientes", Path("x/api_clientes"))]

    check("gana el nombre de proyecto mas largo",
          taller._elegir("metete en api_clientes y revisa", proyectos)[0]
          == "api_clientes",
          "con `api` y `api_clientes` en disco, el corto no puede robar")
    check("el STT separa los guiones y aun asi acierta",
          taller._elegir("metete en api clientes y revisa los tests",
                         proyectos)[0] == "api_clientes")
    check("sin proyecto nombrado no se elige ninguno",
          taller._elegir("revisa por que fallan los tests", proyectos) is None,
          "preguntar es mejor que abrir un repo al azar")
    check("dos carpetas que responden igual de bien no eligen ninguna",
          taller._elegir("metete en api y arregla algo",
                         [("api", Path("x/uno/api")), ("api", Path("x/dos/api"))])
          is None,
          "preguntar cuesta una frase; equivocarse de repo cuesta una tarde")

    check("la tarea queda limpia de «metete en X y»",
          taller._tarea("metete en api_clientes y revisa por que fallan los tests",
                        "api_clientes") == "revisa por que fallan los tests",
          taller._tarea("metete en api_clientes y revisa por que fallan los tests",
                        "api_clientes"))

    check("revisar no escribe", not taller._escribe("revisa por que fallan los tests"))
    check("arreglar escribe", taller._escribe("arregla los tests"))
    check("«revisa y arregla» escribe: gana el verbo mas peligroso",
          taller._escribe("revisa y arregla los tests"))
    check("una tarea que no se reconoce se trata como escritura",
          taller._escribe("haz lo tuyo ahi"),
          "no entender la intencion no es razon para asumir la version inofensiva")

    check("el resumen hablado sale de la ultima linea",
          taller._resumen("mucho texto\nRESUMEN: dos tests rotos, ya los nombre")
          == "dos tests rotos, ya los nombre")

    # Sin `agent_roots` la skill no ofrece nada, y lo dice en vez de fallar.
    class MotorAgentico(FakeEngine):
        agentic_capable = True

    ctx_t = SkillContext(real_cfg0, None, None, MotorAgentico(real_cfg0),
                         text="metete en lo que sea y arregla algo",
                         system=None, policy=policy)
    res_t = await taller.run(ctx_t)
    check("sin directorios declarados no hay nada que tocar",
          not res_t.ok and "directorio" in res_t.speak.lower(), res_t.speak[:60])

    # El encargo NO bloquea el turno: contesta «voy con ello» y el
    # resultado vuelve por el bus cuando el agente termina. Si esto se
    # rompe, FRIDAY se queda muda los minutos que dure el trabajo.
    from core.bus import BUS

    proyecto = sandbox / "proyecto_demo"
    proyecto.mkdir(exist_ok=True)
    pol_taller = Policy(FakeCfg(sandbox, agent_roots=[str(sandbox)]))

    class MotorTrabajador(FakeEngine):
        agentic_capable = True

        def __init__(self, cfg):
            super().__init__(cfg)
            self.kw: dict = {}

        async def complete(self, prompt, system="", **kw):
            self.kw = kw
            return "mire los tests\nRESUMEN: fallan dos por una ruta fija"

    dichos: list[dict] = []

    async def _oye(ev):
        dichos.append(ev.data)

    # Un `sleep` fijo para esperar la tarea de fondo es una carrera latente:
    # con la maquina cargada 0.2s puede no bastar y el test falla sin que
    # nada este roto de verdad. Se espera el evento real del bus
    # (`agent.done`, que `_trabajar` emite justo antes de `core.say`).
    hecho = asyncio.Event()

    async def _hecho(ev):
        hecho.set()

    BUS.on("core.say", _oye)
    BUS.on("agent.done", _hecho)
    motor_t = MotorTrabajador(real_cfg0)

    res_lee = await taller.run(SkillContext(
        real_cfg0, None, None, motor_t, policy=pol_taller,
        text="metete en proyecto_demo y revisa por que fallan los tests"))
    check("una tarea de lectura arranca sin confirmar",
          res_lee.ok and res_lee.pending is None and res_lee.data.get("async"),
          res_lee.speak[:60])
    check("contesta antes de terminar el trabajo",
          "voy con ello" in res_lee.speak.lower(), res_lee.speak[:40])

    await asyncio.wait_for(hecho.wait(), timeout=5)   # dejar correr la tarea de fondo
    check("el resultado vuelve por el bus cuando acaba",
          bool(dichos) and "fallan dos" in dichos[-1].get("text", ""),
          dichos[-1].get("text", "")[:60] if dichos else "no llego nada")
    check("un encargo de lectura no lleva herramientas de escritura",
          "Write" not in motor_t.kw.get("tools", []),
          str(motor_t.kw.get("tools")))
    check("el agente corre en el directorio del proyecto",
          motor_t.kw.get("cwd") == str(proyecto), str(motor_t.kw.get("cwd")))

    res_esc = await taller.run(SkillContext(
        real_cfg0, None, None, motor_t, policy=pol_taller,
        text="metete en proyecto_demo y arregla los tests"))
    check("una tarea que escribe espera un «si» hablado",
          res_esc.pending is not None and res_esc.data.get("writes"),
          res_esc.speak[:70])
    check("la confirmacion repite QUE y DONDE",
          "proyecto_demo" in res_esc.pending.describe
          and "arregla" in res_esc.pending.describe,
          res_esc.pending.describe)

    hecho.clear()
    res_esc.pending.run()
    await asyncio.wait_for(hecho.wait(), timeout=5)
    check("solo tras confirmar recibe herramientas de escritura",
          "Write" in motor_t.kw.get("tools", []), str(motor_t.kw.get("tools")))

    # ── el motor agentico: cwd por llamada y permisos clavados ──
    # `bypassPermissions` no se acepta ni pidiendolo por config. Se
    # comprueba sobre el argv real, sin llegar a levantar Node.
    from core.engine import ClaudeCodeEngine

    capturado: dict[str, object] = {}

    class _ProcFalso:
        returncode = 0
        async def communicate(self, input=None):        # noqa: A002
            return b'{"result":"hecho"}', b""
        def kill(self): pass

    async def _exec_falso(*argv, **kw):
        capturado["argv"] = list(argv)
        capturado["cwd"] = kw.get("cwd")
        return _ProcFalso()

    cc = ClaudeCodeEngine(real_cfg0)
    cc._resolve_binary = lambda: ["claude"]
    original_exec = asyncio.create_subprocess_exec
    asyncio.create_subprocess_exec = _exec_falso
    try:
        salida = await cc.complete("haz algo", agentic=True, cwd=str(sandbox),
                                   permission_mode="bypassPermissions",
                                   tools=["Read", "Grep"], timeout=5)
    finally:
        asyncio.create_subprocess_exec = original_exec

    argv = capturado.get("argv", [])
    check("el motor agentico corre en el directorio de la llamada",
          capturado.get("cwd") == str(sandbox), str(capturado.get("cwd")))
    check("bypassPermissions no se acepta ni pidiendolo",
          "bypassPermissions" not in argv and "acceptEdits" in argv,
          "si una tarea lo necesita, la haces tu en la terminal")
    check("las herramientas van por llamada, no por constructor",
          "Read,Grep" in argv, str([a for a in argv if "," in str(a)]))
    check("el sobre JSON se desenvuelve", salida == "hecho", salida)
    check("el motor declara si sabe trabajar en un repo",
          ClaudeCodeEngine.agentic_capable and not Engine.agentic_capable,
          "es una capacidad, no una marca: la skill no pregunta «¿eres Claude?»")

    # ══════════════════ APLICACIONES ══════════════════
    # Especifico de Windows (`winreg` no existe en otro sitio), asi que
    # vive en su propia funcion y se salta entera fuera de Windows.
    if sys.platform == "win32":
        pruebas_windows(sandbox)

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

    # ══════════════════ VOZ DE SALIDA ══════════════════
    # SAPI5 es COM con afinidad de apartamento: construirlo en un hilo y
    # usarlo en otro cuelga runAndWait() para el resto de la sesion. Fue un
    # fallo real y silencioso — la voz simplemente dejaba de salir. Estas
    # pruebas fijan la invariante sin llegar a hablar.
    print("\n  ── voz de salida ──")
    from voice.tts import LocalTTS

    habla = LocalTTS(real_cfg0)
    habla.load()
    check("load() detecta backend sin construir la voz",
          habla.backend in ("piper", "piper-cli", "sapi5", "none")
          and habla._sapi is None,
          f"backend={habla.backend}, objeto COM={habla._sapi!r}")

    # shutup() lo llama el hilo de asyncio; si tocara COM, reventaria.
    habla.say("esto no se llega a decir")
    habla.shutup()
    check("shutup() no toca COM ni deja cola",
          habla._q.empty() and habla._cut.is_set())

    check("wait_until_idle responde con la cola vacia",
          habla.wait_until_idle(timeout=1.0))

    mudo = LocalTTS(real_cfg0)
    mudo.muted = True
    mudo.say("silenciada")
    check("mute no encola nada", mudo._q.empty())

    check("markdown no se pronuncia",
          LocalTTS.clean("## Titulo\n- **dato** con [[Nota|alias]] y `code`")
          == "Titulo dato con alias y code",
          LocalTTS.clean("## Titulo\n- **dato** con [[Nota|alias]] y `code`"))

    # ══════════════════ CONTROL DEL ORDENADOR ══════════════════
    # La accion la elige el motor, no una regex. Eso significa que el motor
    # puede equivocarse o alucinar, asi que lo que se prueba aqui es el
    # guardia: que el catalogo sea lista blanca y que la politica mande.
    print("\n  ── control del ordenador ──")
    from skills.ordenador import CATALOGO, OrdenadorSkill

    class Espia:
        """Puertos falsos: apuntan lo que se les pide, no tocan la maquina."""
        def __init__(self): self.log = []
        def volume(self, d): self.log.append(("volume", d)); return d
        def set_volume(self, nivel): self.log.append(("set_volume", nivel)); return nivel
        def mute(self): self.log.append(("mute",)); return True
        def playback(self, a): self.log.append(("playback", a)); return True
        def read(self): self.log.append(("read",)); return "copiado"
        def write(self, t): self.log.append(("write", t)); return True
        def lock(self): self.log.append(("lock",)); return True
        def sleep(self): self.log.append(("sleep",)); return True

    class MotorFijo(Engine):
        """Devuelve una propuesta fija, como si fuera lo que dijo el modelo."""
        name = "fijo"
        def __init__(self, cfg, payload): super().__init__(cfg); self.payload = payload
        async def complete(self, prompt, system="", **kw): return self.payload

    class CfgSesion:
        """La config real, pero con el control de sesion permitido."""
        def __init__(self, base, **over): self._b, self._o, self.root = base, over, base.root
        def get(self, k, d=None):
            return self._o[k] if k in self._o else self._b.get(k, d)
        def persona(self): return self._b.persona()

    orden = OrdenadorSkill(real_cfg0)

    async def pedir(payload, acceso, politica):
        motor = MotorFijo(real_cfg0, payload)
        ctx = SkillContext(real_cfg0, None, None, motor, text="lo que sea",
                           system=acceso, policy=politica)
        return await orden.run(ctx)

    espia = Espia()
    libre = SystemAccess(media=espia, clipboard=espia, session=espia)
    pol_libre = Policy(CfgSesion(real_cfg0, **{"policy.allow_session": True}))

    espia.log.clear()
    res_o = await pedir('{"accion":"volumen_cambiar","args":{"cuanto":25},'
                        '"confianza":0.9,"porque":"subir"}', libre, pol_libre)
    check("ejecuta la accion que eligio el motor",
          espia.log == [("volume", 25)], str(espia.log))

    # El catalogo es lista blanca: si el modelo inventa, no hay nada que llamar.
    espia.log.clear()
    res_o = await pedir('{"accion":"formatear_disco","args":{},'
                        '"confianza":0.99,"porque":"alucinacion"}', libre, pol_libre)
    check("una accion inventada por el motor no existe",
          espia.log == [] and not res_o.pending,
          "el catalogo es la lista blanca, diga lo que diga el modelo")

    espia.log.clear()
    res_o = await pedir('{"accion":"silenciar","args":{},'
                        '"confianza":0.2,"porque":"dudoso"}', libre, pol_libre)
    check("poca confianza no toca nada", espia.log == [], str(espia.log))

    # Sesion permitida -> se confirma, no se ejecuta todavia.
    espia.log.clear()
    res_o = await pedir('{"accion":"bloquear","args":{},'
                        '"confianza":0.95,"porque":"se va"}', libre, pol_libre)
    check("bloquear espera un «si» explicito",
          res_o.pending is not None and espia.log == [],
          f"pendiente={bool(res_o.pending)}, ejecutado={espia.log}")
    if res_o.pending:
        res_o.pending.run()
        check("y se aplica solo tras confirmar", espia.log == [("lock",)], str(espia.log))

    # Sesion denegada -> ni se pregunta.
    espia.log.clear()
    pol_estricta = Policy(CfgSesion(real_cfg0, **{"policy.allow_session": False}))
    res_o = await pedir('{"accion":"bloquear","args":{},'
                        '"confianza":0.95,"porque":"se va"}', libre, pol_estricta)
    check("sin permiso no se ejecuta y se dice por que",
          not res_o.ok and espia.log == [] and "session" in res_o.error,
          res_o.speak[:60])

    # Un puerto ausente saca la accion del catalogo que ve el motor.
    espia.log.clear()
    res_o = await pedir('{"accion":"volumen_cambiar","args":{"cuanto":10},'
                        '"confianza":0.9,"porque":"x"}',
                        SystemAccess(clipboard=espia), pol_libre)
    check("una capacidad sin puerto no se ofrece", espia.log == [], str(espia.log))

    # ── el modelo pequeño: tolerar la FORMA, no aflojar el fondo ──
    # Regla 3 del CLAUDE.md: un prompt debe funcionar con un 8B local. Estas
    # son las salidas que de verdad produce uno, y cada una costaba el turno
    # entero antes de tolerarlas.
    espia.log.clear()
    res_o = await pedir("Claro, Jefe. {'accion': 'volumen_cambiar', "
                        "'args': {'cuanto': 20}, 'porque': 'subir',}",
                        libre, pol_libre)
    check("comillas simples, coma colgante y prosa alrededor",
          espia.log == [("volume", 20)], str(espia.log))

    # La que mas dolia: eligio bien y se tiraba por un campo de metadatos.
    espia.log.clear()
    res_o = await pedir('{"accion":"silenciar","args":{}}', libre, pol_libre)
    check("que falte la confianza no es que el modelo dude",
          espia.log == [("mute",)],
          "antes contestaba «no me quedo claro» con la accion ya elegida")

    espia.log.clear()
    res_o = await pedir('{"accion":"silenciar","args":{},"confianza":"alta"}',
                        libre, pol_libre)
    check("la confianza en palabras tambien vale", espia.log == [("mute",)],
          str(espia.log))

    espia.log.clear()
    res_o = await pedir('{"accion":"volumen_fijar","args":"{\\"nivel\\": 30}",'
                        '"confianza":85}', libre, pol_libre)
    check("args anidados como texto y confianza en porcentaje",
          espia.log == [("set_volume", 30)], str(espia.log))

    espia.log.clear()
    res_o = await pedir('{"accion":"Volumen Cambiar","args":{"cuanto":5},'
                        '"confianza":0.9}', libre, pol_libre)
    check("el nombre de la accion se normaliza",
          espia.log == [("volume", 5)], str(espia.log))

    # Y lo que NO se afloja: la lista blanca y la desconfianza declarada.
    espia.log.clear()
    res_o = await pedir('{"accion":"formatear_disco","args":{},"confianza":"alta"}',
                        libre, pol_libre)
    check("tolerar la forma no abre la lista blanca", espia.log == [], str(espia.log))
    espia.log.clear()
    res_o = await pedir('{"accion":"silenciar","args":{},"confianza":0.2}',
                        libre, pol_libre)
    check("una confianza baja DICHA si se respeta", espia.log == [],
          "ausente y baja son cosas distintas")

    # Contra la tabla de despacho real, no contra una lista transcrita aqui:
    # una prueba que hay que editar cada vez que añades una capacidad para
    # que siga pasando no esta probando la invariante, la esta repitiendo.
    manos = OrdenadorSkill(real_cfg0)._manos(None, {})
    check("toda accion del catalogo tiene implementacion",
          not (set(a.nombre for a in CATALOGO) - set(manos)),
          f"{len(CATALOGO)} declaradas, {len(manos)} cableadas")
    check("y no hay implementaciones huerfanas",
          not (set(manos) - set(a.nombre for a in CATALOGO)),
          "una mano sin entrada en el catalogo es inalcanzable")

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

    # ── el enrutado se equivoca; lanzar no puede ser el plan B ──
    # El 17/08/2026, con un modelo local, «Descríbete a ti misma en dos
    # palabras» se enruto a `sistema` con confianza 0.85 y FRIDAY abrio el
    # changelog de WinRAR. El enrutado es probabilistico y siempre lo sera;
    # lo que no puede serlo es que la rama por defecto de una skill con
    # efecto sobre la maquina sea «lanza lo que mejor puntue».
    class CatalogoFalso:
        def __init__(self): self.consultas: list[str] = []
        def find(self, query, limit=5):
            self.consultas.append(query)
            return [AppInfoPorts("Que hay de nuevo en la ultima version",
                                 "C:/x/winrar.lnk", "shortcut", None, 0.45)]
        def refresh(self): return 1

    class LanzadorFalso:
        def __init__(self): self.lanzadas: list[str] = []
        def launch(self, app, args=None):
            self.lanzadas.append(app.name)
            return True

    from system.ports import AppInfo as AppInfoPorts

    cat_falso, lanz_falso = CatalogoFalso(), LanzadorFalso()
    acceso_apps = SystemAccess(apps=cat_falso, launcher=lanz_falso)
    ctx_s = SkillContext(real_cfg, vault, graph, FakeEngine(real_cfg),
                         text="Descríbete a ti misma en dos palabras.",
                         system=acceso_apps, policy=policy)
    res_mal = await skills["sistema"].run(ctx_s)
    check("una frase sin verbo de accion NO lanza nada",
          not lanz_falso.lanzadas and not res_mal.ok,
          f"lanzadas={lanz_falso.lanzadas}")
    check("y ni siquiera se consulta el catalogo",
          not cat_falso.consultas,
          "buscar una frase entera en el Menu Inicio es como empieza el accidente")

    ctx_s.text = "abre discord"
    res_bien = await skills["sistema"].run(ctx_s)
    check("y «abre X» sigue lanzando", bool(lanz_falso.lanzadas) and res_bien.ok,
          f"lanzadas={lanz_falso.lanzadas}")

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

    # ══════════════════ LO QUE NO PUEDE DECLARARSE POR TOML ══════════════════
    print()
    print("  ── el toml no otorga permisos ──")
    from skills.taller import _tools_permitidas

    sin_shell = Policy(FakeCfg(sandbox))
    ok_tools, fuera = _tools_permitidas(["Read", "Grep", "Bash"], sin_shell)
    check("una tarea de solo lectura no puede traer Bash por el toml",
          "Bash" not in ok_tools and "Bash" in fuera,
          "allow_shell esta en false: la lista se filtra, no se obedece")
    check("y lo inofensivo se queda", ok_tools == ["Read", "Grep"])
    check("retirar no es silencioso", bool(fuera), f"retiradas={fuera}")
    con_shell = Policy(FakeCfg(sandbox, allow_shell=True))
    ok2, fuera2 = _tools_permitidas(["Read", "Bash"], con_shell)
    check("con allow_shell en true si pasa", "Bash" in ok2 and not fuera2)

    # ══════════════════ EL BUS CUENTA LO QUE REVIENTA ══════════════════
    print()
    print("  ── nada falla en silencio ──")
    from core.bus import Bus

    bus = Bus()
    dicho: list[str] = []
    bus.on_error = dicho.append

    async def handler_roto(ev):
        raise RuntimeError("reventé")

    bus.on("prueba.tema", handler_roto)
    await bus.emit("prueba.tema", x=1)
    check("un handler roto no tumba el bus", True)
    check("y el fallo llega a la bitacora",
          any("reventé" in d for d in dicho), dicho[0] if dicho else "(nada)")
    check("y queda como evento consultable",
          any(e["topic"] == "core.error" for e in bus.recent(prefix="core.error")))

    bus2 = Bus()
    bus2.on_error = dicho.append
    bus2.on("core.error", handler_roto)      # el que falla escucha core.error
    await bus2.emit("core.error", message="x")
    check("informar de un fallo no entra en bucle", True,
          "core.error no se reemite por el bus")

    # ══════════════════ EL CACHE DEL VAULT TIENE TECHO ══════════════════
    print()
    print("  ── el cache no crece sin fin ──")
    caja = Path(tempfile.mkdtemp(prefix="friday_cache_"))
    v = Vault(caja, cache_max=64)
    for i in range(200):
        v.write(v.raw / f"nota-{i:03}.md", f"apunte numero {i}")
    for p_ in sorted(v.files()):
        v.read(p_)
    check("el cache se queda en su tope", len(v._cache) <= 64,
          f"{len(v._cache)} entradas tras leer 200 notas")
    ultima = sorted(v.files())[-1]
    check("y conserva lo mas reciente", ultima in v._cache)
    check("releer sigue dando lo mismo",
          "apunte numero 199" in v.read(ultima).body)
    shutil.rmtree(caja, ignore_errors=True)

    # ══════════════════ EL ESQUEMA NO EXIGE DE MAS ══════════════════
    print()
    print("  ── el contrato JSON no se inventa campos ──")
    from core.engine import enum_schema

    esq = enum_schema({"accion": ["subir", "bajar"], "confianza": "number"})
    check("sin decir nada, no hay campos obligatorios", esq["required"] == [],
          "un campo requerido no se piensa, se rellena con 0")
    esq2 = enum_schema({"accion": ["subir"], "confianza": "number"},
                       requeridos=["accion"])
    check("y se exige lo que se pide", esq2["required"] == ["accion"])
    check("el enum sigue acotando", esq["properties"]["accion"]["enum"] == ["subir", "bajar"])

    # ── documentos ────────────────────────────────────────────────
    print("\n  ── documentos: generar sin pisar a nadie ──")
    from skills.documentos import DocumentosSkill
    from system.documents import LocalDocumentWriter

    doc_skill = DocumentosSkill(FakeCfg(sandbox))
    crear = ["hazme un pdf con el resumen", "pasa esto a excel",
             "exportame la lista a xlsx", "genera una hoja de calculo"]
    ajeno = ["abre el pdf del contrato", "busca mis pdf de facturas",
             "listame los pdf que tengo", "abre la carpeta documentos",
             "busca en mis documentos el informe", "pasa a la siguiente cancion",
             "sube el volumen", "cuanta memoria ram me queda"]
    check("reconoce lo suyo: crear + formato",
          all(doc_skill.matches(f) > 0.9 for f in crear),
          f"{[doc_skill.matches(f) for f in crear]}")
    check("y no le roba a sistema, archivos ni ordenador",
          all(doc_skill.matches(f) == 0.0 for f in ajeno),
          "abrir o buscar un pdf no es fabricarlo")
    check("sin formato reconocido no actua",
          doc_skill.matches("hazme un resumen de esto") == 0.0)

    escritor = LocalDocumentWriter()
    # Este proceso no tiene QGuiApplication, asi que `pdf` NO puede ofrecerse.
    check("formats() no promete pdf sin interfaz", "pdf" not in escritor.formats(),
          f"{escritor.formats()}")
    try:
        escritor.write_pdf(sandbox / "x.pdf", "t", "cuerpo")
        aborto = "no lanzo nada"
    except RuntimeError as exc:
        aborto = str(exc)[:40]
    check("y pedirlo igualmente avisa en vez de matar el proceso",
          aborto != "no lanzo nada", aborto)

    hoja = escritor.write_sheet(sandbox / "tabla.xlsx", ["Mes", "Gasto"],
                                [["Enero", 120], ["Febrero", 95]])
    check("escribe la hoja", hoja.exists() and hoja.stat().st_size > 0, hoja.name)
    check("y devuelve la ruta REAL, no la pedida", hoja.suffix in (".xlsx", ".csv"))

    fuera = Path(tempfile.gettempdir()) / "no_deberia.pdf"
    check("el destino pasa por politica",
          not policy.can_write(fuera).allowed,
          "fuera de write_roots no se escribe aunque lo pidas")

    # ── varios proveedores en el mismo roster ──────────────────────
    print("\n  ── un roster, varios proveedores ──")
    from core.engine import EngineSwitch

    class CfgRoster(FakeCfg):
        def get(self, clave, defecto=None):
            if clave == "engine.roster":
                return [
                    {"key": "ds", "label": "DeepSeek", "backend": "openai_compat",
                     "model": "deepseek-chat", "base_url": "https://api.deepseek.com/v1",
                     "api_key_env": "DEEPSEEK_API_KEY", "say": ["deepseek"]},
                    {"key": "qwen", "label": "Qwen", "backend": "openai_compat",
                     "model": "qwen-plus", "base_url": "https://otro.example/v1",
                     "api_key_env": "QWEN_API_KEY", "say": ["qwen"]},
                ]
            if clave == "engine.default_model":
                return "ds"
            return super().get(clave, defecto)

    sw = EngineSwitch(CfgRoster(sandbox))
    ds, qw = sw.find("deepseek"), sw.find("qwen")
    check("el roster lee base_url por entrada", ds.base_url.endswith("deepseek.com/v1"))
    check("y api_key_env por entrada", ds.api_key_env == "DEEPSEEK_API_KEY")
    check("dos proveedores no comparten identidad", ds.provider_id != qw.provider_id)

    e_ds = sw._engine_for(ds.backend, ds)
    e_qw = sw._engine_for(qw.backend, qw)
    check("ni comparten adaptador", e_ds is not e_qw,
          "cachear por backend hacia que el segundo hablara con el endpoint del primero")
    check("cada adaptador apunta a lo suyo",
          e_ds.base.endswith("deepseek.com/v1") and e_qw.base.endswith("otro.example/v1"),
          f"{e_ds.base} | {e_qw.base}")
    check("y lleva su modelo", e_ds.model == "deepseek-chat" and e_qw.model == "qwen-plus")
    check("el mismo spec reusa adaptador", sw._engine_for(ds.backend, ds) is e_ds)

    # ══════════════════ RADIOS, BRILLO Y AVISOS ════════════════════
    print()
    print("  -- las radios no viven dentro de «media» --")
    pol_radio = Policy(FakeCfg(sandbox, allow_media=True, allow_radio=True,
                               allow_display=True, allow_notify=True))
    check("encender una radio no se confirma",
          pol_radio.can_control("radio").verdict is Verdict.ALLOW)
    check("apagarla si",
          pol_radio.can_control("radio", desconecta=True).verdict is Verdict.CONFIRM,
          "apagar el wifi deja sin red a la propia FRIDAY")
    pol_sin = Policy(FakeCfg(sandbox, allow_media=True))
    check("tener volumen no da bluetooth",
          pol_sin.can_control("media").verdict is Verdict.ALLOW
          and pol_sin.can_control("radio").verdict is Verdict.DENY,
          "el criterio de separacion es la consecuencia, no la comodidad")
    check("el brillo no desconecta de nada, asi que va suelto",
          pol_radio.can_control("display").verdict is Verdict.ALLOW)

    from system.win32.radios import normaliza_radio
    check("el STT parte los nombres compuestos y aun asi se reconocen",
          normaliza_radio("el blue tooth") == "bluetooth"
          and normaliza_radio("wi fi") == "wifi"
          and normaliza_radio("WLAN") == "wifi")
    check("una radio que no existe se queda desconocida",
          normaliza_radio("la impresora") == "",
          "tratarla como una cualquiera es apagar la que no era")

    print()
    print("  -- avisar fuera del equipo es su propio permiso --")
    from system.notify import HttpNotifier, build_notifier
    from system.ports import Notice

    check("poder leer la red no es poder escribir en ella",
          Policy(FakeCfg(sandbox, allow_web_fetch=True))
          .can_notify("https://ntfy.sh/x").verdict is Verdict.DENY,
          "la direccion del flujo es la diferencia")
    check("y con permiso pero sin destino tampoco",
          pol_radio.can_notify("").verdict is Verdict.DENY)
    check("un destino en tu red local no recibe avisos",
          pol_radio.can_notify("http://192.168.1.1/hook").verdict is Verdict.DENY,
          "hereda el guardia de can_fetch")
    check("un destino publico si",
          pol_radio.can_notify("https://ntfy.sh/tema").verdict is Verdict.ALLOW)

    avisador = HttpNotifier(pol_radio, kind="ntfy",
                            target="https://ntfy.sh/tema")
    _cuerpo, texto, cabeceras = avisador._payload(
        Notice(title="Revisión de sprint", body="En 10 minutos",
               urgencia="alta", tag="recordatorio"))
    check("ntfy manda el titulo por cabecera y el aviso por cuerpo",
          texto == "En 10 minutos" and bool(cabeceras.get("Title")),
          str(cabeceras))
    check("una cabecera con tildes no revienta el envio",
          all(ord(c) < 256 for c in cabeceras["Title"]),
          "las cabeceras HTTP van en latin-1")
    tg = HttpNotifier(pol_radio, kind="telegram", token_env="NO_EXISTE_TOKEN",
                      chat_id="42")
    check("sin token en el entorno, telegram no esta configurado",
          not tg.configurado and not tg.target)

    # Lo que no puede filtrarse es el VALOR del token, no el nombre de la
    # variable — ese es justo el dato que hay que enseñar cuando falta.
    import os as _os
    _os.environ["FRIDAY_TEST_TOKEN"] = "123456:secreto-que-no-sale"
    try:
        tg2 = HttpNotifier(pol_radio, kind="telegram",
                           token_env="FRIDAY_TEST_TOKEN", chat_id="42")
        check("con token, telegram queda listo", tg2.configurado)
        check("y el panel nunca enseña el token",
              "secreto-que-no-sale" not in tg2.describe(), tg2.describe())
        check("pero la URL real si lo lleva, y es la que ve la politica",
              "secreto-que-no-sale" in tg2.target,
              "can_notify tiene que autorizar lo que de verdad se va a pedir")
    finally:
        _os.environ.pop("FRIDAY_TEST_TOKEN", None)
    check("sin destino no hay puerto que ofrecer",
          build_notifier(FakeCfg(sandbox), pol_radio) is None,
          "una capacidad sin configurar no es una capacidad denegada")

    # ══════════════════ EQUIVOCARSE BARATO Y CARO NO ES IGUAL ══════
    print()
    print("  -- el enrutado es probabilistico; sus consecuencias no --")
    from core.router import OIDO_DUDOSO

    check("una skill declara que pasa si el enrutado falla",
          skills["archivos"].tiene_efecto and not skills["metricas"].tiene_efecto,
          "mover cuarenta archivos y leer la CPU no cuestan lo mismo")

    # El incidente del 17/08/2026, reproducido: el motor manda a `sistema`
    # una frase que no pide nada y cuyos disparadores puntuaron cero.
    class MotorTorcido(Engine):
        name = "torcido"

        async def complete(self, prompt, system="", **kw):
            return '{"skill": "sistema", "confidence": 0.85}'

    torcido = Router(real_cfg, vault, graph, MotorTorcido(real_cfg), skills,
                     system=access, policy=policy)
    larga = ("hoy me he levantado raro y llevo un rato dandole vueltas a lo "
             "mismo sin llegar a ninguna parte")
    ruta_mala = await torcido.decide(larga)
    check("una frase que no pide nada no acaba lanzando un programa",
          ruta_mala.skill == "none", f"{ruta_mala.skill} ({ruta_mala.how})")

    class MotorInerte(Engine):
        name = "inerte"

        async def complete(self, prompt, system="", **kw):
            return '{"skill": "metricas", "confidence": 0.85}'

    suave = Router(real_cfg, vault, graph, MotorInerte(real_cfg), skills,
                   system=access, policy=policy)
    ruta_ok = await suave.decide(larga)
    check("pero a una skill que solo lee se le deja pasar",
          ruta_ok.skill == "metricas",
          "equivocarse ahi cuesta una respuesta rara, no una tarde")

    ruta_corta = await router.decide("abre eso")
    check("una orden corta y clara sigue siendo instantanea",
          ruta_corta.how == "fast", f"{ruta_corta.skill} ({ruta_corta.how})")

    # -- el eco: repetir lo dudoso antes de actuar --
    _r, res_eco = await router.dispatch("busca el archivo zorglub", oido=0.3)
    check("con el oido dudoso, una orden con efecto se repite antes",
          res_eco.pending is not None and "Dijiste" in res_eco.speak,
          res_eco.speak)
    router.pending = None
    _r, res_claro = await router.dispatch("busca el archivo zorglub", oido=0.95)
    check("y con el oido claro no se pregunta nada",
          res_claro.pending is None, res_claro.speak[:60])
    router.pending = None
    _r, res_leer = await router.dispatch("dame las metricas", oido=0.1)
    check("una skill que solo lee no se repite ni con el peor oido",
          res_leer.pending is None,
          "confirmar de mas entrena a decir «si» sin escuchar")
    router.pending = None
    check("un turno escrito nunca pasa por el eco", OIDO_DUDOSO < 1.0)


    # ══════════════════ EL TALLER SE PUEDE MIRAR Y PARAR ═══════════
    print()
    print("  -- un encargo que dura minutos tiene que poder mirarse --")
    from skills.taller import Encargo, TallerSkill

    taller = skills["taller"]
    ctx_taller = SkillContext(cfg=real_cfg, vault=vault, graph=graph,
                              engine=FakeEngine(real_cfg), text="",
                              system=access, policy=policy)

    vacio = await taller.run(_con_texto(ctx_taller, "que encargos tienes"))
    check("sin nada en marcha lo dice, no se inventa un proyecto",
          "ningun encargo" in vacio.speak.lower(), vacio.speak)

    taller._encargos["e99"] = Encargo(ident="e99", proyecto="mi-proyecto",
                                      ruta=sandbox, tarea="revisar los tests",
                                      escribe=False)
    vivo = await taller.run(_con_texto(ctx_taller, "como va lo de mi-proyecto"))
    check("con uno corriendo, contesta por el",
          "mi-proyecto" in vivo.speak, vivo.speak)
    parado = await taller.run(_con_texto(ctx_taller, "dejalo"))
    check("y se puede parar sin confirmar",
          parado.data.get("cancelado") == "e99", parado.speak)
    check("cancelar no arma una confirmacion", parado.pending is None,
          "pedir un «si» para dejar de hacer algo es al reves que el resto")
    check("el encargo cancelado se recuerda un rato",
          taller._encargos["e99"].estado == "cancelado",
          "«como fue lo de X» tiene que poder contestarse despues")

    sugerencias = TallerSkill._sugerir("metete en mi proyeto",
                                       [("mi-proyecto", sandbox),
                                        ("otra-cosa", sandbox)])
    check("un nombre mal transcrito se OFRECE, no se elige",
          sugerencias[:1] == ["mi-proyecto"], str(sugerencias))
    check("y algo que no se parece a nada no se ofrece",
          TallerSkill._sugerir("metete en la cocina",
                               [("mi-proyecto", sandbox)]) == [],
          "proponer basura es peor que decir que no lo reconoces")

    # ══════════════════ UNA FRASE, DOS CAPACIDADES ════════════════
    print()
    print("  -- «busca el archivo informe y abrelo» --")
    from core.router import ACTION
    from skills.sistema import OPEN

    # El fallo de raiz: en español el pronombre se pega al imperativo, y con
    # el pronombre pegado el verbo lleva tilde. `\babre\b` no casa con
    # ninguna de las dos formas, que son las que de verdad dicta la gente.
    check("«abrelo» y «ábrelo» son ordenes, no continuacion de la charla",
          bool(ACTION.search("abrelo")) and bool(ACTION.search("ábrelo")),
          "sin esto se tomaban por conversacion y no abrian nada")
    check("y llegan a la rama de abrir",
          bool(OPEN.search("ábrelo")) and bool(OPEN.search("abrelo")))
    check("pero un gerundio no es una orden", not ACTION.search("abriendo"),
          "el enclitico no puede convertirse en comodin")

    partir = Router._partir
    check("una frase con dos peticiones se parte",
          partir("busca el archivo informe y abrelo")
          == ("busca el archivo informe", "abrelo"))
    check("se corta por el ULTIMO conector que valga",
          partir("busca el archivo de ventas y marketing y abrelo")
          == ("busca el archivo de ventas y marketing", "abrelo"),
          "el primer «y» estaba dentro del nombre")
    check("dos cosas buscadas NO son dos peticiones",
          partir("busca el archivo informe y el contrato") == ("", ""),
          "sin verbo detras del conector, no se parte")
    check("una orden simple se queda entera",
          partir("abre spotify") == ("", ""))
    check("y encadenar tiene tope de dos",
          partir("abrelo") == ("", ""),
          "esto no es un planificador y no debe parecerlo")

    # ── la cadena de verdad, con un lanzador espia ──
    cadena_caja = Path(tempfile.mkdtemp(prefix="friday_cadena_"))
    (cadena_caja / "informe anual.pdf").write_text("x", encoding="utf-8")
    (cadena_caja / "instalador nitro.exe").write_text("x", encoding="utf-8")

    pol_cadena = Policy(FakeCfg(cadena_caja))

    class LanzadorEspia:
        def __init__(self, policy):
            self.policy = policy
            self.abiertos: list[str] = []
            self.last_error = ""

        def launch(self, app, args=None):
            return True

        def open_path(self, ruta):
            decision = self.policy.can_open(Path(ruta))
            if not decision.allowed:
                self.last_error = decision.reason
                return False
            self.last_error = ""
            self.abiertos.append(Path(ruta).name)
            return True

    espia_cadena = LanzadorEspia(pol_cadena)
    acceso_cadena = SystemAccess(files=LocalFileIndex(pol_cadena),
                                 launcher=espia_cadena)
    router_cadena = Router(real_cfg, vault, graph, FakeEngine(real_cfg), skills,
                           system=acceso_cadena, policy=pol_cadena)

    async def _turno(frase):
        espia_cadena.abiertos.clear()
        ruta = await router_cadena.decide(frase)
        _r, res = await router_cadena.dispatch(frase, ruta)
        router_cadena.pending = None
        return res

    res_cad = await _turno("busca el archivo informe y abrelo")
    check("la primera mitad encuentra y la segunda abre",
          espia_cadena.abiertos == ["informe anual.pdf"],
          str(espia_cadena.abiertos))
    check("y se cuenta lo que se hizo, entero",
          "Abierto" in res_cad.speak and "coincidencias" in res_cad.speak,
          res_cad.speak)

    res_exe = await _turno("busca el archivo instalador y abrelo")
    check("un ejecutable encontrado por voz NO se abre",
          espia_cadena.abiertos == [],
          "abrirlo seria ejecucion arbitraria esquivando allow_shell")
    check("y se dice por que", "No pude abrir" in res_exe.speak, res_exe.speak)

    await _turno("busca el archivo zzzz y abrelo")
    check("sin resultado en la primera, no hay segunda",
          espia_cadena.abiertos == [],
          "abrir el resultado de una busqueda vacia es abrir cualquier cosa")

    res_aj = await _turno("busca el archivo informe y silencia el volumen")
    check("si la segunda no sabe consumir lo entregado, no corre",
          espia_cadena.abiertos == []
          and res_aj.data.get("cadena", {}).get("hecho") is False,
          str(res_aj.data.get("cadena")))
    check("pero la primera mitad si se hizo, y se dice",
          "Hice lo primero" in res_aj.display,
          "media tarea anunciada entera es peor que media tarea")

    check("abrir un archivo no es lanzar una app del catalogo",
          pol_cadena.can_open(cadena_caja / "x.exe").verdict is Verdict.DENY
          and pol_cadena.can_open(cadena_caja / "informe anual.pdf").verdict
          is Verdict.ALLOW,
          "can_launch recibe algo curado; can_open, lo que haya en tu disco")
    check("y un acceso directo tampoco, que apunta a donde quiera",
          pol_cadena.can_open(cadena_caja / "x.lnk").verdict is Verdict.DENY)
    check("fuera de tus raices no se abre nada",
          pol_cadena.can_open(Path("C:/Windows/notepad.pdf")).verdict
          is Verdict.DENY)

    shutil.rmtree(cadena_caja, ignore_errors=True)

    shutil.rmtree(sandbox, ignore_errors=True)
    shutil.rmtree(vault.root, ignore_errors=True)

    # ══════════════════ ANALISIS ESTATICO ══════════════════
    print("\n  ── nada de ventanas negras ──")
    huerfanos = _subprocess_sin_no_window()
    check("todo subprocess.* propio pasa creationflags=NO_WINDOW",
          not huerfanos, ", ".join(huerfanos))

    bad = [n for n, ok, _ in results if not ok]
    print(f"\n  {len(results) - len(bad)}/{len(results)} pruebas pasaron")
    if bad:
        print(f"  fallaron: {', '.join(bad)}\n")
        return 1
    print("  capa de sistema verde.\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
