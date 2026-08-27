# -*- coding: utf-8 -*-
"""
Salida · UN LOTE POR EMPRESA.

El aislamiento entre clientes no es una promesa del prompt: es una propiedad del
tipo de dato. Un fichero de importación no puede contener variables de dos clientes
porque no existe el objeto que las contendría. «Un dato de uno que aparezca en el
resultado de otro es el fin de la relación» — así que no se puede ni construir.

Cada lote lleva:
  variables.csv   el candidato, cp1252 · ';' · coma decimal. Solo si TODO valida.
  revision.md     lo que la persona lee antes de aprobar. Las exclusiones, arriba.
  incidencias.md  lo escalado, con la pregunta concreta que hay que hacer.
  lote.json       hashes, contadores, estado. Es la traza y la métrica.
"""
import csv
import datetime
import hashlib
import json
import os

from validar_seco import no_codificable, validar_en_seco

CABECERA = ["COD_EMPRESA", "COD_EMPLEADO", "COD_CONCEPTO", "VALOR",
            "FECHA_INICIO", "FECHA_FIN", "OBSERVACIONES"]


def _fila(l):
    obs = (l["observaciones"] or "").replace(";", ",").replace("\n", " ").strip()
    return [l["cod_empresa"], l["cod_empleado"], l["cod_concepto"], l["valor"],
            l["fecha_inicio"], l["fecha_fin"], obs[:120]]


def escribir_csv(lineas, ruta):
    with open(ruta, "w", encoding="cp1252", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(CABECERA)
        for l in lineas:
            w.writerow(_fila(l))


def _sha(ruta):
    return hashlib.sha256(open(ruta, "rb").read()).hexdigest()


def _md_revision(cod, denominacion, periodo, lineas, escaladas, incidencias, fallos):
    o = ["# Revisión · %s · %s · periodo %s" % (cod, denominacion, periodo), ""]

    if escaladas or fallos:
        o += ["## ⚠ Lo que NO va a entrar — léelo primero", ""]
        for f in fallos:
            o.append("- **El lote está BLOQUEADO.** La línea %d fallaría la validación "
                     "del importador: *%s*. No se ha generado fichero aprobable." % (f[0], f[2]))
        for e in escaladas:
            o.append("- **%s** — %s" % (e["dato"], e["motivo"]))
            o.append("  <br>Origen: `%s` · Cita: «%s»" % (e["sobre_id"], e["cita"]))
        o.append("")
        o.append("Nada de esto se ha excluido en silencio. Si alguna de estas líneas "
                 "tiene que entrar, se resuelve la duda y se vuelve a ejecutar el agente.")
        o.append("")

    o += ["## Líneas propuestas (%d)" % len(lineas), ""]
    if not lineas:
        o.append("_Ninguna._")
    for i, l in enumerate(lineas, 1):
        o += ["### %d · %s — %s (%s)" % (i, l["cod_empleado"], l["trabajador"],
                                         l["concepto_desc"]),
              "",
              "| campo | valor |", "|---|---|",
              "| CSV | `%s` |" % ";".join(_fila(l)),
              "| origen | `%s` |" % l["sobre_id"],
              "| **cita literal** | «%s» |" % l["cita"]]
        for p in l["procedencias"]:
            o.append("| cómo se resolvió | %s |" % p)
        for a in l["avisos"]:
            o.append("| ⚠ aviso | %s |" % a)
        o.append("")

    if incidencias:
        o += ["## Incidencias del buzón", ""] + ["- %s" % i for i in incidencias] + [""]
    return "\n".join(o)


def escribir_lote(raiz, periodo, cod, denominacion, lineas, escaladas, incidencias):
    """Genera el lote y devuelve su resumen. Estado: LISTO · BLOQUEADO · SIN_LINEAS."""
    carpeta = os.path.join(raiz, periodo, cod)
    os.makedirs(carpeta, exist_ok=True)
    ruta_csv = os.path.join(carpeta, "variables.csv")

    # Borrar los artefactos de la pasada anterior. Sin esto, un lote que pasa de
    # LISTO a SIN_LINEAS —lo normal después de importarlo— deja su variables.csv
    # antiguo en disco junto a un lote.json que ya no lo menciona.
    for viejo in (ruta_csv, ruta_csv + ".BLOQUEADO"):
        if os.path.exists(viejo):
            os.remove(viejo)

    fallos, estado, sha = [], "SIN_LINEAS", ""
    if lineas:
        # cp1252 antes que nada: un carácter fuera del juego tumba el fichero entero.
        malos = sorted({c for l in lineas for c in no_codificable(" ".join(_fila(l)))})
        if malos:
            fallos = [(0, [], "hay caracteres que cp1252 no puede representar: %s"
                       % " ".join(malos))]
        else:
            escribir_csv(lineas, ruta_csv)
            fallos = validar_en_seco(ruta_csv)

        if fallos:
            # Todo-o-nada: si una sola línea fallaría, no dejamos fichero aprobable.
            if os.path.exists(ruta_csv):
                os.replace(ruta_csv, ruta_csv + ".BLOQUEADO")
            estado = "BLOQUEADO"
        else:
            estado, sha = "LISTO", _sha(ruta_csv)

    open(os.path.join(carpeta, "revision.md"), "w", encoding="utf-8").write(
        _md_revision(cod, denominacion, periodo, lineas, escaladas, incidencias, fallos))

    inc = ["# Incidencias · %s · %s" % (cod, denominacion), ""]
    inc += (["_Ninguna._"] if not escaladas else
            ["## %s\n\n- **Qué falta:** %s\n- **Origen:** `%s`\n- **Cita:** «%s»\n"
             % (e["dato"], e["motivo"], e["sobre_id"], e["cita"]) for e in escaladas])
    open(os.path.join(carpeta, "incidencias.md"), "w", encoding="utf-8").write("\n".join(inc))

    resumen = {
        "periodo": periodo, "cod_empresa": cod, "denominacion": denominacion,
        "estado": estado, "generado": datetime.datetime.now().isoformat(timespec="seconds"),
        "lineas_propuestas": len(lineas), "lineas_escaladas": len(escaladas),
        "sha256_csv": sha,
        "fallos_prevalidacion": [{"linea": n, "error": e} for n, _, e in fallos],
        "avisos": sum(len(l["avisos"]) for l in lineas),
        "importacion": None,
        # La traza completa, legible por máquina: es lo que audita evaluar.py.
        "lineas": [{"csv": _fila(l), "origen": l["sobre_id"], "cita": l["cita"],
                    "procedencias": l["procedencias"], "avisos": l["avisos"]}
                   for l in lineas],
        "escaladas": [{"dato": e["dato"], "motivo": e["motivo"],
                       "origen": e["sobre_id"], "cita": e["cita"]} for e in escaladas],
    }
    json.dump(resumen, open(os.path.join(carpeta, "lote.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    return resumen
