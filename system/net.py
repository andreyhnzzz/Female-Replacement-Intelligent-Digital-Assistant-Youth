"""Salida a la red. El unico lugar del proyecto que hace peticiones HTTP.

Tres razones para que este centralizado:

1. **La politica se aplica una vez.** `can_fetch` se consulta aqui, asi que
   ninguna implementacion puede saltarsela por olvido.
2. **El tamano esta acotado.** Se lee por trozos y se corta: un feed roto que
   devuelva un gigabyte no se lleva la memoria por delante.
3. **No compite con el audio.** `core/privacy.py` revienta las conexiones
   no-loopback mientras el pipeline de voz esta sellado. Eso es deliberado:
   si una descarga cae justo durante una transcripcion, falla — y falla
   ruidosamente, que es exactamente lo que el candado promete.

Nada de esto vive en `voice/`. El audio no habla con la red, nunca.
"""
from __future__ import annotations

from dataclasses import dataclass

from core.policy import Policy

DEFAULT_MAX_BYTES = 512 * 1024

# Contacto por defecto. Cambialo en `[system] contact` por el tuyo.
DEFAULT_CONTACT = "https://github.com/topics/friday-desktop-companion"


def user_agent(contact: str = "") -> str:
    """Cadena de identificacion. El contacto **no es opcional**.

    Comprobado contra Wikimedia, que es el caso mas estricto que toca este
    proyecto: su politica de robots devuelve **403 a todo** —API REST,
    action API, todo— si el User-Agent no incluye una forma de contacto entre
    parentesis. Y fingir ser Chrome no ayuda: esas cadenas estan bloqueadas
    explicitamente, asi que la opcion «disfrazarse» es la que menos funciona.

    Con un contacto dentro, las mismas peticiones devuelven 200.

    El otro motivo es el evidente: si FRIDAY llega a molestar a un servidor,
    quien mire el registro tiene a quien escribir en vez de tener que bloquear
    a ciegas.
    """
    who = (contact or DEFAULT_CONTACT).strip()
    return f"FRIDAY-desktop-companion/1.0 ({who}) python-aiohttp"


UA = user_agent()


@dataclass(frozen=True, slots=True)
class Fetched:
    """Resultado de una descarga. `error` vacio = salio bien."""
    url: str
    body: str = ""
    status: int = 0
    error: str = ""
    truncated: bool = False

    @property
    def ok(self) -> bool:
        return not self.error and bool(self.body)


async def fetch(url: str, policy: Policy, *, timeout_s: float = 12.0,
                max_bytes: int = DEFAULT_MAX_BYTES,
                accept: str = "text/html,application/xhtml+xml,application/xml",
                ua: str = "") -> Fetched:
    """Descarga una URL como texto. Nunca lanza: devuelve el error dentro.

    Que no lance es intencional. Esto lo llaman skills que estan a mitad de
    una respuesta hablada; una excepcion de red no debe convertirse en
    «la skill noticias fallo» cuando lo util es decir que feed no contesto.
    """
    decision = policy.can_fetch(url)
    if not decision.allowed:
        return Fetched(url, error=decision.reason)

    try:
        import aiohttp
    except ImportError:
        return Fetched(url, error="falta aiohttp (pip install aiohttp)")

    headers = {"User-Agent": ua or UA, "Accept": accept,
               "Accept-Language": "es-ES,es;q=0.9,en;q=0.6"}
    try:
        to = aiohttp.ClientTimeout(total=timeout_s)
        async with aiohttp.ClientSession(timeout=to, headers=headers) as s:
            async with s.get(url, allow_redirects=True) as r:
                if r.status >= 400:
                    return Fetched(url, status=r.status, error=f"HTTP {r.status}")

                # Redirigir a red local esquivaria can_fetch: se revalida el
                # destino final, no solo el que pedimos.
                final = str(r.url)
                if final != url:
                    again = policy.can_fetch(final)
                    if not again.allowed:
                        return Fetched(url, status=r.status,
                                       error=f"redirigio a {again.reason}")

                chunks: list[bytes] = []
                total = 0
                truncated = False
                async for block in r.content.iter_chunked(16384):
                    chunks.append(block)
                    total += len(block)
                    if total >= max_bytes:
                        truncated = True
                        break

                raw = b"".join(chunks)
                enc = r.charset or "utf-8"
                try:
                    body = raw.decode(enc, "replace")
                except (LookupError, TypeError):
                    body = raw.decode("utf-8", "replace")
                return Fetched(final, body=body, status=r.status, truncated=truncated)

    except Exception as exc:
        return Fetched(url, error=f"{type(exc).__name__}: {exc}"[:160])
