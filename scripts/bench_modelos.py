"""Banco de modelos: ¿cuanto entiende cada uno del catalogo de `ordenador`?

    .\\.venv\\Scripts\\python scripts\\bench_modelos.py                 # el activo
    .\\.venv\\Scripts\\python scripts\\bench_modelos.py opus deepseek   # comparar
    .\\.venv\\Scripts\\python scripts\\bench_modelos.py --frases        # ver los casos

Por que existe: CLAUDE.md documenta que la eleccion de accion pasa de 6/12 a
12/12 con cuatro cambios de prompt, pero esos numeros se midieron a mano y no
quedo forma de repetirlos. Sin banco, cambiar de modelo — o de prompt — es
cambiar una corazonada por otra.

Dos decisiones que hacen que esto mida algo:

1. **Va por el `_decidir` de verdad**, no por una copia del prompt. Un banco
   que replica el prompt deja de medir el sistema en cuanto el prompt cambia,
   y encima no avisa: sigue dando numeros bonitos.
2. **Ninguna frase esta en los ejemplos del catalogo.** «esto suena altisimo»
   vive dentro del propio prompt: medir con ella mide memoria, no
   comprension. Todas las de aqui son formas que el catalogo NO ha visto,
   que es justo donde un 8B se cae y un modelo grande aguanta.

El caso `None` (ultimo) no es relleno: una skill con efecto que no reconoce
lo suyo tiene que decirlo, no elegir la accion mas parecida.
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import config as config_mod              # noqa: E402
from core import http                              # noqa: E402
from core.engine import build_engine               # noqa: E402
from skills.ordenador import CATALOGO, OrdenadorSkill   # noqa: E402

PASS, FAIL = "\033[92m ok \033[0m", "\033[91mFALLA\033[0m"

# (frase, accion esperada, comprobacion extra sobre args)
# `None` = se espera que NO actue.
CASOS: tuple[tuple[str, str | None, object], ...] = (
    ("no se oye practicamente nada", "volumen_cambiar",
     lambda a: _num(a.get("cuanto")) > 0),
    ("me esta reventando los oidos", "volumen_cambiar",
     lambda a: _num(a.get("cuanto")) < 0),
    ("subelo un pelin que se pierde", "volumen_cambiar",
     lambda a: _num(a.get("cuanto")) > 0),
    ("dejalo por la mitad mas o menos", "volumen_fijar", None),
    ("quitale el sonido del todo", "silenciar", None),
    ("esta cancion no la aguanto", "reproduccion", None),
    ("congela la musica un segundo", "reproduccion", None),
    ("necesito esto para pegarlo luego", "copiar", None),
    ("a ver que llevo copiado", "leer_portapapeles", None),
    ("me largo a comer, cierra el acceso", "bloquear", None),
    ("manda el equipo a dormir", "suspender", None),
    ("cuentame un chiste malo", None, None),
)


def _num(v: object) -> float:
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


async def medir(clave: str) -> tuple[int, int, float]:
    cfg = config_mod.load()
    motor = build_engine(cfg)
    spec = motor.find(clave)
    if spec is None:
        print(f"  «{clave}» no esta en el roster.")
        return 0, 0, 0.0
    ok, msg = await motor.switch(spec)
    if not ok:
        print(f"  no pude usar {clave}: {msg}")
        return 0, 0, 0.0

    skill = OrdenadorSkill(cfg)
    disponibles = list(CATALOGO)          # sin filtrar por puerto: mide al modelo
    print(f"\n  ── {spec.label} ({spec.backend}/{spec.model}) ──")

    aciertos, total_ms = 0, 0.0
    for frase, esperada, extra in CASOS:
        ctx = SimpleNamespace(text=frase, engine=motor, cfg=cfg,
                              vault=None, graph=None, system=None,
                              policy=None, slots={})
        t0 = time.time()
        try:
            propuesta = await skill._decidir(ctx, disponibles)   # el camino real
        except Exception as exc:
            propuesta, esperada_txt = None, f"reventó: {exc}"[:60]
            print(f"  [{FAIL}] {frase!r} — {esperada_txt}")
            total_ms += (time.time() - t0) * 1000
            continue
        ms = (time.time() - t0) * 1000
        total_ms += ms

        if esperada is None:
            bien = propuesta is None
            dio = "no actuo" if propuesta is None else propuesta[0].nombre
        elif propuesta is None:
            bien, dio = False, "no actuo"
        else:
            accion, args, _ = propuesta
            bien = accion.nombre == esperada
            if bien and extra is not None:
                bien = bool(extra(args))
                dio = f"{accion.nombre} {args}"
            else:
                dio = accion.nombre
        aciertos += bien
        quiere = esperada or "no actuar"
        print(f"  [{PASS if bien else FAIL}] {frase!r}\n"
              f"        quiere {quiere} · dio {dio} · {ms:.0f} ms")

    await http.close()
    return aciertos, len(CASOS), total_ms


async def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if "--frases" in sys.argv:
        for frase, esperada, _ in CASOS:
            print(f"  {frase!r} -> {esperada or 'no actuar'}")
        return 0

    if not args:
        motor = build_engine(config_mod.load())
        args = [motor.spec.key] if motor.spec else []
        await http.close()
    if not args:
        print("  roster vacio.")
        return 1

    marcador: list[tuple[str, int, int, float]] = []
    for clave in args:
        a, t, ms = await medir(clave)
        marcador.append((clave, a, t, ms))

    print("\n  ── marcador ──")
    for clave, a, t, ms in marcador:
        if not t:
            continue
        print(f"  {clave:<12} {a}/{t}   {ms / t:.0f} ms por caso")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
