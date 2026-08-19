"""La sesion HTTP compartida del proceso.

Existe por una sola razon, y es medible: una `ClientSession` por peticion es
un handshake TCP + TLS por peticion. Contra un endpoint remoto eso son
100-300 ms que se pagan **en cada turno hablado** que sale a la red, y el
adaptador `anthropic_api` existe precisamente para ahorrar ese orden de
latencia frente a levantar Node. Pagarlo por el otro lado anula la ventaja.

Vive en `core/` y no en `system/net.py` porque la usan los dos lados —el
motor y la capa de red— y `system` ya depende de `core`. Al reves seria un
ciclo.

No sabe nada de politica ni de audio: es una tuberia. Quien decide si una URL
se puede pedir es `core/policy.py`, y quien lo comprueba es `system/net.py`.
"""
from __future__ import annotations

import asyncio
from typing import Any

_SESSION: Any = None
_LOCK = asyncio.Lock()

# Un escritorio no necesita mas: son peticiones sueltas de skills, no un
# rastreador. Y el cache de DNS ahorra la resolucion en cada salto.
_LIMIT = 8
_DNS_TTL = 300


async def session(timeout_s: float = 30.0):
    """La sesion compartida, creada al primer uso dentro del bucle vivo.

    Perezosa a proposito: `aiohttp.ClientSession` se ata al bucle de eventos
    en el que nace, asi que no puede construirse al importar el modulo.
    """
    global _SESSION
    import aiohttp

    if _SESSION is not None and not _SESSION.closed:
        return _SESSION
    async with _LOCK:
        if _SESSION is None or _SESSION.closed:
            _SESSION = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=timeout_s),
                connector=aiohttp.TCPConnector(limit=_LIMIT, ttl_dns_cache=_DNS_TTL))
    return _SESSION


async def close() -> None:
    """Cierra la sesion. La llama `friday.py::shutdown`."""
    global _SESSION
    if _SESSION is not None and not _SESSION.closed:
        await _SESSION.close()
    _SESSION = None
