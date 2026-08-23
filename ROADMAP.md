# Pendientes

Lo que falta, por qué falta y dónde tocarlo. Nada aquí es una idea suelta:
todo salió de usar FRIDAY o de un límite que se dejó puesto a conciencia.

Cuando algo se cierre, se borra de aquí y se documenta en el `README.md`.

---

## Prioridad alta

### ☐ Instalar la voz de Piper

`[voice.tts] engine = "piper"` está configurado, pero no hay ningún `.onnx` en
`models/piper/`, así que siempre cae a SAPI5. Funciona, pero Piper suena
bastante mejor. El código de carga y de reproducción ya está y es
multiplataforma — **solo falta el modelo**, y bajarlo es una decisión del
dueño de la máquina, no algo que el repo deba hacer por su cuenta.

Es lo único de esta lista que no es trabajo de programación, y por eso está
arriba: es la mejora más grande por menos esfuerzo que le queda al proyecto.

### ☐ Medir `anthropic_api` de verdad

Sigue sin medirse, y es lo primero que hay que hacer antes de escribir una
línea de adaptador persistente. Ya está implementado y en el roster
(`di «directo»`); es HTTP puro, así que elimina de golpe el proceso de Node y
la inicialización de Claude Code, y solo queda la latencia de red.

Necesita `ANTHROPIC_API_KEY`, que no está configurada.

| | medido el 17/08/2026 |
|---|---|
| arrancar el binario `claude --version` | **0,2 s** |
| turno corto completo por `claude_code` | **3,3-3,7 s** |
| turno corto por Ollama local (HTTP) | **0,3-0,6 s** |
| turno corto por `anthropic_api` | **sin medir** |

Lo importante: el arranque del proceso son 200 ms, no los 3 s. Mantener una
instancia viva recupera bastante menos de lo que parece, y además choca con
que cada llamada de FRIDAY declara su propio formato y es deliberadamente sin
estado — una sesión persistente filtraría el contrato JSON de una skill al
turno de la siguiente.

---

## Prioridad media

### ☐ Modelo local: cerrar el hueco que queda

Con `llama3.1:8b` sobre Ollama, la elección de acción del catálogo va 12/12,
igual que Sonnet (ver el README). Lo que sigue abierto:

- **Las skills de prosa no se han medido con el 8B**: `inbox`, `plan`,
  `noticias`, `pantalla` y `web` piden markdown, no JSON, y ahí el contrato
  es más laxo pero la calidad de redacción es lo que más se nota.
- **El catálogo de `ordenador` creció a 14 acciones** (radios y brillo). La
  medida de 12/12 se hizo con nueve. Hay que **repetirla**: más entradas es
  más superficie donde confundir dos vecinas, y `radio_encender` /
  `radio_apagar` son exactamente el par que un modelo pequeño puede cruzar.
  Los ejemplos ya llevan el argumento (`desactiva el bluetooth -> bluetooth`),
  que es lo que arregló el signo del volumen, pero no está comprobado.
- **`_freeform` con notas del vault**: aun con las palabras vacías fuera, un
  8B se apoya más de la cuenta en el contexto inyectado. Convendría exigir
  una puntuación mínima, no solo que haya coincidencia.
- **Modelos más pequeños que 8B** no se han probado. El 3B es donde se vería
  si los prompts aguantan de verdad o solo aguantan con este.

### ☐ Calibrar `OIDO_DUDOSO` con voz real

El eco de confirmación (`core/router.py`) dispara por debajo de `0.55` de
confianza del STT. Ese número está puesto **por criterio, no medido**: la
lógica y el cableado están probados, pero cuál es el umbral correcto para
`faster-whisper` con tu micrófono y tu voz solo se sabe dictando.

Demasiado alto y FRIDAY pregunta constantemente, que es peor que no preguntar
— confirmar de más entrena a decir «sí» sin escuchar. Demasiado bajo y no
atrapa el caso que existe para atrapar.

**Cómo**: `voice.stt.final` ya lleva `confidence` en el bus, y el registro lo
recoge. Dictar un rato normal, mirar la distribución y poner el umbral en la
cola baja.

### ☐ Brillo de monitores externos (DDC/CI)

`DisplayControl` funciona con paneles que exponen control por software:
portátiles y todo-en-uno. Un monitor por HDMI no aparece en WMI y FRIDAY dice
que no puede, que es correcto pero no útil si es tu única pantalla.

Sale por DDC/CI, que es otro mundo: `SetVCPFeature` de `dxva2.dll`, por
monitor físico. Cabe en `system/win32/radios.py` detrás del mismo puerto y sin
tocar ninguna skill — que es justamente la prueba de que el puerto está bien
puesto.

---

## Decisiones tomadas a conciencia, no olvidos

No están pendientes: están **decididas**. Si algún día se cambian, que sea a
sabiendas y no por creer que se olvidaron.

- **`allow_shell = false`.** Ejecución de comandos arbitrarios dictados por
  voz, con un STT que se equivoca. Si se abre, que sea con lista blanca de
  comandos, nunca con texto libre.
- **Nada de apagar ni reiniciar** en `SessionControl`. Una orden mal
  transcrita no puede costarte el trabajo sin guardar. Bloquear y suspender
  sí, y aun así se confirman.
- **Los avisos solo salen, nunca entran.** Hay pasarela de notificación
  (`system/notify.py`) y no la habrá de entrada: aceptar órdenes remotas
  sortearía el PTT, la confirmación hablada y la política de un solo golpe.
  Ver la regla 8 del `CLAUDE.md`.
- **`allow_radio = false` de fábrica.** No es prudencia genérica: apagar el
  wifi puede dejar sin motor a la propia FRIDAY a media frase.
- **No se raspan páginas de resultados de buscadores.** Cambian el HTML cada
  pocas semanas y muchos lo bloquean; un asistente apoyado en eso empieza a
  mentir en cuanto se rompe.
- **La memoria es markdown y nada más.** Ninguna base de datos, ningún índice
  persistente. Las marcas del reloj también: van a la nota diaria, no a un
  archivo de estado.

---

## Algún día

- **`system/linux/`** — los `Protocol` de `system/ports.py` están para esto:
  implementarlos para X11/Wayland no debería tocar ni una skill. Es la prueba
  de fuego de que la inversión de dependencias vale de algo. Con `RadioControl`
  y `DisplayControl` recién añadidos hay dos candidatos fáciles: `rfkill` y
  `brightnessctl` hacen lo mismo en tres líneas.
- **Piper en streaming** — sintetizar por frases y empezar a hablar antes de
  tener el audio entero. Con respuestas largas se nota la espera, y ahora que
  FRIDAY conversa las respuestas son más largas que antes.
- **Trabajos del reloj declarados hablando** — hoy `[[schedule.jobs]]` se
  escribe en el toml. «Todos los lunes a las nueve dame el briefing» debería
  poder escribirlo ella. Es una skill que escribe config, así que necesita su
  propio permiso: la política no cubre «modificarse a sí misma».
