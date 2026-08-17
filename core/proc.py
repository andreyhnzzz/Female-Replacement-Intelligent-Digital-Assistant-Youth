"""Como FRIDAY lanza procesos hijos.

Un solo dato, pero se necesita en tres sitios que no se conocen entre si
(el motor, el catalogo de aplicaciones y el taller), y el motivo hay que
escribirlo una vez.

**El problema.** FRIDAY corre como aplicacion de escritorio Qt: no tiene
consola. Cuando un proceso hijo de consola arranca sin una, Windows le crea
una ventana propia. Resultado: una ventana negra parpadeando sobre el
escritorio **en cada turno hablado** — cada llamada al motor, cada refresco
del catalogo de apps, cada `git status` del taller. En un acompañante que
vive encima de tu trabajo, eso no es un detalle cosmetico: es la diferencia
entre algo que acompaña y algo que interrumpe.

**La solucion.** `CREATE_NO_WINDOW` en `creationflags`. El proceso corre
igual y sus tuberias funcionan igual; simplemente no se le da consola.

Fuera de Windows la constante vale 0, que es el valor por defecto de
`creationflags` y no hace nada: asi el codigo que la usa no necesita
preguntar en que sistema esta.
"""
from __future__ import annotations

import subprocess
import sys

NO_WINDOW: int = (getattr(subprocess, "CREATE_NO_WINDOW", 0)
                  if sys.platform == "win32" else 0)
