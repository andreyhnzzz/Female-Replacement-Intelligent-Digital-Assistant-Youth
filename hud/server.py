"""Servidor del HUD: estaticos + websocket.

Escucha solo en loopback. El HUD es una ventana a este proceso, no un servicio.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from aiohttp import WSMsgType, web

from core.bus import Bus, Event

WEB = Path(__file__).parent / "web"


class HUDServer:
    def __init__(self, cfg, bus: Bus, state_provider, command_sink):
        self.cfg = cfg
        self.bus = bus
        self.host = cfg.get("hud.host", "127.0.0.1")
        self.port = int(cfg.get("hud.port", 8787))
        self.state_provider = state_provider      # () -> dict
        self.command_sink = command_sink          # async (str) -> None
        self.clients: set[web.WebSocketResponse] = set()
        self.app = web.Application()
        self.runner: web.AppRunner | None = None
        self._routes()
        bus.on("*", self._relay)

    def _routes(self) -> None:
        self.app.add_routes([
            web.get("/", self.index),
            web.get("/ws", self.ws),
            web.get("/api/state", self.api_state),
            web.static("/static", WEB),
        ])

    # -- handlers ------------------------------------------------------
    async def index(self, _req: web.Request) -> web.StreamResponse:
        html = (WEB / "index.html").read_text(encoding="utf-8")
        html = html.replace("{{THEME}}", self.cfg.get("hud.theme", "amber")) \
                   .replace("{{NAME}}", self.cfg.get("identity.name", "F.R.I.D.A.Y"))

        # cache-busting por mtime: editas el css y lo ves, sin ctrl+shift+R
        for asset in ("hud.css", "hud.js"):
            f = WEB / asset
            stamp = int(f.stat().st_mtime) if f.exists() else 0
            html = html.replace(f"/static/{asset}", f"/static/{asset}?v={stamp}")

        return web.Response(text=html, content_type="text/html",
                            headers={"Cache-Control": "no-store"})

    async def api_state(self, _req: web.Request) -> web.Response:
        return web.json_response(self.state_provider())

    async def ws(self, req: web.Request) -> web.WebSocketResponse:
        wsr = web.WebSocketResponse(heartbeat=25)
        await wsr.prepare(req)
        self.clients.add(wsr)
        await wsr.send_json({"topic": "hud.hello", **self.state_provider()})
        try:
            async for msg in wsr:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    payload = json.loads(msg.data)
                except json.JSONDecodeError:
                    continue
                kind = payload.get("type")
                if kind == "command":
                    await self.command_sink(str(payload.get("text", "")))
                elif kind == "ping":
                    await wsr.send_json({"topic": "hud.state", **self.state_provider()})
        finally:
            self.clients.discard(wsr)
        return wsr

    # -- difusion ------------------------------------------------------
    async def _relay(self, ev: Event) -> None:
        if not self.clients:
            return
        payload = ev.as_json()
        if ev.topic in ("core.tick", "voice.level"):
            payload.update(self.state_provider())
        dead = []
        for c in self.clients:
            try:
                await c.send_json(payload)
            except Exception:
                dead.append(c)
        for c in dead:
            self.clients.discard(c)

    async def broadcast(self, topic: str, **data: Any) -> None:
        await self._relay(Event(topic, data))

    # -- ciclo de vida ---------------------------------------------------
    async def start(self) -> str:
        self.runner = web.AppRunner(self.app, access_log=None)
        await self.runner.setup()
        site = web.TCPSite(self.runner, self.host, self.port)
        await site.start()
        url = f"http://{self.host}:{self.port}"
        if self.cfg.get("hud.autolaunch", True):
            self._launch(url)
        return url

    async def stop(self) -> None:
        for c in list(self.clients):
            await c.close()
        if self.runner:
            await self.runner.cleanup()

    def _launch(self, url: str) -> None:
        """Ventana de app sin barra de navegador. Una pantalla, sin pestanas."""
        kiosk = self.cfg.get("hud.kiosk", True)
        if sys.platform == "win32" and kiosk:
            candidates = [
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            ]
            for exe in candidates:
                if Path(exe).exists():
                    try:
                        subprocess.Popen(
                            [exe, f"--app={url}", "--window-size=1500,940",
                             "--disable-features=TranslateUI"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        return
                    except OSError:
                        continue
        import webbrowser
        webbrowser.open(url)
