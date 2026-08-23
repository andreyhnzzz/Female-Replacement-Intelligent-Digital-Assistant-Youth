"""Radios (Bluetooth, wifi) y brillo de pantalla en Windows.

Implementa `RadioControl` y `DisplayControl`. Ninguna skill importa este
archivo: hablan con los Protocol de `system/ports.py`.

    -- Por que hay un hilo dedicado aqui --

Las dos APIs que hacen falta tienen **afinidad de hilo**, y no de la misma
forma:

- **WinRT** (`Windows.Devices.Radios`) devuelve `IAsyncOperation`. Para
  esperarlo hace falta un bucle de eventos, y no puede ser el de FRIDAY: la
  llamada tarda cientos de milisegundos y el bucle esta atendiendo el turno.
- **WMI por COM** (`WmiMonitorBrightnessMethods`) exige `CoInitialize` en el
  hilo que lo usa. Construirlo en uno y llamarlo desde otro no da error:
  cuelga. Eso ya nos costo una sesion entera de voz muda en `voice/tts.py`.

Un unico hilo con COM inicializado atiende las dos, y los puertos siguen
siendo **sincronos** como el resto de los locales: quien llama espera con
tope, y si el tope vence se dice, no se miente.

    -- Que necesita estar instalado --

El brillo va por `pywin32`, que ya es dependencia. Las radios necesitan las
proyecciones WinRT (`winsdk` o `winrt`), que **no** lo son: sin ellas el
puerto queda en None y `friday.py --check` lo dice. Preferimos eso a fingir
la capacidad, y a la alternativa —`netsh` con privilegios— que convertiria
subir el Bluetooth en ejecucion de shell (regla 6).
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import threading
from typing import Any, Callable

from core.lang import slug_words
from core.policy import Policy
from system.ports import RadioState

# Tope de espera de una operacion del hilo de dispositivos. Generoso porque
# encender una radio tarda de verdad; acotado porque un turno hablado que se
# queda esperando a la pila Bluetooth es un turno perdido.
_TIMEOUT_S = 6.0

_ALIAS = {
    "bluetooth": "bluetooth", "bt": "bluetooth", "blue tooth": "bluetooth",
    "wifi": "wifi", "wi fi": "wifi", "wlan": "wifi",
    "red inalambrica": "wifi", "inalambrica": "wifi",
}


def normaliza_radio(kind: str) -> str:
    """«el blue tooth», «wi fi» y «la red inalambrica» son `bluetooth` o `wifi`.

    El STT parte los nombres compuestos casi siempre, asi que el alias se
    busca **dentro** de la frase y no como cadena entera: el motor entrega
    `{"radio": "el blue tooth"}` mas veces de las que entrega `"bluetooth"`.

    Se prueban de mas largo a mas corto para que «wi fi» gane a un «bt» que
    apareciera de refilon, y siempre con frontera de palabra: un `kind`
    desconocido tiene que quedarse desconocido, porque tratarlo como una
    radio cualquiera es apagar la que no era.
    """
    plano = f" {slug_words(kind)} "
    for alias in sorted(_ALIAS, key=len, reverse=True):
        if f" {alias} " in plano:
            return _ALIAS[alias]
    return ""


# ============================================== el hilo de dispositivos
class _Dispositivos:
    """Un hilo, COM inicializado, cola de trabajos. Perezoso: si nadie toca
    una radio ni el brillo, este hilo no llega a existir."""

    def __init__(self) -> None:
        self._pool: concurrent.futures.ThreadPoolExecutor | None = None
        self._lock = threading.Lock()

    def _arranca(self) -> concurrent.futures.ThreadPoolExecutor:
        with self._lock:
            if self._pool is None:
                self._pool = concurrent.futures.ThreadPoolExecutor(
                    max_workers=1, thread_name_prefix="devices")
                self._pool.submit(_co_initialize).result(timeout=5)
            return self._pool

    def run(self, fn: Callable[[], Any], timeout: float = _TIMEOUT_S) -> Any:
        """Ejecuta `fn` en el hilo de dispositivos. Lanza si vence el tope."""
        return self._arranca().submit(fn).result(timeout=timeout)

    def cierra(self) -> None:
        with self._lock:
            if self._pool is not None:
                self._pool.shutdown(wait=False)
                self._pool = None


def _co_initialize() -> None:
    try:
        import pythoncom
        pythoncom.CoInitialize()
    except Exception:
        pass                      # sin pywin32 el brillo ya fallara mas abajo


DISPOSITIVOS = _Dispositivos()


# ============================================== WinRT: las radios
def _winrt_radios():
    """El modulo de radios de WinRT, venga del paquete que venga.

    `winsdk` y `winrt` son la misma proyeccion con dos nombres segun la
    epoca. Se prueban los dos: cual tenga instalado el usuario no es asunto
    de este codigo.
    """
    for modulo in ("winsdk.windows.devices.radios",
                   "winrt.windows.devices.radios"):
        try:
            return __import__(modulo, fromlist=["Radio"])
        except ImportError:
            continue
    return None


def winrt_disponible() -> bool:
    return _winrt_radios() is not None


class WindowsRadioControl:
    """Implementa `RadioControl` sobre `Windows.Devices.Radios`."""

    def __init__(self, policy: Policy):
        self.policy = policy
        self.last_error = ""

    def _permiso(self) -> bool:
        decision = self.policy.can_control("radio")
        self.last_error = "" if decision.allowed else decision.reason
        return decision.allowed

    @staticmethod
    def _kind_de(mod, kind: str):
        return {"bluetooth": mod.RadioKind.BLUETOOTH,
                "wifi": mod.RadioKind.WI_FI}.get(kind)

    def _buscar(self, kind: str):
        """La primera radio del tipo pedido, o None. Corre en el hilo."""
        mod = _winrt_radios()
        if mod is None:
            raise RuntimeError("faltan las proyecciones WinRT (pip install winsdk)")
        objetivo = self._kind_de(mod, kind)
        if objetivo is None:
            raise ValueError(f"radio desconocida: {kind}")

        async def _traer():
            # `request_access_async` es obligatorio antes de escribir: sin el,
            # `set_state_async` devuelve DENIED_BY_SYSTEM sin explicar nada.
            await mod.Radio.request_access_async()
            radios = await mod.Radio.get_radios_async()
            return [r for r in radios if r.kind == objetivo]

        encontradas = asyncio.run(_traer())
        return encontradas[0] if encontradas else None

    def state(self, kind: str) -> RadioState:
        """Leer no tiene efecto, asi que no consulta a la politica.

        Solo escribir cambia algo; exigir el permiso de apagado para poder
        decir «el Bluetooth esta encendido» seria confundir las dos cosas.
        """
        tipo = normaliza_radio(kind)
        if not tipo:
            self.last_error = f"no se que radio es «{kind}»"
            return RadioState(kind=str(kind), on=None)

        mod = _winrt_radios()
        try:
            radio = DISPOSITIVOS.run(lambda: self._buscar(tipo))
        except Exception as exc:
            self.last_error = str(exc)[:140]
            return RadioState(kind=tipo, on=None)

        if radio is None:
            self.last_error = f"este equipo no tiene {tipo}"
            return RadioState(kind=tipo, on=None)

        self.last_error = ""
        encendida = radio.state == mod.RadioState.ON
        # DISABLED y UNKNOWN no son «apagada»: son «no lo se».
        conocido = radio.state in (mod.RadioState.ON, mod.RadioState.OFF)
        return RadioState(kind=tipo, on=encendida if conocido else None,
                          name=getattr(radio, "name", "") or "")

    def set(self, kind: str, on: bool) -> bool:
        tipo = normaliza_radio(kind)
        if not tipo:
            self.last_error = f"no se que radio es «{kind}»"
            return False
        if not self._permiso():
            return False

        mod = _winrt_radios()

        def _aplicar() -> bool:
            radio = self._buscar(tipo)
            if radio is None:
                raise RuntimeError(f"este equipo no tiene {tipo}")
            destino = mod.RadioState.ON if on else mod.RadioState.OFF

            async def _set():
                return await radio.set_state_async(destino)

            resultado = asyncio.run(_set())
            if resultado != mod.RadioAccessStatus.ALLOWED:
                detalle = getattr(resultado, "name", resultado)
                raise RuntimeError(f"Windows no dejo cambiarla ({detalle})")
            return True

        try:
            return bool(DISPOSITIVOS.run(_aplicar))
        except Exception as exc:
            self.last_error = str(exc)[:140]
            return False


# ============================================== WMI: el brillo
class WindowsDisplayControl:
    """Implementa `DisplayControl` sobre WMI (root\\WMI).

    Funciona con paneles que exponen control por software: portatiles y
    todo-en-uno. Un monitor externo por HDMI normalmente **no** aparece ahi
    —eso va por DDC/CI, que es otro mundo— y entonces se dice que no se
    puede, en vez de mover un brillo que nadie ve.
    """

    RUTA = "winmgmts:\\\\.\\root\\WMI"

    def __init__(self, policy: Policy):
        self.policy = policy
        self.last_error = ""

    def _permiso(self) -> bool:
        decision = self.policy.can_control("display")
        self.last_error = "" if decision.allowed else decision.reason
        return decision.allowed

    @classmethod
    def _wmi(cls):
        import win32com.client
        return win32com.client.GetObject(cls.RUTA)

    def brightness(self) -> int:
        """Nivel actual 0-100, o -1 si el panel no lo expone.

        -1 y no 0: «no lo se» y «apagado del todo» no son lo mismo, y aqui
        confundirlos haria que FRIDAY dijera que tienes la pantalla negra.
        """
        def _leer() -> int:
            for o in self._wmi().InstancesOf("WmiMonitorBrightness"):
                return int(o.CurrentBrightness)
            raise RuntimeError("ningun panel expone su brillo")

        try:
            self.last_error = ""
            return int(DISPOSITIVOS.run(_leer))
        except Exception as exc:
            self.last_error = str(exc)[:140]
            return -1

    def set_brightness(self, level: int) -> int:
        """Fija el brillo. Devuelve el nivel aplicado, o -1 si no pudo."""
        if not self._permiso():
            return -1
        nivel = max(0, min(100, int(level)))

        def _aplicar() -> int:
            for m in self._wmi().InstancesOf("WmiMonitorBrightnessMethods"):
                m.WmiSetBrightness(0, nivel)     # timeout 0 = permanente
                return nivel
            raise RuntimeError("ningun panel acepta cambios de brillo")

        try:
            self.last_error = ""
            return int(DISPOSITIVOS.run(_aplicar))
        except Exception as exc:
            self.last_error = str(exc)[:140]
            return -1
