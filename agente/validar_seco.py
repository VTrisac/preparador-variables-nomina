# -*- coding: utf-8 -*-
"""
Etapa 5 · PRE-VALIDACIÓN — la decisión de arquitectura más importante del proyecto.

El importador del software de nóminas confirma LÍNEA A LÍNEA y sin transacción: si
la línea 7 está mal, las seis primeras ya están dentro, el fichero se marca PARCIAL
y no hay deshacer. Eso no se puede cambiar: es el software del cliente.

Lo que sí se puede hacer es NO reimplementar su validación, sino importar la suya y
ejecutarla en seco sobre el fichero completo antes de que exista la menor posibilidad
de depositarlo. Si una sola línea fallaría, no se genera fichero aprobable.

Así, un importador sin transacción se vuelve todo-o-nada desde fuera.

Por qué importar en vez de replicar:
  · cero deriva — si el fabricante cambiara `validar()`, nuestra puerta lo sigue sola;
  · cero código que mantener;
  · y lo que comprobamos es exactamente lo que el importador comprobará, no nuestra
    interpretación de ello.

Verificado: `importador.py` se importa sin efectos secundarios (todo lo que actúa
está bajo `if __name__ == "__main__"`). No se modifica ni un byte de ese fichero.
"""
import csv
import importlib.util
import os

BASE = os.path.dirname(os.path.abspath(__file__))
IMPORTADOR = os.path.join(BASE, "..", "caso-despacho", "sistemas", "nominas", "importador.py")

_cache = None


def importador(ruta=IMPORTADOR):
    global _cache
    if _cache is None:
        spec = importlib.util.spec_from_file_location("imp_nominas", os.path.abspath(ruta))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _cache = mod
    return _cache


def no_codificable(texto):
    """cp1252 no cubre todo Unicode. Un carácter fuera del juego tumba el fichero
    entero en el importador (`UnicodeDecodeError` al releerlo) y aquí se ve antes.
    `validar()` no lo comprueba porque para cuando corre, el fichero ya se leyó."""
    malos = []
    for c in texto:
        try:
            c.encode("cp1252")
        except UnicodeEncodeError:
            malos.append(c)
    return malos


def validar_en_seco(ruta_csv, ruta_importador=IMPORTADOR):
    """Ejecuta la validación DEL CLIENTE sobre el fichero completo.

    Devuelve [] si el importador lo aceptaría entero, o la lista de
    (nº de línea, fila, mensaje de error) tal y como él los formularía.
    """
    imp = importador(ruta_importador)

    with open(ruta_csv, "r", encoding="cp1252", newline="") as fh:
        filas = list(csv.reader(fh, delimiter=";"))

    if not filas or [c.strip() for c in filas[0]] != imp.CABECERA:
        return [(1, filas[0] if filas else [], "la cabecera no es la esperada")]

    empleados, conceptos = imp.cargar_referencias()
    fallos = []
    for n, fila in enumerate(filas[1:], start=2):
        if not any(x.strip() for x in fila):
            continue
        error = imp.validar(fila, n, empleados, conceptos)   # su función, no la nuestra
        if error:
            fallos.append((n, fila, error))
    return fallos
