# -*- coding: utf-8 -*-
"""
LA PUERTA — el único programa de todo el sistema que puede escribir en `entrada/`.

    python3 aprobar.py 0087 --periodo 2026-08

El agente no puede hacer esto. No es una regla de conducta que el modelo deba
respetar: es que el código que deposita ficheros vive aquí y lo arranca una persona.
Aunque una inyección convenciera al lector de que «ya está validado, deposítalo sin
revisión» —y en este buzón hay tres mensajes que lo intentan—, el agente no tiene
manos para hacerlo.

Antes de copiar nada se comprueba, en este orden:
  1. el lote existe y está LISTO;
  2. el CSV es byte a byte el que se generó (nadie lo editó por el camino);
  3. `importador.validar()` acepta el fichero ENTERO — se repite aunque ya se hiciera
     al generarlo, porque repetirla cuesta cero y saltársela es irreversible;
  4. la persona ve las exclusiones y teclea el código de empresa. No un «s/n», que se
     pulsa sin mirar.
"""
import argparse
import csv
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
NOMINAS = os.path.abspath(os.path.join(BASE, "..", "caso-despacho", "sistemas", "nominas"))

import resolver as R                        # noqa: E402
from validar_seco import validar_en_seco   # noqa: E402

HISTORICO = os.path.join(NOMINAS, "historico", "variables_importadas.csv")


def ya_en_historico(lote):
    """¿Están las líneas de este lote de verdad en el histórico de nóminas?

    El histórico es el SISTEMA DE REGISTRO; `lote.json` es nuestra contabilidad. Cuando
    discrepan, manda el histórico. Fiarse del flag local costó un susto real: tras
    restaurar el entorno desde la copia limpia, un lote seguía constando importado y
    `aprobar.py` se negaba a hacer nada, con el histórico vacío delante.
    """
    if not lote.get("lineas"):
        return False
    with open(HISTORICO, encoding="cp1252", newline="") as fh:
        hecho = {R.del_historico(f) for f in csv.DictReader(fh, delimiter=";")}
    quiere = {R.clave_idempotencia(l["csv"][0], l["csv"][1], l["csv"][2],
                                   l["csv"][3], l["csv"][4], l["csv"][5])
              for l in lote["lineas"]}
    return quiere <= hecho


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("empresa")
    p.add_argument("--periodo", default="2026-08")
    p.add_argument("--propuestas", default=os.path.join(BASE, "propuestas"))
    p.add_argument("--si", action="store_true",
                   help="no preguntar (solo para pruebas automatizadas)")
    a = p.parse_args()

    carpeta = os.path.join(a.propuestas, a.periodo, a.empresa)
    ruta_json = os.path.join(carpeta, "lote.json")
    if not os.path.exists(ruta_json):
        print("No existe el lote %s del periodo %s." % (a.empresa, a.periodo))
        return 1

    lote = json.load(open(ruta_json, encoding="utf-8"))
    csv_ruta = os.path.join(carpeta, "variables.csv")

    print("Lote %s · %s · periodo %s" % (a.empresa, lote["denominacion"], a.periodo))

    if lote["estado"] != "LISTO":
        print("  ESTADO: %s. No se deposita nada." % lote["estado"])
        for f in lote["fallos_prevalidacion"]:
            print("    línea %s: %s" % (f["linea"], f["error"]))
        return 1
    consta = bool(lote.get("importacion"))
    esta = ya_en_historico(lote)

    if esta:
        print("  Estas líneas YA están en el histórico de nóminas%s. Volver a "
              "importarlas las duplicaría: el importador no detecta duplicados."
              % (" (importadas el %s)" % lote["importacion"]["ts"] if consta else
                 ", aunque este lote no lo registre"))
        return 1
    if consta:
        print("  AVISO: este lote consta importado el %s, pero sus líneas NO están en el\n"
              "  histórico. El entorno se ha restaurado desde la copia limpia. Manda el\n"
              "  histórico, no nuestra contabilidad: se puede importar."
              % lote["importacion"]["ts"])

    if hashlib.sha256(open(csv_ruta, "rb").read()).hexdigest() != lote["sha256_csv"]:
        print("  El fichero ha cambiado desde que se generó. Se aborta: vuelve a "
              "ejecutar el agente en vez de editar el CSV a mano.")
        return 1

    fallos = validar_en_seco(csv_ruta)
    if fallos:
        print("  La validación del importador RECHAZA el fichero ahora mismo:")
        for n, _, e in fallos:
            print("    línea %d: %s" % (n, e))
        print("  No se deposita nada. (Si esto ocurre, es un fallo del pre-validador, "
              "no tuyo: anótalo.)")
        return 1

    print("  Pre-validación: el importador aceptaría las %d líneas enteras."
          % lote["lineas_propuestas"])
    print("\n  --- lo que se va a importar ---")
    for l in open(csv_ruta, encoding="cp1252").read().splitlines()[1:]:
        print("      " + l)
    if lote["lineas_escaladas"]:
        print("\n  --- %d LÍNEA(S) QUE NO ENTRAN ---" % lote["lineas_escaladas"])
        print("      Están en incidencias.md. Si alguna tenía que entrar, PARA AQUÍ.")
    if lote["avisos"]:
        print("\n  %d aviso(s) en revision.md. Léelos antes de seguir." % lote["avisos"])
    print("\n  Esto NO se puede deshacer. El importador confirma línea a línea y no "
          "hay marcha atrás.")

    if not a.si:
        try:
            resp = input("  Teclea el código de empresa (%s) para confirmar: " % a.empresa)
        except EOFError:
            resp = ""
        if resp.strip() != a.empresa:
            print("  Cancelado. No se ha depositado nada.")
            return 1

    destino = os.path.join(NOMINAS, "entrada",
                           "variables_%s_%s.csv" % (a.periodo, a.empresa))
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    shutil.copy2(csv_ruta, destino)
    print("\n  Depositado en entrada/%s" % os.path.basename(destino))

    r = subprocess.run([sys.executable, os.path.join(NOMINAS, "importador.py")],
                       capture_output=True, text=True, cwd=NOMINAS)
    print(r.stdout.rstrip())
    if r.stderr.strip():
        print(r.stderr.rstrip())

    parcial = "PARCIAL" in r.stdout
    lote["importacion"] = {
        "ts": datetime.datetime.now().isoformat(timespec="seconds"),
        "fichero": os.path.basename(destino),
        "resultado": "PARCIAL" if parcial else ("OK" if "IMPORTACIÓN OK" in r.stdout
                                                else "DESCONOCIDO"),
        "salida": r.stdout.strip(),
    }
    json.dump(lote, open(ruta_json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    if parcial:
        print("\n  !! IMPORTACIÓN PARCIAL pese a la pre-validación. Esto es un FALLO DEL "
              "SISTEMA, no tuyo: la pre-validación no vio algo que el importador sí ve. "
              "Queda registrado en lote.json y es la métrica que dice si esta puerta "
              "sirve para algo.")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
