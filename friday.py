#!/usr/bin/env python3
"""
F.R.I.D.A.Y OS — orquestador.

    tu voz -> PTT -> STT local -> Router -> Skill -> Vault(markdown) -> TTS local
                                     |                                     |
                                     +------------- HUD --------------------+

Uso:
    python friday.py                # todo: voz + HUD
    python friday.py --no-voice     # solo HUD y texto
    python friday.py --no-hud       # solo consola
    python friday.py --say "texto"  # una peticion y sale
    python friday.py --check        # diagnostico
"""
from __future__ import annotations

import argparse
import asyncio
import signal
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import privacy
from core.bus import BUS
from core.config import load as load_config
from core.engine import build_engine
from core.router import Router
from memory.graph import Graph
from memory.vault import Vault
from skills import build_skills

BANNER = r"""
   ______ ____   ____ ____   ___ __   __
  / ____// __ \ /  _// __ \ /   |\ \ / /
 / /_   / /_/ / / / / / / // /| | \ V /
/ __/  / _, _/_/ / / /_/ // ___ |  | |
/_/    /_/ |_|/___//_____//_/  |_|  |_|   O S
        memoria en markdown · voz local · motor modular
"""

COMMANDS = [
    {"key": "SPACE", "label": "hablar (manten)", "send": ""},
    {"key": "metricas", "label": "jalar numeros", "send": "dame las metricas"},
    {"key": "inbox", "label": "resumen matutino", "send": "dame el resumen del dia"},
    {"key": "plan", "label": "escribir top 3", "send": "arma el plan de hoy"},
    {"key": "agenda", "label": "que viene", "send": "que tengo en la agenda"},
    {"key": "vault", "label": "buscar memoria", "send": "que sabes de "},
    {"key": "repite", "label": "repetir ultima", "send": "repite"},
    {"key": "heal", "label": "reparar grafo", "send": "reparar grafo"},
    {"key": "silencio", "label": "callar voz", "send": "silencio"},
]


class Friday:
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
        self.skills = build_skills(self.cfg)
        self.router = Router(self.cfg, self.vault, self.graph, self.engine, self.skills)

        self.stt = None
        self.tts = None
        self.ptt = None
        self.hud = None
        self.status: dict[str, Any] = {
            "engine": self.engine.name, "engine_ok": False,
            "stt": "—", "stt_ok": False, "tts": "—", "tts_ok": False,
            "ptt_key": self.cfg.get("voice.ptt.key", "space"),
        }
        self._busy = asyncio.Lock()
        self._stop = asyncio.Event()

    # ══════════════════════════════════════════ estado para el HUD
    def snapshot(self) -> dict[str, Any]:
        from skills.agenda import AgendaSkill
        from skills.base import SkillContext

        vitals = {}
        if "metricas" in self.skills:
            try:
                vitals = self.skills["metricas"].system_vitals()
            except Exception:
                pass

        agenda: list[dict] = []
        if "agenda" in self.skills:
            try:
                ctx = SkillContext(self.cfg, self.vault, self.graph, self.engine)
                now = datetime.now().timestamp()
                agenda = [e for e in self.skills["agenda"].collect(ctx)
                          if not e["done"] and e["ts"] > now - 86400][:10]
            except Exception:
                pass

        return {
            "status": self.status,
            "vitals": vitals,
            "vault": self.vault.stats(),
            "graph": self.graph.build().to_json(max_nodes=80),
            "agenda": agenda,
            "skills": self.router.catalog(),
            "commands": COMMANDS,
            "audio": {"recording": bool(self.ptt and self.ptt.recording),
                      "speaking": bool(self.tts and self.tts.speaking)},
        }

    # ══════════════════════════════════════════ ciclo principal
    async def handle(self, text: str, source: str = "hud") -> None:
        text = (text or "").strip()
        if not text:
            return
        if self._busy.locked():
            await self.bus.emit("core.info", message="ocupada, encolando…")

        async with self._busy:
            if self.cfg.get("privacy.log_transcripts", True) and source == "voz":
                try:
                    self.vault.log(text, kind="voz")
                except Exception:
                    pass

            route = await self.router.decide(text)
            await self.bus.emit("router.decided", skill=route.skill, how=route.how,
                                confidence=route.confidence, text=text)

            # comandos de voz sobre la propia voz
            if route.skill == "_mute" and self.tts:
                self.tts.muted = True
                self.tts.shutup()
                await self.bus.emit("core.info", message="voz silenciada")
                return
            if route.skill == "_unmute" and self.tts:
                self.tts.muted = False
                await self.bus.emit("core.info", message="voz activa")
                return
            if route.skill == "_cancel":
                if self.tts:
                    self.tts.shutup()
                await self.bus.emit("core.info", message="cancelado")
                return

            _, res = await self.router.dispatch(text, route)

            await self.bus.emit(
                "skill.result", skill=route.skill, speak=res.speak,
                display=res.display, writes=res.writes, ok=res.ok,
                error=res.error, ms=res.data.get("_ms", 0))

            if not res.ok and res.error:
                await self.bus.emit("core.error", message=res.error[:300])

            if res.speak and self.tts:
                await self.bus.emit("tts.speaking", backend=self.tts.backend)
                self.tts.say(res.speak)

            if not self.hud:
                print(f"\n\033[38;5;214m{res.display or res.speak}\033[0m\n")

    # ══════════════════════════════════════════ voz
    def _on_utterance(self, audio, duration: float) -> None:
        """Corre en hilo del PTT. Sella la red mientras transcribe."""
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
        if text:
            asyncio.run_coroutine_threadsafe(self.handle(text, source="voz"), self.loop)

    async def _start_voice(self) -> None:
        from voice.ptt import PushToTalk
        from voice.stt import LocalSTT
        from voice.tts import LocalTTS

        # --- TTS (rapido) ---
        self.tts = LocalTTS(self.cfg)
        await asyncio.to_thread(self.tts.load)
        self.tts.start()
        self.status["tts"] = f"{self.tts.backend}"
        self.status["tts_ok"] = self.tts.backend != "none"
        await self.bus.emit("core.info",
                            message=f"tts: {self.tts.backend} ({self.tts.info})")

        # --- STT (lento: modelo) ---
        self.stt = LocalSTT(self.cfg)
        self.status["stt"] = f"cargando {self.stt.model_name}…"

        allow_dl = self.args.allow_model_download

        def _load_stt() -> None:
            # El sello es por hilo: hay que ponerlo AQUI, dentro del worker,
            # no alrededor de to_thread. Si no, no protege nada.
            if allow_dl:
                self.stt.load()
            else:
                with privacy.sealed():
                    self.stt.load()

        try:
            await asyncio.to_thread(_load_stt)
            self.status["stt"] = self.stt.info
            self.status["stt_ok"] = True
        except privacy.AudioLeak:
            self.status["stt"] = "modelo no descargado"
            await self.bus.emit("core.error", message=(
                "El modelo de Whisper no esta en cache y hace falta descargarlo una vez. "
                "Corre: python friday.py --allow-model-download"))
        except Exception as exc:
            self.status["stt"] = "error"
            await self.bus.emit("core.error", message=f"STT no cargo: {exc}")
        await self.bus.emit("core.info", message=f"stt: {self.status['stt']}")

        # --- PTT ---
        if self.status["stt_ok"]:
            self.ptt = PushToTalk(self.cfg, self.bus)
            self.ptt.on_utterance = self._on_utterance
            await asyncio.to_thread(self.ptt.start)
            await self.bus.emit("core.info",
                                message=f"push-to-talk armado: {self.ptt.key_name} ({self.ptt.mode})")

    # ══════════════════════════════════════════ latido
    async def _tick(self) -> None:
        interval = max(0.5, float(self.cfg.get("hud.refresh_ms", 1000)) / 1000)
        while not self._stop.is_set():
            try:
                if self.ptt and self.ptt.recording:
                    await self.bus.emit("voice.level", level=self.ptt.level)
                elif self.hud and self.hud.clients:
                    await self.bus.emit("core.tick")
            except Exception:
                pass
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass

    # ══════════════════════════════════════════ arranque
    async def run(self) -> None:
        self.loop = asyncio.get_running_loop()
        self.bus.bind_loop(self.loop)

        if self.cfg.get("privacy.local_only_audio", True):
            privacy.install(reporter=lambda m: self.bus.emit_threadsafe("core.error", message=m))

        print(BANNER)
        print(f"  vault  : {self.vault.root}")
        print(f"  motor  : {self.engine.name}")

        ok, info = await self.engine.health()
        self.status["engine_ok"] = ok
        self.status["engine"] = f"{self.engine.name}" + ("" if ok else " ✗")
        print(f"  estado : {'ok' if ok else 'CAIDO'} — {info}\n")

        self._seed_vault()

        if self.cfg.get("hud.enabled", True) and not self.args.no_hud:
            from hud.server import HUDServer
            self.hud = HUDServer(self.cfg, self.bus, self.snapshot,
                                 lambda t: self.handle(t, source="hud"))
            url = await self.hud.start()
            print(f"  HUD    : {url}\n")

        if self.cfg.get("voice.enabled", True) and not self.args.no_voice:
            await self._start_voice()
        else:
            print("  voz    : deshabilitada\n")

        if self.args.say:
            await self.handle(self.args.say, source="cli")
            await asyncio.sleep(1.0)
            return

        asyncio.create_task(self._tick())
        await self.bus.emit("core.info", message="F.R.I.D.A.Y en linea.")

        if self.ptt:
            print(f"  Manten {self.ptt.key_name.upper()} y habla. Ctrl+C para salir.\n")
        else:
            print("  Escribe en el HUD. Ctrl+C para salir.\n")

        await self._stop.wait()

    def _seed_vault(self) -> None:
        """Primera vez: deja el vault utilizable, no vacio."""
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
        if self.hud:
            await self.hud.stop()


# ══════════════════════════════════════════════ diagnostico
async def check(cfg_path: str | None) -> int:
    cfg = load_config(cfg_path)
    print(BANNER)
    print("  DIAGNOSTICO\n")
    # (etiqueta, ok, nota, obligatorio)
    rows: list[tuple[str, bool, str, bool]] = []

    eng = build_engine(cfg)
    ok, info = await eng.health()
    rows.append((f"motor · {eng.name}", ok, info, True))

    for mod, label in [("numpy", "numpy"), ("sounddevice", "audio i/o"),
                       ("pynput", "push-to-talk"), ("faster_whisper", "STT local"),
                       ("aiohttp", "HUD"), ("psutil", "vitales")]:
        try:
            __import__(mod)
            rows.append((label, True, mod, True))
        except ImportError:
            rows.append((label, False, f"falta: pip install {mod}", True))

    # TTS: basta con UNO de los dos. Ambos son locales.
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
    rows.append(("TTS SAPI5", sapi, "pyttsx3 (voces de Windows)", False))
    rows.append(("TTS piper", piper, "opcional: pip install piper-tts", False))
    rows.append(("TTS (alguno)", sapi or piper,
                 "piper" if piper else "sapi5" if sapi else "sin boca", True))

    v = Vault(cfg.vault_root)
    st = v.stats()
    rows.append(("vault", True, f"{st['notes']} notas · {st['links']} enlaces · {v.root}", True))

    try:
        import sounddevice as sd
        din = sd.query_devices(kind="input")
        name = str(din.get("name", "?"))
        virtual = any(k in name.lower() for k in ("voicemod", "cable", "virtual", "vb-audio"))
        rows.append(("microfono", True,
                     name[:46] + ("  ← virtual, revisa que capte tu voz" if virtual else ""),
                     True))
    except Exception as exc:
        rows.append(("microfono", False, str(exc)[:52], True))

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
    ap = argparse.ArgumentParser(prog="friday", description="F.R.I.D.A.Y OS")
    ap.add_argument("--config", default=None, help="ruta a friday.toml")
    ap.add_argument("--no-voice", action="store_true", help="sin STT/TTS/PTT")
    ap.add_argument("--no-hud", action="store_true", help="sin interfaz")
    ap.add_argument("--say", metavar="TEXTO", help="una peticion y sale")
    ap.add_argument("--check", action="store_true", help="diagnostico de dependencias")
    ap.add_argument("--allow-model-download", action="store_true",
                    help="permite bajar el modelo de Whisper la primera vez")
    args = ap.parse_args()

    if args.check:
        return asyncio.run(check(args.config))

    fri = Friday(args)

    async def go() -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, lambda: fri._stop.set())
            except NotImplementedError:
                pass          # Windows: KeyboardInterrupt se encarga
        try:
            await fri.run()
        finally:
            await fri.shutdown()

    try:
        asyncio.run(go())
    except KeyboardInterrupt:
        print("\n  FRIDAY fuera de linea.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
