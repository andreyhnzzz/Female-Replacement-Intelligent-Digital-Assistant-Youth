"""Adaptadores de motor.

FRIDAY no sabe quien piensa. Le pasa un prompt a un Engine y recibe texto.
Cambiar de Claude Code a un modelo local es cambiar UNA linea del toml.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
from abc import ABC, abstractmethod
from typing import Any

from .config import Config


# ---------------------------------------------------------------- base
class Engine(ABC):
    name = "base"

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.timeout = float(cfg.get("engine.timeout_s", 180))

    @abstractmethod
    async def complete(self, prompt: str, system: str = "", **kw: Any) -> str:
        ...

    async def health(self) -> tuple[bool, str]:
        return True, "ok"

    # -- helper compartido -------------------------------------------
    @staticmethod
    def extract_json(text: str) -> dict[str, Any] | None:
        """Saca el primer objeto JSON del texto, con o sin cerca de codigo."""
        if not text:
            return None
        fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
        candidates = [fence.group(1)] if fence else []
        start = text.find("{")
        if start != -1:
            depth, in_str, esc = 0, False, False
            for i, ch in enumerate(text[start:], start):
                if esc:
                    esc = False
                    continue
                if ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = not in_str
                elif not in_str:
                    if ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                        if depth == 0:
                            candidates.append(text[start:i + 1])
                            break
        for c in candidates:
            try:
                return json.loads(c)
            except json.JSONDecodeError:
                continue
        return None


# ------------------------------------------------------- Claude Code
class ClaudeCodeEngine(Engine):
    """Claude Code headless (`claude -p`) como motor.

    Dos modos, y la diferencia importa:

    - **razonamiento** (por defecto): `--tools ""` y `--system-prompt` propio.
      Sin herramientas, sin cwd agentico, sin ruido de git. Es un LLM puro que
      entra texto y saca texto. Los archivos los escribe FRIDAY en Python —
      por eso el motor no necesita tocar disco.

    - **agentico** (`agentic=True`): le devolvemos las herramientas y el cwd
      del proyecto. Para cuando de verdad quieres que trabaje en el repo.

    El prompt viaja por **stdin**, no por argv: en Windows el shim .CMD de npm
    destroza los argumentos largos con saltos de linea y comillas.
    """

    name = "claude_code"

    def __init__(self, cfg: Config):
        super().__init__(cfg)
        self.binary = cfg.get("engine.claude_code.binary", "claude")
        self.model = cfg.get("engine.claude_code.model", "claude-opus-5")
        self.perm = cfg.get("engine.claude_code.permission_mode", "acceptEdits")
        self.tools = cfg.get("engine.claude_code.allowed_tools", [])
        self.max_turns = int(cfg.get("engine.max_turns", 6))
        self.cwd = str(cfg.root)

    def _resolve_binary(self) -> list[str]:
        exe = shutil.which(self.binary) or shutil.which(f"{self.binary}.cmd")
        if exe:
            return [exe]
        # npm en Windows deja un .ps1 / .cmd; caemos a shell de npx si hace falta
        npx = shutil.which("npx") or shutil.which("npx.cmd")
        if npx:
            return [npx, "-y", "@anthropic-ai/claude-code"]
        raise RuntimeError("No encuentro el binario `claude` ni `npx` en el PATH.")

    BASE_SYSTEM = (
        "Eres un motor de razonamiento. Recibes una instruccion y devuelves "
        "EXACTAMENTE lo que te pide, sin preambulo, sin explicacion, sin ofrecer "
        "ayuda y sin cerca de codigo salvo que te la pidan. No tienes herramientas "
        "ni acceso a archivos: todo lo que necesitas esta en el mensaje. "
        "Nunca digas que no puedes escribir un archivo — no es tu trabajo."
    )

    async def complete(self, prompt: str, system: str = "", agentic: bool = False,
                       **kw: Any) -> str:
        argv = self._resolve_binary() + [
            "-p",
            "--output-format", "json",
            "--model", kw.get("model", self.model),
        ]

        if agentic:
            argv += ["--permission-mode", self.perm,
                     "--max-turns", str(kw.get("max_turns", self.max_turns))]
            if self.tools:
                argv += ["--allowed-tools", ",".join(self.tools)]
            if system:
                argv += ["--append-system-prompt", system]
        else:
            # motor puro: sin herramientas, sin contexto de repo
            argv += ["--tools", "",
                     "--exclude-dynamic-system-prompt-sections",
                     "--max-turns", "1",
                     "--system-prompt",
                     (self.BASE_SYSTEM + ("\n\n" + system if system else ""))]

        env = {**os.environ, "CLAUDE_CODE_NONINTERACTIVE": "1"}
        proc = await asyncio.create_subprocess_exec(
            *argv, cwd=self.cwd, env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(
                proc.communicate(input=prompt.encode("utf-8")), timeout=self.timeout)
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError(f"El motor no respondio en {self.timeout:.0f}s.")

        text = out.decode("utf-8", "replace").strip()
        if proc.returncode != 0 and not text:
            raise RuntimeError(err.decode("utf-8", "replace").strip()[:400] or "motor fallo")

        # `--output-format json` devuelve un sobre; el contenido va en .result
        try:
            env_json = json.loads(text)
            if isinstance(env_json, dict):
                return str(env_json.get("result") or env_json.get("text") or text)
        except json.JSONDecodeError:
            pass
        return text

    async def health(self) -> tuple[bool, str]:
        try:
            argv = self._resolve_binary() + ["--version"]
            proc = await asyncio.create_subprocess_exec(
                *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=20)
            return proc.returncode == 0, out.decode().strip() or "claude code"
        except Exception as exc:
            return False, str(exc)[:120]


# ------------------------------------------------------------ Ollama
class OllamaEngine(Engine):
    name = "ollama"

    def __init__(self, cfg: Config):
        super().__init__(cfg)
        self.host = cfg.get("engine.ollama.host", "http://127.0.0.1:11434").rstrip("/")
        self.model = cfg.get("engine.ollama.model", "llama3.1:8b")

    async def complete(self, prompt: str, system: str = "", **kw: Any) -> str:
        import aiohttp
        payload = {
            "model": kw.get("model", self.model),
            "prompt": prompt,
            "system": system,
            "stream": False,
            "options": {"temperature": kw.get("temperature", 0.3)},
        }
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.post(f"{self.host}/api/generate", json=payload) as r:
                r.raise_for_status()
                return (await r.json()).get("response", "")

    async def health(self) -> tuple[bool, str]:
        import aiohttp
        try:
            to = aiohttp.ClientTimeout(total=5)
            async with aiohttp.ClientSession(timeout=to) as s:
                async with s.get(f"{self.host}/api/tags") as r:
                    tags = await r.json()
            names = [m["name"] for m in tags.get("models", [])][:4]
            return True, ", ".join(names) or "ollama"
        except Exception as exc:
            return False, str(exc)[:120]


# --------------------------------------------- OpenAI-compatible local
class OpenAICompatEngine(Engine):
    """llama.cpp server, LM Studio, vLLM, text-generation-webui..."""

    name = "openai_compat"

    def __init__(self, cfg: Config):
        super().__init__(cfg)
        self.base = cfg.get("engine.openai_compat.base_url", "http://127.0.0.1:8080/v1").rstrip("/")
        self.model = cfg.get("engine.openai_compat.model", "local-model")
        self.key = cfg.get("engine.openai_compat.api_key", "not-needed")

    async def complete(self, prompt: str, system: str = "", **kw: Any) -> str:
        import aiohttp
        msgs = ([{"role": "system", "content": system}] if system else []) + \
               [{"role": "user", "content": prompt}]
        payload = {"model": kw.get("model", self.model), "messages": msgs,
                   "temperature": kw.get("temperature", 0.3), "stream": False}
        headers = {"Authorization": f"Bearer {self.key}"}
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as s:
            async with s.post(f"{self.base}/chat/completions", json=payload) as r:
                r.raise_for_status()
                data = await r.json()
        return data["choices"][0]["message"]["content"]

    async def health(self) -> tuple[bool, str]:
        import aiohttp
        try:
            to = aiohttp.ClientTimeout(total=5)
            async with aiohttp.ClientSession(timeout=to) as s:
                async with s.get(f"{self.base}/models") as r:
                    data = await r.json()
            return True, str(data.get("data", [{}])[0].get("id", "local"))
        except Exception as exc:
            return False, str(exc)[:120]


ENGINES = {
    "claude_code": ClaudeCodeEngine,
    "ollama": OllamaEngine,
    "openai_compat": OpenAICompatEngine,
}


def build_engine(cfg: Config) -> Engine:
    backend = cfg.get("engine.backend", "claude_code")
    if backend not in ENGINES:
        raise ValueError(f"Backend desconocido: {backend}. Opciones: {list(ENGINES)}")
    return ENGINES[backend](cfg)
