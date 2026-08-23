"""Lenguaje hablado: normalizar lo que llega del STT antes de decidir nada.

Existe por una razon medida: **FRIDAY no lee, oye**. El texto que entra al
router no lo escribio nadie — lo transcribio un modelo que se come tildes,
parte los nombres compuestos y escribe los numeros con letra la mitad de las
veces. Cada capa que resolvia eso por su cuenta lo resolvia distinto:
`core/engine.py` doblaba acentos, `skills/taller.py` doblaba acentos *y*
puntuacion, y `skills/ordenador.py` no doblaba nada y perdia «sube el volumen
veinte» porque `int("veinte")` lanza.

Aqui no hay politica ni efectos: son funciones puras sobre cadenas. Se puede
importar desde cualquier capa sin romper la regla 5 — no comunica nada, mide.
"""
from __future__ import annotations

import difflib
import re
import unicodedata

# ══════════════════════════════════════════════ formas de la misma palabra
def fold(text: str) -> str:
    """Minusculas sin acentos. La puntuacion se queda.

    El STT rara vez acierta la tilde y nunca la acierta dos veces igual:
    «metricas», «métricas» y «metrícas» son la misma peticion.
    """
    norm = unicodedata.normalize("NFD", str(text).lower())
    return "".join(c for c in norm if unicodedata.category(c) != "Mn")


def slug_words(text: str) -> str:
    """Como `fold`, pero ademas todo lo que no sea alfanumerico es un espacio.

    `mi-proyecto`, `mi_proyecto` y «mi proyecto» son lo mismo dicho de tres
    maneras, y el dictado siempre entrega la tercera.
    """
    return re.sub(r"[^a-z0-9]+", " ", fold(text)).strip()


def parecido(a: str, b: str) -> float:
    """0..1 de cuanto se parecen dos nombres ya doblados.

    Se usa para *proponer*, nunca para actuar: un parecido alto es motivo
    para preguntar «¿te refieres a X?», no para elegir X.
    """
    return difflib.SequenceMatcher(None, slug_words(a), slug_words(b)).ratio()


# ══════════════════════════════════════════════ numeros dictados
_UNIDADES = {
    "cero": 0, "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4,
    "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10,
    "once": 11, "doce": 12, "trece": 13, "catorce": 14, "quince": 15,
    "dieciseis": 16, "diecisiete": 17, "dieciocho": 18, "diecinueve": 19,
    "veinte": 20, "veintiuno": 21, "veintidos": 22, "veintitres": 23,
    "veinticuatro": 24, "veinticinco": 25, "veintiseis": 26,
    "veintisiete": 27, "veintiocho": 28, "veintinueve": 29,
}
_DECENAS = {
    "treinta": 30, "cuarenta": 40, "cincuenta": 50, "sesenta": 60,
    "setenta": 70, "ochenta": 80, "noventa": 90, "cien": 100, "ciento": 100,
}

# Cantidades que la gente dice en vez de un numero. Sin esto, «bajale un
# poco» y «bajale muchisimo» pedian exactamente el mismo salto.
_VAGAS = {
    "un poquito": 5, "un poco": 10, "algo": 10, "un pelin": 5, "un pelo": 5,
    "bastante": 25, "mucho": 30, "muchisimo": 40, "un monton": 40,
    "al maximo": 100, "del todo": 100, "a tope": 100, "nada": 0,
    "la mitad": 50, "un tercio": 33, "un cuarto": 25,
}

_FRACCIONES = {"mitad": 50, "medio": 50, "media": 50, "tercio": 33, "cuarto": 25}


def numero(text: str, por_defecto: int | None = None) -> int | None:
    """El primer numero que aparece en la frase, en digitos o en letra.

    Devuelve `por_defecto` si no hay ninguno. Reconoce, en este orden:

        "ponlo a 40"        -> 40      digitos, incluido «40%»
        "volumen al veinte" -> 20      palabra suelta
        "treinta y cinco"   -> 35      decena + unidad
        "a la mitad"        -> 50      fraccion hablada
        "bajale un poco"    -> 10      cantidad vaga

    Las vagas van **despues de los digitos y antes de las palabras sueltas**,
    y ese orden esta pagado con un fallo: «ponlo a 5, un poco mas» tiene un
    numero de verdad y ese manda, pero «bajale un poco» devolvia 1 porque el
    «un» de la frase hecha es tambien la palabra para el uno.
    """
    plano = slug_words(text)
    if not plano:
        return por_defecto

    m = re.search(r"(?<![a-z0-9])(\d{1,3})(?![0-9])", plano)
    if m:
        return int(m.group(1))

    for frase, valor in _VAGAS.items():
        if frase in plano:
            return valor

    palabras = plano.split()
    for i, w in enumerate(palabras):
        if w in _DECENAS:
            base = _DECENAS[w]
            # «treinta y cinco»: la conjuncion es opcional, el STT la pierde.
            resto = palabras[i + 1:i + 3]
            if resto and resto[0] == "y" and len(resto) > 1 and resto[1] in _UNIDADES:
                return base + _UNIDADES[resto[1]]
            if resto and resto[0] in _UNIDADES and base < 100:
                return base + _UNIDADES[resto[0]]
            return base
        if w in _UNIDADES:
            return _UNIDADES[w]

    for w in palabras:
        if w in _FRACCIONES:
            return _FRACCIONES[w]
    return por_defecto


# ══════════════════════════════════════════════ forma de la frase
# Una pregunta sobre la maquina no se parece a un lamento que la menciona.
# «cuanta RAM me queda» pregunta; «se me cayo el servidor» cuenta algo.
_INTERROGATIVO = re.compile(
    r"(^\s*[¿?]|\?\s*$"
    r"|^\s*(y\s+)?(que|cual|cuales|cuanto|cuanta|cuantos|cuantas|como|"
    r"donde|cuando|quien|por que|para que)\b"
    r"|^\s*(dime|dame|muestra|muestrame|ensename|informe|reporte|resumen|"
    r"lee|lista|listame|checa|revisa|comprueba|mira)\b"
    r"|\b(me queda|tengo|hay|va|esta|estan|anda)\b\s*[?]?\s*$)", re.I)

# Narrar algo que pasa no es pedir nada. Estas marcas aparecen en frases que
# mencionan vocabulario tecnico sin pedir una lectura de la maquina.
_NARRATIVO = re.compile(
    r"^\s*(se me|se nos|me|nos|le)\s+(cayo|callo|rompio|jodio|peto|murio|"
    r"colgo|trabo|freno|revento)\b"
    r"|\b(tengo|tenemos)\s+(una|un|el|la)\s+(demo|reunion|entrega|examen|"
    r"presentacion|junta|llamada|deadline|entrevista)\b"
    r"|\b(ayer|anoche|el otro dia|la semana pasada|hace un rato)\b", re.I)


def es_pregunta(text: str) -> bool:
    """¿La frase pide un dato, o esta contando algo?

    No es analisis sintactico: es la diferencia entre «cuanto me queda de
    disco» y «se me lleno el disco y perdi la tarde», que comparten la
    palabra que dispara la skill de metricas y no comparten la intencion.
    """
    plano = fold(text).strip()
    if _NARRATIVO.search(plano):
        return False
    return bool(_INTERROGATIVO.search(plano))


def es_narrativo(text: str) -> bool:
    """La otra mitad: la frase cuenta algo que paso, no pide nada."""
    return bool(_NARRATIVO.search(fold(text)))


# ══════════════════════════════════════════════ eco para confirmar
_RELLENO = re.compile(
    r"^\s*(oye|eh|em|este|a ver|mira|pues|bueno|porfa|por favor|friday|viernes)"
    r"[\s,]+", re.I)


def limpia(text: str) -> str:
    """Quita muletillas del principio y aprieta espacios. No cambia el fondo.

    Se usa para el **eco**: cuando FRIDAY repite lo que entendio antes de
    hacer algo con efecto, repetir «eh, oye, em» no ayuda a nadie a detectar
    que oyo mal.
    """
    limpio = re.sub(r"\s+", " ", str(text)).strip()
    anterior = ""
    while limpio != anterior:
        anterior = limpio
        limpio = _RELLENO.sub("", limpio).strip()
    return limpio or str(text).strip()
