"""Adaptadores de motor. FRIDAY pasa un prompt y recibe texto.

  1. Adaptadores — Claude Code, API de Anthropic, Ollama y cualquier endpoint
     del dialecto OpenAI. Mismo contrato para todos.
  2. Roster — los modelos alcanzables y sus alias hablados. Vive en el toml.
  3. `EngineSwitch` — la fachada que sostienen router y skills, para que
     cambiar de modelo a media conversacion no invalide ninguna referencia.

Nada fuera de este archivo sabe que existe Claude (regla 3).
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import unicodedata
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from . import http
from .bus import BUS
from .config import Config
from .proc import NO_WINDOW


# ---------------------------------------------------------------- base
class Engine(ABC):
    name = "base"

    # ¿Sabe trabajar dentro de un repo, o solo entra texto y sale texto?
    # Es una capacidad, no una marca: deja preguntar «¿hay motor agentico?»
    # sin preguntar «¿eres Claude?» (regla 3).
    agentic_capable = False

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
    def _loosen(candidate: str) -> str:
        """Repara comas colgantes, comillas simples y literales de Python.

        Un 8B que eligio bien la accion no puede perder el turno por una
        coma. Solo se aplica si el `json.loads` estricto ya fallo.
        """
        s = re.sub(r",\s*([}\]])", r"\1", candidate)
        if '"' not in s and "'" in s:
            s = s.replace("'", '"')
        s = re.sub(r"(?<![\w\"'])(True|False|None)(?![\w\"'])",
                   lambda m: {"True": "true", "False": "false",
                              "None": "null"}[m.group(1)], s)
        return s

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
            for intento in (c, Engine._loosen(c)):
                try:
                    data = json.loads(intento)
                except json.JSONDecodeError:
                    continue
                if isinstance(data, dict):
                    return data
        return None


# ------------------------------------------------------- Claude Code
class ClaudeCodeEngine(Engine):
    """Claude Code headless (`claude -p`) como motor.

    Dos modos: **razonamiento** (por defecto) va sin herramientas ni cwd de
    repo —los archivos los escribe Python—, y **agentico** devuelve
    herramientas y cwd. Esos tres van por llamada y no por constructor:
    cada encargo elige su proyecto, y leer no lleva la misma caja que
    arreglar tests.

    El prompt viaja por stdin: en Windows el shim .CMD de npm destroza los
    argumentos largos. Cada llamada levanta un proceso de Node (~1-2 s fijos);
    si ese peaje sobra, `anthropic_api` va por HTTP.
    """

    name = "claude_code"
    agentic_capable = True

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
            "--model", kw.get("model") or self.model,
        ]

        cwd = self.cwd
        if agentic:
            perm = str(kw.get("permission_mode") or self.perm)
            # No se acepta ni pidiendolo desde el toml: a este motor lo dirige
            # un STT que se equivoca. Si algo necesita saltarse permisos, se
            # hace a mano en la terminal.
            if perm == "bypassPermissions":
                perm = "acceptEdits"
            tools = kw.get("tools") or self.tools

            argv += ["--permission-mode", perm,
                     "--max-turns", str(kw.get("max_turns", self.max_turns))]
            if tools:
                argv += ["--allowed-tools", ",".join(tools)]
            if system:
                argv += ["--append-system-prompt", system]
            cwd = str(kw.get("cwd") or self.cwd)
        else:
            # motor puro: sin herramientas, sin contexto de repo
            argv += ["--tools", "",
                     "--exclude-dynamic-system-prompt-sections",
                     "--max-turns", "1",
                     "--system-prompt",
                     (self.BASE_SYSTEM + ("\n\n" + system if system else ""))]

        env = {**os.environ, "CLAUDE_CODE_NONINTERACTIVE": "1"}
        proc = await asyncio.create_subprocess_exec(
            *argv, cwd=cwd, env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            creationflags=NO_WINDOW,      # sin consola: ver core/proc.py
        )
        # El tope viaja en la llamada: un encargo agentico puede tardar
        # minutos y un turno hablado no.
        timeout = float(kw.get("timeout") or self.timeout)
        try:
            out, err = await asyncio.wait_for(
                proc.communicate(input=prompt.encode("utf-8")), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError(f"El motor no respondio en {timeout:.0f}s.")

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
                *argv, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL, creationflags=NO_WINDOW)
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=20)
            return proc.returncode == 0, out.decode().strip() or "claude code"
        except Exception as exc:
            return False, str(exc)[:120]


# ------------------------------------------------- API de Anthropic
class AnthropicAPIEngine(Engine):
    """Claude por HTTP directo: 1-2 s menos por turno que `claude_code`, que
    levanta Node en cada llamada. A cambio necesita `ANTHROPIC_API_KEY` y
    factura por token. Conviven; el conmutador salta sin reiniciar."""

    name = "anthropic_api"
    ENDPOINT = "/v1/messages"
    VERSION = "2023-06-01"

    def __init__(self, cfg: Config):
        super().__init__(cfg)
        p = "engine.anthropic_api"
        self.base = str(cfg.get(f"{p}.base_url", "https://api.anthropic.com")).rstrip("/")
        self.model = cfg.get(f"{p}.model", "claude-opus-5")
        self.max_tokens = int(cfg.get(f"{p}.max_tokens", 2048))
        self.key_env = str(cfg.get(f"{p}.api_key_env", "ANTHROPIC_API_KEY"))
        self._key_inline = str(cfg.get(f"{p}.api_key", "") or "")

    @property
    def key(self) -> str:
        return self._key_inline or os.environ.get(self.key_env, "")

    async def complete(self, prompt: str, system: str = "", **kw: Any) -> str:
        import aiohttp

        if not self.key:
            raise RuntimeError(
                f"Sin clave: exporta {self.key_env} o pon api_key en el toml.")

        payload: dict[str, Any] = {
            "model": kw.get("model") or self.model,
            "max_tokens": int(kw.get("max_tokens", self.max_tokens)),
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            payload["system"] = system
        if "temperature" in kw:
            payload["temperature"] = float(kw["temperature"])

        headers = {"x-api-key": self.key, "anthropic-version": self.VERSION,
                   "content-type": "application/json"}
        # El tope viaja en la llamada (un encargo largo no dura lo que un
        # turno hablado); la sesion se comparte para no pagar TLS cada vez.
        timeout = aiohttp.ClientTimeout(total=float(kw.get("timeout") or self.timeout))
        s = await http.session()
        async with s.post(self.base + self.ENDPOINT, json=payload,
                          headers=headers, timeout=timeout) as r:
            if r.status >= 400:
                detail = (await r.text())[:300]
                raise RuntimeError(f"HTTP {r.status}: {detail}")
            data = await r.json()

        # content es una lista de bloques; nos quedamos con el texto
        return "".join(b.get("text", "") for b in data.get("content", [])
                       if b.get("type") == "text").strip()

    async def health(self) -> tuple[bool, str]:
        if not self.key:
            return False, f"falta {self.key_env}"
        import aiohttp
        try:
            headers = {"x-api-key": self.key, "anthropic-version": self.VERSION}
            to = aiohttp.ClientTimeout(total=10)
            s = await http.session()
            async with s.get(f"{self.base}/v1/models", headers=headers,
                             timeout=to) as r:
                if r.status >= 400:
                    return False, f"HTTP {r.status}"
                data = await r.json()
            ids = [m.get("id", "") for m in data.get("data", [])][:3]
            return True, ", ".join(i for i in ids if i) or "anthropic api"
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
        payload: dict[str, Any] = {
            "model": kw.get("model") or self.model,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "options": {"temperature": kw.get("temperature", 0.3)},
        }
        # Fuerza JSON en la decodificacion, y con esquema acota los valores:
        # gramatica en vez de buenos modales.
        if kw.get("json_schema"):
            payload["format"] = kw["json_schema"]
        elif kw.get("json_mode"):
            payload["format"] = "json"
        timeout = aiohttp.ClientTimeout(total=float(kw.get("timeout") or self.timeout))
        s = await http.session()
        async with s.post(f"{self.host}/api/generate", json=payload,
                          timeout=timeout) as r:
            r.raise_for_status()
            return (await r.json()).get("response", "")

    async def health(self) -> tuple[bool, str]:
        import aiohttp
        try:
            to = aiohttp.ClientTimeout(total=5)
            s = await http.session()
            async with s.get(f"{self.host}/api/tags", timeout=to) as r:
                tags = await r.json()
            names = [m["name"] for m in tags.get("models", [])][:4]
            return True, ", ".join(names) or "ollama"
        except Exception as exc:
            return False, str(exc)[:120]


# --------------------------------------------- OpenAI-compatible
class OpenAICompatEngine(Engine):
    """Cualquier endpoint con el contrato `/chat/completions`: llama.cpp, LM
    Studio, vLLM, OpenAI, Groq, OpenRouter, DeepSeek y la capa compatible de
    Gemini. Cambiar de proveedor es `base_url` + `api_key_env`; un adaptador
    por marca seria el mismo archivo cuatro veces."""

    name = "openai_compat"

    def __init__(self, cfg: Config):
        super().__init__(cfg)
        p = "engine.openai_compat"
        self.base = str(cfg.get(f"{p}.base_url", "http://127.0.0.1:8080/v1")).rstrip("/")
        self.model = cfg.get(f"{p}.model", "local-model")
        self.key_env = str(cfg.get(f"{p}.api_key_env", "") or "")
        self._key_inline = str(cfg.get(f"{p}.api_key", "not-needed") or "")

    @property
    def key(self) -> str:
        if self.key_env:
            return os.environ.get(self.key_env, "") or self._key_inline
        return self._key_inline

    async def complete(self, prompt: str, system: str = "", **kw: Any) -> str:
        import aiohttp
        msgs = ([{"role": "system", "content": system}] if system else []) + \
               [{"role": "user", "content": prompt}]
        payload: dict[str, Any] = {
            "model": kw.get("model") or self.model, "messages": msgs,
            "temperature": kw.get("temperature", 0.3), "stream": False}
        if kw.get("json_schema"):
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "respuesta", "strict": True,
                                "schema": kw["json_schema"]}}
        elif kw.get("json_mode"):
            payload["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {self.key}"}
        timeout = aiohttp.ClientTimeout(total=float(kw.get("timeout") or self.timeout))
        s = await http.session()
        async with s.post(f"{self.base}/chat/completions", json=payload,
                          headers=headers, timeout=timeout) as r:
            if r.status >= 400:
                raise RuntimeError(f"HTTP {r.status}: {(await r.text())[:300]}")
            data = await r.json()

        # Indexar a pelo aqui daba un KeyError crudo mientras los otros tres
        # adaptadores devuelven un RuntimeError con el motivo. El dialecto
        # «compatible» lo hablan seis proveedores y no todos igual de bien.
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(
                f"respuesta inesperada del endpoint: {str(data)[:200]}") from exc

    async def health(self) -> tuple[bool, str]:
        import aiohttp
        try:
            headers = {"Authorization": f"Bearer {self.key}"} if self.key else {}
            to = aiohttp.ClientTimeout(total=5)
            s = await http.session()
            async with s.get(f"{self.base}/models", headers=headers, timeout=to) as r:
                data = await r.json()
            return True, str(data.get("data", [{}])[0].get("id", "local"))
        except Exception as exc:
            return False, str(exc)[:120]


# ══════════════════════════════════════════ pedir JSON, sin rezar
# Seco a proposito: la persona da el tono, y un tono no cabe dentro de un
# JSON. Mandar 4 KB de caracter en una llamada que solo devuelve
# `{"accion": ...}` pone a un 8B a hablar en personaje.
JSON_SYSTEM = (
    "Devuelves UNICAMENTE un objeto JSON valido con las claves que te piden. "
    "Sin prosa antes ni despues, sin cerca de codigo, sin explicar nada, sin "
    "claves de mas. Si un dato no lo sabes, pon el valor vacio, pero devuelve "
    "el objeto completo."
)


def enum_schema(campos: dict[str, Any],
                requeridos: list[str] | None = None) -> dict[str, Any]:
    """Atajo para el esquema mas util: un objeto con claves acotadas.

        enum_schema({"accion": ["subir", "bajar"], "args": "object"},
                    requeridos=["accion"])

    Un valor lista se vuelve `enum`; una cadena, un tipo suelto.

    Cuidado con `requeridos`: un campo obligatorio no se piensa, se inventa
    (medido con `llama3.1:8b`). Exige lo que necesitas para actuar y deja
    opcional lo que solo es una señal.
    """
    props: dict[str, Any] = {}
    for clave, valor in campos.items():
        if isinstance(valor, (list, tuple)):
            props[clave] = {"type": "string", "enum": list(valor)}
        else:
            props[clave] = {"type": str(valor)}
    return {"type": "object", "properties": props,
            "required": list(campos) if requeridos is None else list(requeridos)}


async def ask_json(engine: "Engine", prompt: str, system: str = "",
                   schema: dict[str, Any] | None = None,
                   repair: bool = True) -> dict[str, Any] | None:
    """Pide un objeto JSON y devuelve el dict, o None.

    El unico sitio por el que pasa un contrato JSON, y concentra las cuatro
    cosas que lo hacen aguantar con un 8B: modo JSON del backend, `schema`
    (con `enum` el decodificador no PUEDE inventarse un nombre), temperatura
    0 y sin persona. Si aun asi no hubo JSON, una segunda pasada le devuelve
    su propia salida y le pide solo el objeto.

    El esquema es una pista, no una garantia — los backends que no lo
    soportan lo ignoran. La validacion de despues sigue mandando.
    """
    raw = await engine.complete(
        prompt,
        system=(JSON_SYSTEM + ("\n\n" + system if system else "")),
        json_mode=True, json_schema=schema, temperature=0.0)

    data = Engine.extract_json(raw)
    if data is not None or not repair or not (raw or "").strip():
        return data

    try:
        rescate = await engine.complete(
            "Extrae el objeto JSON que hay en este texto y devuelvelo solo, "
            "sin nada mas:\n\n" + raw[:2000],
            system=JSON_SYSTEM, json_mode=True, temperature=0.0)
    except Exception:
        return None
    return Engine.extract_json(rescate)


ENGINES: dict[str, type[Engine]] = {
    "claude_code": ClaudeCodeEngine,
    "anthropic_api": AnthropicAPIEngine,
    "ollama": OllamaEngine,
    "openai_compat": OpenAICompatEngine,
}


# ══════════════════════════════════════════════════ roster de modelos
def _fold(text: str) -> str:
    """Minusculas sin acentos: el STT rara vez acierta la tilde."""
    norm = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in norm if unicodedata.category(c) != "Mn")


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """Una entrada del catalogo: un modelo concreto y como pedirlo hablando."""
    key: str                      # identificador corto y estable
    label: str                    # como se muestra y se dice
    backend: str                  # cual adaptador lo atiende
    model: str                    # id que entiende ese backend
    say: tuple[str, ...] = ()     # alias hablados
    note: str = ""                # una linea para el panel

    @property
    def aliases(self) -> tuple[str, ...]:
        seen = {_fold(a) for a in self.say} | {_fold(self.key), _fold(self.label)}
        return tuple(sorted(seen, key=len, reverse=True))


DEFAULT_ROSTER: tuple[dict[str, Any], ...] = (
    {"key": "opus", "label": "Opus 5", "backend": "claude_code",
     "model": "claude-opus-5", "say": ["opus", "opus cinco", "el grande"],
     "note": "razonamiento profundo, el mas lento"},
    {"key": "sonnet", "label": "Sonnet 5", "backend": "claude_code",
     "model": "claude-sonnet-5", "say": ["sonnet", "soneto", "sonet"],
     "note": "equilibrio; el de diario"},
    {"key": "haiku", "label": "Haiku 4.5", "backend": "claude_code",
     "model": "claude-haiku-4-5-20251001", "say": ["haiku", "aiku", "el rapido"],
     "note": "respuesta inmediata"},
)


def resolve_model(roster: list[ModelSpec], spoken: str) -> ModelSpec | None:
    """Resuelve lo dicho a una entrada del roster: gana el alias mas largo.

    Sin esa regla «opus» y «opus cinco» empatan y decide el orden del toml.
    El limite de palabra evita que «haiku» se dispare con «haikus del vault».
    Funcion suelta porque el enrutado la necesita antes de que exista motor.
    """
    blob = _fold(spoken)
    best: tuple[int, ModelSpec] | None = None
    for spec in roster:
        for alias in spec.aliases:
            if not alias:
                continue
            if re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", blob):
                if best is None or len(alias) > best[0]:
                    best = (len(alias), spec)
                break
    return best[1] if best else None


def load_roster(cfg: Config) -> list[ModelSpec]:
    raw = cfg.get("engine.roster") or list(DEFAULT_ROSTER)
    out: list[ModelSpec] = []
    for item in raw:
        if not isinstance(item, dict) or not item.get("backend"):
            continue
        key = str(item.get("key") or item.get("model", "")).strip()
        if not key:
            continue
        out.append(ModelSpec(
            key=key,
            label=str(item.get("label", key)),
            backend=str(item["backend"]),
            model=str(item.get("model", "")),
            say=tuple(str(s) for s in item.get("say", [])),
            note=str(item.get("note", "")),
        ))
    return out


# ══════════════════════════════════════════════════ el conmutador
class EngineSwitch(Engine):
    """La fachada que todos sostienen: router y skills reciben ESTE objeto,
    nunca un adaptador concreto, asi que «cambia a Sonnet» solo mueve un
    campo de aqui dentro. Los adaptadores se construyen perezosamente y se
    cachean: tener Ollama en el roster no cuesta nada si no lo llamas."""

    def __init__(self, cfg: Config):
        super().__init__(cfg)
        self.roster = load_roster(cfg)
        self._cache: dict[str, Engine] = {}
        self._spec: ModelSpec | None = None
        self._fallback_backend = str(cfg.get("engine.backend", "claude_code"))
        self.history: list[str] = []

        wanted = str(cfg.get("engine.default_model", "") or "")
        self._spec = (self.find(wanted) if wanted else None) \
            or next((s for s in self.roster if s.backend == self._fallback_backend), None) \
            or (self.roster[0] if self.roster else None)

    # ── identidad ─────────────────────────────────────────────────
    @property
    def name(self) -> str:                    # type: ignore[override]
        return self._spec.backend if self._spec else self._fallback_backend

    @property
    def spec(self) -> ModelSpec | None:
        return self._spec

    @property
    def label(self) -> str:
        if self._spec is None:
            return self._fallback_backend
        return f"{self._spec.label} · {self._spec.backend}"

    @property
    def current(self) -> Engine:
        return self._engine_for(self.name)

    def _engine_for(self, backend: str) -> Engine:
        if backend not in ENGINES:
            raise ValueError(f"Backend desconocido: {backend}. Opciones: {list(ENGINES)}")
        if backend not in self._cache:
            self._cache[backend] = ENGINES[backend](self.cfg)
        return self._cache[backend]

    # ── catalogo ──────────────────────────────────────────────────
    def find(self, spoken: str) -> ModelSpec | None:
        return resolve_model(self.roster, spoken)

    def available(self) -> list[ModelSpec]:
        return list(self.roster)

    # ── capacidad agentica ────────────────────────────────────────
    @property
    def agentic_capable(self) -> bool:                # type: ignore[override]
        return bool(getattr(self.current, "agentic_capable", False))

    def agentic_spec(self) -> ModelSpec | None:
        """El activo si sabe trabajar en un repo; si no, el primero que sepa.

        Devuelve el spec en vez de conmutar: encargar una revision no puede
        cambiarte el modelo con el que estabas conversando.
        """
        if self._spec is not None and \
                getattr(ENGINES.get(self._spec.backend), "agentic_capable", False):
            return self._spec
        for spec in self.roster:
            if getattr(ENGINES.get(spec.backend), "agentic_capable", False):
                return spec
        return None

    async def complete_agentic(self, prompt: str, system: str = "",
                               spec: ModelSpec | None = None, **kw: Any) -> str:
        """Encargo dentro de un repo, con el modelo que sepa hacerlo."""
        spec = spec or self.agentic_spec()
        if spec is None:
            raise RuntimeError("Ningun modelo del roster sabe trabajar en un repo.")
        engine = self._engine_for(spec.backend)
        return await engine.complete(prompt, system=system, agentic=True,
                                     model=spec.model, **kw)

    # ── cambiar ───────────────────────────────────────────────────
    async def switch(self, spec: ModelSpec) -> tuple[bool, str]:
        """Cambia el modelo activo. No valida contra la red: eso lo hace la
        primera peticion real, y fallar ahi es mas informativo que aqui."""
        if spec.backend not in ENGINES:
            return False, f"no tengo adaptador para {spec.backend}"
        previous = self._spec
        if previous is not None and previous.key == spec.key:
            return True, f"ya estaba en {spec.label}"
        try:
            self._engine_for(spec.backend)          # construir revela config rota
        except Exception as exc:
            return False, str(exc)[:160]

        self._spec = spec
        self.history.append(spec.key)
        await BUS.emit("engine.switched", key=spec.key, label=spec.label,
                       backend=spec.backend, model=spec.model,
                       previous=previous.key if previous else "")
        return True, spec.label

    # ── contrato de Engine ────────────────────────────────────────
    async def complete(self, prompt: str, system: str = "", **kw: Any) -> str:
        engine = self.current
        if self._spec and self._spec.model and "model" not in kw:
            kw["model"] = self._spec.model
        return await engine.complete(prompt, system=system, **kw)

    async def health(self) -> tuple[bool, str]:
        try:
            ok, info = await self.current.health()
        except Exception as exc:
            return False, str(exc)[:120]
        return ok, f"{self.label} — {info}" if info else self.label

    def snapshot(self) -> dict[str, Any]:
        return {
            "backend": self.name,
            "key": self._spec.key if self._spec else "",
            "label": self._spec.label if self._spec else self._fallback_backend,
            "model": self._spec.model if self._spec else "",
            "roster": [s.key for s in self.roster],
        }


def build_engine(cfg: Config) -> EngineSwitch:
    backend = cfg.get("engine.backend", "claude_code")
    if backend not in ENGINES:
        raise ValueError(f"Backend desconocido: {backend}. Opciones: {list(ENGINES)}")
    return EngineSwitch(cfg)
