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

    def __init__(self, sandbox: Path):
        self.root = ROOT
        self._d = {
            "policy.enabled": True,
            "policy.allow_launch": True,
            "policy.allow_file_write": True,
            "policy.allow_shell": False,
            "policy.allow_web": True,
            "policy.confirm_over_files": 3,
            "policy.write_roots": [str(sandbox)],
            "policy.read_roots": [str(sandbox)],
            "policy.blocked_apps": ["regedit*", "cmd.exe"],
        }

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

    # ══════════════════ SKILLS Y CONFIRMACION ══════════════════
    print("\n  ── skills de sistema ──")
    real_cfg = load_config(ROOT / "config" / "friday.toml")
    vault = Vault(Path(tempfile.mkdtemp(prefix="friday_vault_")))
    graph = Graph(vault, ttl_s=0)
    skills = build_skills(real_cfg)
    router = Router(real_cfg, vault, graph, FakeEngine(real_cfg), skills,
                    system=access, policy=policy)

    check("las 8 skills cargan", len(skills) == 8, ", ".join(skills))

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
