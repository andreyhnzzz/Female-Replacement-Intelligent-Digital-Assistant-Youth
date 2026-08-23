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

import asyncio
from dataclasses import dataclass
from urllib.parse import urljoin

from core.http import close, session   # noqa: F401 — reexportadas a proposito
from core.policy import Decision, Policy

DEFAULT_MAX_BYTES = 512 * 1024

# Los saltos se siguen a mano para poder autorizar cada uno; hay que ponerles
# tope o una cadena circular gira para siempre.
MAX_REDIRECTS = 5

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


async def authorize(url: str, policy: Policy) -> Decision:
    """El permiso completo de salida: el barato y el que consulta el DNS.

    `can_fetch` es puro y decide en microsegundos. `resolves_to_local` sale
    al DNS y bloquea, asi que va en un hilo — si no, una resolucion lenta
    congela el bucle de eventos justo cuando FRIDAY esta contestando.

    Los dos juntos aqui, y aqui solo, para que ninguna skill pueda quedarse
    con la mitad barata y saltarse la otra (regla 6).
    """
    decision = policy.can_fetch(url)
    if not decision.allowed:
        return decision
    return await asyncio.to_thread(policy.resolves_to_local, url)


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
    try:
        import aiohttp
    except ImportError:
        return Fetched(url, error="falta aiohttp (pip install aiohttp)")

    headers = {"User-Agent": ua or UA, "Accept": accept,
               "Accept-Language": "es-ES,es;q=0.9,en;q=0.6"}
    actual = url
    try:
        to = aiohttp.ClientTimeout(total=timeout_s)
        sesion = await session(timeout_s)
        for _ in range(MAX_REDIRECTS + 1):
            permiso = await authorize(actual, policy)
            if not permiso.allowed:
                extra = "" if actual == url else "redirigio a una URL bloqueada: "
                return Fetched(url, error=f"{extra}{permiso.reason}")

            # `allow_redirects=False` no es un detalle: con los saltos
            # automaticos, aiohttp YA pidio la URL interna antes de que
            # nadie pudiera mirarla. Descartar la respuesta despues no
            # deshace la peticion, y un GET al router ya tuvo su efecto.
            async with sesion.get(actual, headers=headers, timeout=to,
                                  allow_redirects=False) as r:
                if r.status in (301, 302, 303, 307, 308):
                    destino = r.headers.get("Location", "")
                    if not destino:
                        return Fetched(actual, status=r.status,
                                       error=f"HTTP {r.status} sin destino")
                    # `urljoin` resuelve el Location relativo («/otra») contra
                    # el que acabamos de pedir; absoluto lo deja igual.
                    actual = urljoin(actual, destino)
                    continue                    # el permiso se rehace arriba

                if r.status >= 400:
                    return Fetched(actual, status=r.status, error=f"HTTP {r.status}")

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
                return Fetched(actual, body=body, status=r.status,
                               truncated=truncated)

        return Fetched(url, error=f"demasiados saltos (mas de {MAX_REDIRECTS})")

    except Exception as exc:
        return Fetched(url, error=f"{type(exc).__name__}: {exc}"[:160])


async def post(url: str, policy: Policy, *, json: dict | None = None,
               data: str = "", headers: dict[str, str] | None = None,
               timeout_s: float = 10.0, ua: str = "") -> Fetched:
    """Manda algo a la red. El unico camino de salida con cuerpo.

    Tres diferencias con `fetch`, y las tres son la misma razon de fondo —
    esto **empuja datos**, no los trae:

    1. **No sigue redirecciones, ni una.** En un GET, seguir un salto
       autorizandolo antes es aceptable. En un POST el salto reenviaria el
       cuerpo a un destino que el usuario no escribio, y el cuerpo es
       precisamente lo que no queria publicar. Un 3xx aqui es un error, no
       un paso intermedio.
    2. **La autorizacion es la misma**, `authorize`, sin atajo: la red local
       tampoco recibe avisos.
    3. **Tampoco lanza.** La llaman notificadores en segundo plano; que no
       salga un aviso no puede tumbar el ciclo que lo mando.
    """
    try:
        import aiohttp
    except ImportError:
        return Fetched(url, error="falta aiohttp (pip install aiohttp)")

    permiso = await authorize(url, policy)
    if not permiso.allowed:
        return Fetched(url, error=permiso.reason)

    cabeceras = {"User-Agent": ua or UA}
    cabeceras.update(headers or {})

    try:
        to = aiohttp.ClientTimeout(total=timeout_s)
        sesion = await session(timeout_s)
        async with sesion.post(url, json=json, data=data or None,
                               headers=cabeceras, timeout=to,
                               allow_redirects=False) as r:
            cuerpo = (await r.text())[:2000]
            if r.status in (301, 302, 303, 307, 308):
                return Fetched(url, status=r.status,
                               error="el destino redirige; un aviso no se reenvia")
            if r.status >= 400:
                return Fetched(url, status=r.status,
                               error=f"HTTP {r.status}: {cuerpo[:120]}")
            return Fetched(url, body=cuerpo or "ok", status=r.status)
    except Exception as exc:
        return Fetched(url, error=f"{type(exc).__name__}: {exc}"[:160])
