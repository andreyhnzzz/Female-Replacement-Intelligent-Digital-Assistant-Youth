# Avisos de terceros

F.R.I.D.A.Y se publica bajo la [licencia MIT](LICENSE). Ese permiso cubre el
código de este repositorio, no el de las bibliotecas que usa, que conservan
cada una la suya.

## Lo que hay que mirar antes de distribuir

Dos dependencias son **LGPLv3**, y eso trae obligaciones que MIT no tiene:

| Componente | Licencia | Para qué se usa |
|---|---|---|
| **PySide6** / shiboken6 | LGPL-3.0 *o* GPL-2.0 *o* GPL-3.0 | la ventana, QML y la escena 3D |
| **pynput** | LGPL-3.0 | el push-to-talk global (F9) |

La LGPL permite que tu propio código siga siendo MIT **siempre que el usuario
pueda sustituir la biblioteca LGPL por otra versión**. Con este proyecto tal
como está, eso se cumple solo: Python importa en tiempo de ejecución y
cualquiera puede actualizar o parchear PySide6 en su `.venv` sin tocar nada
más. Distribuir el código fuente, o el lanzador `FRIDAY.exe` —que no contiene
Qt, solo lo invoca—, no añade ninguna carga.

**Donde deja de ser gratis es en un bundle.** Si algún día se empaqueta todo
con PyInstaller en un único ejecutable, Qt viaja dentro y hay que dar al
usuario alguna forma de relinkar o reemplazar esas bibliotecas, además de
incluir el texto de la LGPL. Está anotado en el
[ROADMAP](ROADMAP.md) junto al resto de motivos por los que ese bundle es un
trabajo aparte.

## El resto

Comprobado sobre el entorno instalado, leyendo el fichero de licencia de cada
paquete y no su metadato —que en varios viene vacío:

| Componente | Licencia |
|---|---|
| faster-whisper | MIT |
| mss | MIT |
| comtypes | MIT |
| sounddevice | MIT |
| aiohttp | Apache-2.0 y MIT |
| numpy | BSD-3-Clause |
| psutil | BSD-3-Clause |
| pywin32 | Python Software Foundation License |
| pyttsx3 | Mozilla Public License 2.0 |

Todas permisivas: no imponen condiciones a este repositorio más allá de
conservar sus avisos de copyright si se redistribuyen.

Opcionales, solo si los instalas: **Piper** (MIT) para la voz neuronal y
**soundfile** (BSD-3-Clause) para reproducir su salida por CLI. Ninguno está
en el entorno por defecto.

## Modelos y contenido

- **Los modelos de voz no van en el repositorio.** `faster-whisper` descarga
  el suyo en el primer arranque, y las voces de Piper se bajan aparte. Cada
  modelo tiene su propia licencia — compruébala antes de redistribuirlo.
- **Las voces SAPI5 son de Windows** y se usan a través del sistema
  operativo; no se redistribuye ninguna.
- **Las fuentes RSS de `config/friday.toml`** son ejemplos apuntando a medios
  públicos. El contenido de esos feeds es de sus editores; FRIDAY lo lee y lo
  resume para uso personal, no lo republica.
- **El nombre F.R.I.D.A.Y y el personaje** son de Marvel. Este es un proyecto
  personal sin relación con Marvel ni Disney, y no está afiliado ni
  respaldado por ellos.

## Cómo comprobarlo tú

```powershell
.\.venv\Scripts\python -m pip install pip-licenses
.\.venv\Scripts\pip-licenses --format=markdown --with-urls
```
