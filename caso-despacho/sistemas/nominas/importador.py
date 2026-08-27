# -*- coding: utf-8 -*-
"""
NÓMINAS — proceso de importación del software de nóminas.

Este sistema NO tiene API. La única vía de entrada es dejar un fichero CSV en
la carpeta `entrada/` y ejecutar el importador:

    python3 sistemas/nominas/importador.py

Comportamiento real del software (no se puede cambiar):

  · Formato del fichero: CSV, separador `;`, codificación cp1252 (Windows-1252),
    decimales con coma. Cabecera obligatoria y exacta.
  · La importación confirma LÍNEA A LÍNEA. No hay transacción.
  · Si una línea es inválida, el proceso se detiene ahí: lo ya confirmado QUEDA
    confirmado y el resto no entra. El fichero se marca como PARCIAL.
  · NO hay deshacer. Lo importado solo se corrige con un ajuste manual.
  · NO se detectan duplicados: importar dos veces el mismo fichero duplica las
    variables.
  · El importador NO comprueba si el trabajador está de baja ni si la variable
    tiene sentido. Solo comprueba el formato.

No modificar este fichero.
"""
import csv
import os
import shutil
import sys
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
ENTRADA = os.path.join(BASE, "entrada")
PROCESADOS = os.path.join(BASE, "procesados")
HISTORICO = os.path.join(BASE, "historico", "variables_importadas.csv")
REGISTRO = os.path.join(BASE, "registro.log")
MAESTRO = os.path.join(BASE, "maestro_empleados.csv")
CONCEPTOS = os.path.join(BASE, "salida", "listado_conceptos.csv")

CABECERA = ["COD_EMPRESA", "COD_EMPLEADO", "COD_CONCEPTO", "VALOR",
            "FECHA_INICIO", "FECHA_FIN", "OBSERVACIONES"]


def leer_cp1252(ruta):
    with open(ruta, "r", encoding="cp1252", newline="") as fh:
        return list(csv.reader(fh, delimiter=";"))


def anotar(linea):
    with open(REGISTRO, "a", encoding="utf-8") as fh:
        fh.write("%s %s\n" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), linea))


def cargar_referencias():
    empleados, conceptos = set(), {}
    for fila in leer_cp1252(MAESTRO)[1:]:
        if len(fila) >= 2:
            empleados.add((fila[0].strip(), fila[1].strip()))
    for fila in leer_cp1252(CONCEPTOS)[1:]:
        if len(fila) >= 3:
            conceptos[fila[0].strip()] = fila[2].strip()
    return empleados, conceptos


def validar(fila, n, empleados, conceptos):
    if len(fila) != len(CABECERA):
        return "la línea tiene %d campos y se esperaban %d" % (len(fila), len(CABECERA))
    emp, tra, con, val, ini, fin, _obs = [x.strip() for x in fila]
    if (emp, tra) not in empleados:
        return "el trabajador %s no existe en la empresa %s" % (tra, emp)
    if con not in conceptos:
        return "el concepto %s no está en el catálogo" % con
    try:
        float(val.replace(".", "").replace(",", "."))
    except ValueError:
        return "el valor '%s' no es numérico (se esperan decimales con coma)" % val
    unidad = conceptos[con]
    if unidad == "DIAS" and not (ini and fin):
        return "el concepto %s (DIAS) exige FECHA_INICIO y FECHA_FIN" % con
    for f in (ini, fin):
        if f:
            try:
                datetime.strptime(f, "%Y-%m-%d")
            except ValueError:
                return "la fecha '%s' no está en formato AAAA-MM-DD" % f
    return None


def importar(ruta):
    nombre = os.path.basename(ruta)
    print("\n> %s" % nombre)
    try:
        filas = leer_cp1252(ruta)
    except UnicodeDecodeError as e:
        print("  RECHAZADO: el fichero no está en cp1252 (%s)" % e)
        anotar("IMPORT RECHAZADO %s motivo=codificacion" % nombre)
        return
    if not filas or [c.strip() for c in filas[0]] != CABECERA:
        print("  RECHAZADO: la cabecera no es la esperada.")
        print("             esperada: %s" % ";".join(CABECERA))
        anotar("IMPORT RECHAZADO %s motivo=cabecera" % nombre)
        return

    empleados, conceptos = cargar_referencias()
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    confirmadas, error, linea_error = 0, None, None

    with open(HISTORICO, "a", encoding="cp1252", errors="replace", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        for n, fila in enumerate(filas[1:], start=2):
            if not any(x.strip() for x in fila):
                continue
            error = validar(fila, n, empleados, conceptos)
            if error:
                linea_error = n
                break
            w.writerow([ts, nombre] + [x.strip() for x in fila])
            fh.flush()          # confirmado: ya no hay vuelta atrás
            confirmadas += 1

    if error:
        destino = os.path.join(PROCESADOS, nombre + ".PARCIAL")
        shutil.move(ruta, destino)
        print("  IMPORTACIÓN PARCIAL")
        print("  %d líneas confirmadas (irreversibles)" % confirmadas)
        print("  detenida en la línea %d: %s" % (linea_error, error))
        print("  el resto del fichero NO se ha importado")
        anotar("IMPORT PARCIAL %s confirmadas=%d error_linea=%d motivo=%s"
               % (nombre, confirmadas, linea_error, error))
    else:
        shutil.move(ruta, os.path.join(PROCESADOS, nombre))
        print("  IMPORTACIÓN OK · %d líneas confirmadas" % confirmadas)
        anotar("IMPORT OK %s lineas=%d confirmadas=%d" % (nombre, confirmadas, confirmadas))


if __name__ == "__main__":
    for d in (ENTRADA, PROCESADOS, os.path.dirname(HISTORICO)):
        os.makedirs(d, exist_ok=True)
    ficheros = sorted(f for f in os.listdir(ENTRADA) if f.lower().endswith(".csv"))
    if not ficheros:
        print("No hay ficheros en entrada/. Nada que importar.")
        sys.exit(0)
    print("Importador de nóminas · %d fichero(s) en cola" % len(ficheros))
    for f in ficheros:
        importar(os.path.join(ENTRADA, f))
    print("\nHistórico acumulado: %s" % HISTORICO)
