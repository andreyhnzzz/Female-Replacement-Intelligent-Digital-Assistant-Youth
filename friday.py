#!/usr/bin/env python3
"""
F.R.I.D.A.Y — acompañante de escritorio.

No es una pagina web ni un servidor local: es una ventana del sistema, sin
marco, flotando sobre tu escritorio, con acceso real a la computadora.

    tu voz ─▶ PTT ─▶ STT local ─▶ Router ─▶ Skill ─┬─▶ vault/*.md
                                       │           ├─▶ sistema (apps, ventanas)
                                       │           ├─▶ archivos (buscar, ordenar)
                                       │           └─▶ pantalla (contexto)
                                       │
                                 Politica  ─── nada con efecto pasa sin permiso
                                       │
                            Acompañante (Qt/QML) ─▶ TTS local

Uso:
    python friday.py                 acompañante + voz
    python friday.py --no-voice      acompañante sin microfono
    python friday.py --console       sin ventana, solo terminal
    python friday.py --say "texto"   una peticion y sale
    python friday.py --check         diagnostico
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import privacy
from core.bus import BUS
from core.config import load as load_config
from core.engine import build_engine
from core.logbook import Logbook
from core.policy import Policy
from core.router import Router
from memory.graph import Graph
from memory.vault import Vault
from skills import build_skills
from system import build_system_access

BANNER = r"""
   ______ ____   ____ ____   ___ __   __
  / ____// __ \ /  _// __ \ /   |\ \ / /
 / /_   / /_/ / / / / / / // /| | \ V /
/ __/  / _, _/_/ / / /_/ // ___ |  | |
/_/    /_/ |_|/___//_____//_/  |_|  |_|
        acompañante de escritorio · memoria en markdown · voz local
"""


class Friday:
    """El nucleo. No sabe que existe una interfaz; habla por el bus."""

    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.cfg = load_config(args.config)
        self.bus = BUS

        self.vault = Vault(
            self.cfg.vault_root,
            raw=self.cfg.get("vault.raw", "raw"),
            wiki=self.cfg.get("vault.wiki", "wiki"),
            outputs=self.cfg.get("vault.outputs", "outputs"),
            daily_format=self.cfg.get("vault.daily_format", "%Y-%m-%d"),
        )
        self.graph = Graph(self.vault, ttl_s=float(self.cfg.get("vault.index_ttl_s", 3)))
        self.engine = build_engine(self.cfg)
        self.policy = Policy(self.cfg)
        self.system = build_system_access(self.cfg, self.policy)
        self.skills = build_skills(self.cfg)
        self.router = Router(self.cfg, self.vault, self.graph, self.engine,
                             self.skills, system=self.system, policy=self.policy)

        self.stt = None
        self.tts = None
        self.ptt = None
        self.status: dict[str, Any] = {
            "engine": self.engine.name, "engine_ok": False,
            "stt": "—", "stt_ok": False, "tts": "—", "tts_ok": False,
            "ptt_key": self.cfg.get("voice.ptt.key", "space"),
        }
        self._busy = asyncio.Lock()
        self._stop = asyncio.Event()
        self.loop: asyncio.AbstractEventLoop | None = None

    # ══════════════════════════════════════════ peticiones
    async def handle(self, text: str, source: str = "ui") -> None:
        text = (text or "").strip()
        if not text:
            return

        async with self._busy:
            if self.cfg.get("privacy.log_transcripts", True) and source == "voz":
                try:
                    self.vault.log(text, kind="voz")
                except Exception:
                    pass

            route = await self.router.decide(text)
            await self.bus.emit("router.decided", skill=route.skill, how=route.how,
                                confidence=route.confidence, text=text)

            if route.skill == "_mute" and self.tts:
                self.tts.muted = True
                self.tts.shutup()
                await self.bus.emit("core.info", message="voz silenciada")
                return
            if route.skill == "_unmute" and self.tts:
                self.tts.muted = False
                await self.bus.emit("core.info", message="voz activa")
                return

            _, res = await self.router.dispatch(text, route)

            await self.bus.emit(
                "skill.result", skill=route.skill, speak=res.speak,
                display=res.display, writes=res.writes, ok=res.ok,
                error=res.error, ms=res.data.get("_ms", 0),
                pending=res.data.get("_pending", ""))

            if not res.ok and res.error:
                await self.bus.emit("core.error", message=res.error[:300])

            if res.speak and self.tts:
                await self.bus.emit("tts.speaking", backend=self.tts.backend)
                self.tts.say(res.speak)
                await self.bus.emit("tts.done")

            if self.args.console or self.args.say:
                print(f"\n\033[38;5;214m{res.display or res.speak}\033[0m\n")

    # ══════════════════════════════════════════ voz
    def _on_utterance(self, audio, duration: float) -> None:
        """Corre en el hilo del PTT. Sella la red mientras transcribe."""
        try:
            with privacy.sealed():
                result = self.stt.transcribe(audio)
        except privacy.AudioLeak as leak:
            self.bus.emit_threadsafe("core.error", message=str(leak))
            return
        except Exception as exc:
            self.bus.emit_threadsafe("core.error", message=f"STT fallo: {exc}")
            return

        text = result.get("text", "").strip()
        self.bus.emit_threadsafe("voice.stt.final", text=text, duration=duration,
                                 **{k: v for k, v in result.items() if k != "text"})
        if text and self.loop:
            asyncio.run_coroutine_threadsafe(self.handle(text, source="voz"), self.loop)

    async def _start_voice(self) -> None:
        from voice.ptt import PushToTalk
        from voice.stt import LocalSTT
        from voice.tts import LocalTTS

        self.tts = LocalTTS(self.cfg)
        await asyncio.to_thread(self.tts.load)
        self.tts.start()
        self.status["tts"] = self.tts.backend
        self.status["tts_ok"] = self.tts.backend != "none"
        await self.bus.emit("core.info", message=f"voz: {self.tts.backend} ({self.tts.info})")

        self.stt = LocalSTT(self.cfg)
        allow_dl = self.args.allow_model_download

        def _load_stt() -> None:
            # el sello es por hilo: va DENTRO del worker o no protege nada
            if allow_dl:
                self.stt.load(allow_download=True)
            else:
                with privacy.sealed():
                    self.stt.load(allow_download=False)

        try:
            await asyncio.to_thread(_load_stt)
            self.status["stt"] = self.stt.info
            self.status["stt_ok"] = True
        except privacy.AudioLeak:
            self.status["stt"] = "modelo no descargado"
            await self.bus.emit("core.error", message=(
                "Falta descargar el modelo de voz una vez. "
                "Corre: python friday.py --allow-model-download"))
        except Exception as exc:
            self.status["stt"] = "error"
            await self.bus.emit("core.error", message=f"STT no cargo: {exc}")

        if self.status["stt_ok"]:
            await self.bus.emit("core.info", message=f"oidos: {self.status['stt']}")
            self.ptt = PushToTalk(self.cfg, self.bus)
            self.ptt.on_utterance = self._on_utterance
            await asyncio.to_thread(self.ptt.start)
            await self.bus.emit("core.info",
                                message=f"manten {self.ptt.key_name.upper()} y habla")

    # ══════════════════════════════════════════ latido
    async def _tick(self) -> None:
        interval = max(0.05, float(self.cfg.get("desktop.level_ms", 60)) / 1000)
        while not self._stop.is_set():
            if self.ptt and self.ptt.recording:
                await self.bus.emit("voice.level", level=self.ptt.level)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass

    # ══════════════════════════════════════════ arranque
    async def start(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        self.loop = loop or asyncio.get_running_loop()
        self.bus.bind_loop(self.loop)

        # Bitacora: sin esto, cuando algo no arranca no hay forma de saber
        # si fallo el modelo, el hotkey o el microfono.
        self.logbook = Logbook(self.bus, self.cfg.root / "logs" / "friday.log",
                               echo=bool(self.args.console or self.args.verbose))

        if self.cfg.get("privacy.local_only_audio", True):
            privacy.install(
                reporter=lambda m: self.bus.emit_threadsafe("core.error", message=m))

        ok, _info = await self.engine.health()
        self.status["engine_ok"] = ok
        await self.bus.emit("core.info",
                            message=f"motor {self.engine.name}: {'listo' if ok else 'caido'}")

        activas = [k for k, v in self.system.available().items() if v]
        await self.bus.emit("core.info",
                            message=f"acceso al sistema: {', '.join(activas) or 'ninguno'}")

        self._seed_vault()

        if self.cfg.get("voice.enabled", True) and not self.args.no_voice:
            await self._start_voice()

        asyncio.create_task(self._tick())
        await self.bus.emit("core.info", message="F.R.I.D.A.Y en linea.")

    def _seed_vault(self) -> None:
        readme = self.vault.root / "README.md"
        if readme.exists():
            return
        self.vault.write(readme,
            "# Vault de F.R.I.D.A.Y\n\n"
            "Todo aqui es markdown plano. Sin base de datos. Abrelo con Obsidian\n"
            "apuntando la boveda a esta carpeta y el grafo aparece solo.\n\n"
            "- `raw/` — captura cruda: notas diarias, transcripciones de voz\n"
            "- `wiki/` — notas atomicas enlazadas con [[wikilinks]]\n"
            "- `outputs/` — lo que FRIDAY produce: [[Agenda]], planes, briefings\n",
            meta={"type": "indice", "tags": ["meta"]})
        self.vault.write("wiki/Agenda.md",
            "# Agenda\n\nUna linea por evento. FRIDAY lee y escribe aqui.\n\n"
            "## Eventos\n"
            "- 2026-08-16 09:00 | Revisar el vault con FRIDAY | #sistema\n",
            meta={"type": "agenda", "tags": ["agenda"]})
        self.vault.daily()

    async def shutdown(self) -> None:
        self._stop.set()
        if self.ptt:
            self.ptt.stop()
        if self.tts:
            self.tts.shutup()
            self.tts.stop()


# ══════════════════════════════════════════════ modos de arranque
def run_companion(fri: Friday) -> int:
    """Modo normal: ventana flotante. Qt manda en el hilo principal."""
    from desktop import CompanionApp

    app = CompanionApp(fri.cfg, fri.bus, lambda t: fri.handle(t, source="ui"))

    async def core_main(loop: asyncio.AbstractEventLoop) -> None:
        try:
            await fri.start(loop)
        except Exception as exc:
            await fri.bus.emit("core.error", message=f"arranque fallido: {exc}")

    print(BANNER)
    print(f"  vault  : {fri.vault.root}")
    print(f"  motor  : {fri.engine.name}")
    print(f"  sistema: {', '.join(k for k, v in fri.system.available().items() if v)}")
    print("\n  El acompañante esta en tu escritorio. Cierra desde la bandeja.\n")

    code = app.run(core_main)
    asyncio.run(fri.shutdown())
    return code


async def run_console(fri: Friday) -> int:
    """Sin ventana: util para depurar y para equipos sin escritorio."""
    print(BANNER)
    await fri.start()

    if fri.args.say:
        await fri.handle(fri.args.say, source="cli")
        await asyncio.sleep(0.4)
        await fri.shutdown()
        return 0

    print("  Modo consola. Escribe, o Ctrl+C para salir.\n")
    loop = asyncio.get_running_loop()
    try:
        while True:
            line = await loop.run_in_executor(None, lambda: input("› "))
            if line.strip().lower() in ("salir", "exit", "quit"):
                break
            await fri.handle(line, source="consola")
    except (EOFError, KeyboardInterrupt):
        pass
    finally:
        await fri.shutdown()
    return 0


# ══════════════════════════════════════════════ diagnostico
async def check(cfg_path: str | None) -> int:
    cfg = load_config(cfg_path)
    print(BANNER)
    print("  DIAGNOSTICO\n")
    rows: list[tuple[str, bool, str, bool]] = []

    eng = build_engine(cfg)
    ok, info = await eng.health()
    rows.append((f"motor · {eng.name}", ok, info, True))

    for mod, label, req in [
        ("numpy", "numpy", True), ("psutil", "vitales", True),
        ("PySide6", "acompañante (Qt)", True),
        ("sounddevice", "audio i/o", False), ("pynput", "push-to-talk", False),
        ("faster_whisper", "STT local", False),
        ("win32gui", "ventanas (pywin32)", False),
    ]:
        try:
            __import__(mod)
            rows.append((label, True, mod, req))
        except ImportError:
            rows.append((label, False, f"pip install {mod}", req))

    try:
        import pyttsx3  # noqa: F401
        sapi = True
    except ImportError:
        sapi = False
    try:
        from piper.voice import PiperVoice  # noqa: F401
        piper = True
    except ImportError:
        piper = False
    rows.append(("TTS local", sapi or piper,
                 "piper" if piper else "sapi5" if sapi else "sin boca", False))

    policy = Policy(cfg)
    access = build_system_access(cfg, policy)
    for cap, on in access.available().items():
        rows.append((f"acceso · {cap}", on,
                     "disponible" if on else "no en esta plataforma", False))

    v = Vault(cfg.vault_root)
    st = v.stats()
    rows.append(("vault", True, f"{st['notes']} notas · {st['links']} enlaces", True))
    rows.append(("politica", True,
                 f"escribe en {len(policy.write_roots)} raices · "
                 f"confirma sobre {policy.confirm_over} archivos", True))

    width = max(len(r[0]) for r in rows) + 2
    for name, good, note, req in rows:
        mark = "\033[92m ok \033[0m" if good else \
               ("\033[91mfalta\033[0m" if req else "\033[93m -- \033[0m")
        print(f"  [{mark}] {name.ljust(width)} {note}")

    bad = [r[0] for r in rows if not r[1] and r[3]]
    print("\n  " + ("todo listo." if not bad else f"falta lo obligatorio: {', '.join(bad)}"))
    return 0 if not bad else 1


# ══════════════════════════════════════════════ entrada
def main() -> int:
    ap = argparse.ArgumentParser(prog="friday", description="F.R.I.D.A.Y")
    ap.add_argument("--config", default=None, help="ruta a friday.toml")
    ap.add_argument("--no-voice", action="store_true", help="sin STT/TTS/PTT")
    ap.add_argument("--console", action="store_true", help="sin ventana, solo terminal")
    ap.add_argument("--say", metavar="TEXTO", help="una peticion y sale")
    ap.add_argument("--check", action="store_true", help="diagnostico")
    ap.add_argument("--verbose", "-v", action="store_true",
                    help="vuelca la bitacora del bus a la consola")
    ap.add_argument("--allow-model-download", action="store_true",
                    help="permite bajar el modelo de voz la primera vez")
    args = ap.parse_args()

    if args.check:
        return asyncio.run(check(args.config))

    fri = Friday(args)

    if args.console or args.say:
        try:
            return asyncio.run(run_console(fri))
        except KeyboardInterrupt:
            print("\n  F.R.I.D.A.Y fuera de linea.\n")
            return 0

    return run_companion(fri)


if __name__ == "__main__":
    sys.exit(main())
