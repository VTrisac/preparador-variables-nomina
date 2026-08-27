# -*- coding: utf-8 -*-
"""
Preparador de variables de nómina — del buzón a un lote listo para revisar.

    python3 agente.py --periodo 2026-08

Lo que este programa NO puede hacer, por diseño y no por educación: escribir en
`entrada/`. Ese permiso lo tiene únicamente `aprobar.py`, que ejecuta una persona.
Aunque una inyección convenciera al modelo, el agente no tiene manos.
"""
import argparse
import datetime
import json
import os
import sys

import extraer as EX
import gestor as G
import resolver as R
from ingesta import ingerir
from lote import escribir_lote

BASE = os.path.dirname(os.path.abspath(__file__))
BUZON = os.path.join(BASE, "..", "caso-despacho", "sistemas", "buzon")


def _lector(preferido=None):
    """Devuelve (proveedor, cliente) según las claves que haya, o None.

    Con las dos claves puestas gana la que se pida con --proveedor; si no se pide
    ninguna, gana NVIDIA por ser la gratuita. La elección se imprime siempre: qué
    modelo leyó los mensajes es parte del resultado, no un detalle de configuración.
    """
    orden = [preferido] if preferido else ["nvidia", "anthropic"]
    for p in orden:
        if not os.environ.get(EX.PROVEEDORES[p]["clave"]):
            continue
        if p == "anthropic":
            import anthropic
            return p, anthropic.Anthropic()
        from openai import OpenAI
        return p, OpenAI(base_url="https://integrate.api.nvidia.com/v1",
                         api_key=os.environ["NVIDIA_API_KEY"])
    return None


def _aplicar_correcciones(variables):
    """«perdona, son 6 no 16»: gana la posterior, y las dos constan en el informe."""
    corregidas = {v["corrige_a"].strip() for v in variables if v.get("corrige_a", "").strip()}
    vivas, muertas = [], []
    for v in variables:
        (muertas if v["cita_literal"].strip() in corregidas else vivas).append(v)
    return vivas, muertas


def procesar(periodo, raiz_salida, lector=None, cache=None, fijado=None):
    tablas = R.Tablas()
    contactos = G.contactos() if G.disponible() else []
    if not contactos:
        print("  · el gestor no responde: se resuelve la empresa solo por denominación "
              "y plantilla, que es la vía con corroboración.")

    sobres = ingerir(os.path.join(BUZON, periodo))

    por_empresa, sin_encargo, incidencias_sueltas = {}, [], []

    for s in sobres:
        print("\n· %s" % s.id)
        for i in s.incidencias:
            print("    !! %s" % i[:160])
        if not s.procesable:
            print("    -> no se procesa: %s" % s.descartado)
            incidencias_sueltas += s.incidencias
            continue

        try:
            variables, notas, origen = EX.extraer(s, lector, cache, fijado)
        except RuntimeError as e:
            print("    -> ETAPA 2 sin resolver: %s" % e)
            return None
        print("    extracción (%s): %d variable(s). %s" % (origen, len(variables), notas[:110]))

        variables, corregidas = _aplicar_correcciones(variables)
        for c in corregidas:
            print("    ~~ corregida y descartada: «%s»" % c["cita_literal"][:80])

        if not variables:
            sin_encargo.append((s.id, notas))
            print("    -> no comunica variables de nómina; no genera encargo.")
            continue

        nombres = [v["trabajador_texto"] for v in variables]
        cod, procedencia, motivo = R.resolver_empresa(s, nombres, tablas, contactos)
        if not cod:
            print("    -> EMPRESA SIN RESOLVER: %s" % motivo)
            incidencias_sueltas.append("%s · empresa sin resolver: %s" % (s.id, motivo))
            por_empresa.setdefault("SIN_EMPRESA", {"lineas": [], "esc": [], "inc": []})
            por_empresa["SIN_EMPRESA"]["esc"] += [
                {"dato": "%s — %s" % (v["trabajador_texto"], v["concepto_texto"]),
                 "motivo": motivo, "sobre_id": s.id, "cita": v["cita_literal"]}
                for v in variables]
            por_empresa["SIN_EMPRESA"]["inc"] += s.incidencias
            continue

        print("    empresa %s (%s) · %s" % (cod, tablas.denominacion[cod], procedencia))
        e = por_empresa.setdefault(cod, {"lineas": [], "esc": [], "inc": []})
        e["inc"] += s.incidencias
        if corregidas:
            e["inc"] += ["CORRECCIÓN · «%s» quedó anulada por una rectificación posterior "
                         "del mismo remitente en %s" % (c["cita_literal"], s.id)
                         for c in corregidas]

        for v in variables:
            _una(v, s, cod, procedencia, tablas, periodo, e)

    resumenes = []
    for cod in sorted(por_empresa):
        d = por_empresa[cod]
        denom = tablas.denominacion.get(cod, "(empresa no identificada)")
        resumenes.append(escribir_lote(raiz_salida, periodo, cod, denom,
                                       d["lineas"], d["esc"], d["inc"]))
    return {"lotes": resumenes, "sin_encargo": sin_encargo,
            "incidencias": incidencias_sueltas}


def _una(v, sobre, cod, procedencia_empresa, tablas, periodo, acumulador):
    """Resuelve una variable extraída. Cualquier duda -> escala, nunca adivina."""
    def escalar(motivo):
        acumulador["esc"].append({
            "dato": "%s — %s %s" % (v["trabajador_texto"], v["valor"], v["concepto_texto"]),
            "motivo": motivo, "sobre_id": sobre.id, "cita": v["cita_literal"]})

    emp, proc_t, motivo = R.resolver_trabajador(v["trabajador_texto"], cod, tablas)
    if not emp:
        return escalar(motivo)

    fuera = R.estado_laboral(emp, periodo)
    if fuera:
        return escalar(fuera)

    concepto, proc_c, motivo = R.resolver_concepto(v["concepto_texto"], v["unidad_texto"])
    if not concepto:
        prev = tablas.precedente.get(cod)
        if prev:
            motivo += (" Para orientar la respuesta: el mes pasado esta empresa importó "
                       "los conceptos %s." % ", ".join(
                           "%s (%s)" % (c, tablas.conceptos[c]["DESCRIPCION"])
                           for c in sorted(prev)))
        return escalar(motivo)

    valor, nota_valor = R.normalizar_valor(v["valor"])
    if valor is None:
        return escalar(nota_valor)

    fechas, procs_f = {}, []
    for campo, clave in (("fecha_desde", "fecha_inicio"), ("fecha_hasta", "fecha_fin")):
        iso, nota = R.normalizar_fecha(v.get(campo, ""), periodo)
        if iso is None:
            return escalar(nota)
        fechas[clave] = iso
        if nota:
            procs_f.append(nota)

    # Un concepto en DIAS sin fechas lo rechaza el importador: mejor preguntarlo ahora.
    if tablas.conceptos[concepto]["UNIDAD"] == "DIAS" and not (
            fechas["fecha_inicio"] and fechas["fecha_fin"]):
        if fechas["fecha_inicio"] and not fechas["fecha_fin"]:
            fechas["fecha_fin"] = fechas["fecha_inicio"]
            procs_f.append("un solo día: FECHA_FIN = FECHA_INICIO")
        else:
            return escalar("el concepto %s (%s) se mide en DIAS y el importador exige "
                           "FECHA_INICIO y FECHA_FIN; el mensaje no las da."
                           % (concepto, tablas.conceptos[concepto]["DESCRIPCION"]))

    linea = {
        "cod_empresa": cod, "cod_empleado": emp["COD_EMPLEADO"], "cod_concepto": concepto,
        "valor": valor, "observaciones": v["concepto_texto"],
        "trabajador": emp["APELLIDOS_NOMBRE"],
        "concepto_desc": tablas.conceptos[concepto]["DESCRIPCION"],
        "sobre_id": sobre.id, "cita": v["cita_literal"],
        "procedencias": ["empresa: %s" % procedencia_empresa,
                         "trabajador: %s" % proc_t,
                         "concepto: %s" % proc_c] + procs_f,
        "avisos": [], **fechas,
    }
    # Recortar al periodo PRIMERO, contar los días DESPUÉS. Al revés, los días
    # contados no corresponden a las fechas escritas. Y si al recortar el tramo
    # desaparece, se escala: no se cuenta un intervalo invertido.
    bloqueo, avisos_recorte = R.recortar_al_periodo(linea, periodo)
    if bloqueo:
        return escalar(bloqueo)
    linea["avisos"] += avisos_recorte

    # Un concepto en DIAS necesita un número de días; si el cliente no lo dice pero
    # da las fechas, lo cuenta el código (determinista) y lo deja anotado.
    if tablas.conceptos[concepto]["UNIDAD"] == "DIAS" and not linea["valor"]:
        dias = (datetime.date.fromisoformat(linea["fecha_fin"])
                - datetime.date.fromisoformat(linea["fecha_inicio"])).days + 1
        linea["valor"] = str(dias)
        linea["procedencias"].append(
            "el mensaje no da el número de días: contados %d desde %s hasta %s, ambos "
            "incluidos" % (dias, linea["fecha_inicio"], linea["fecha_fin"]))
        linea["avisos"].append(
            "si la fecha de alta significa que la persona SE REINCORPORA ese día, la "
            "baja termina el día anterior y serían %d días. Confirmar." % (dias - 1))

    if nota_valor:
        linea["procedencias"].append(nota_valor)
    if v.get("confianza") == "baja":
        linea["avisos"].append("el lector marcó esta lectura con confianza BAJA.")

    bloqueos, avisos = R.reglas(linea, emp, periodo, tablas)
    if bloqueos:
        return escalar(" · ".join(bloqueos))
    linea["avisos"] += avisos
    acumulador["lineas"].append(linea)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--periodo", default="2026-08")
    p.add_argument("--salida", default=os.path.join(BASE, "propuestas"))
    p.add_argument("--cache", default=os.path.join(BASE, "extraccion"))
    p.add_argument("--proveedor", choices=sorted(EX.PROVEEDORES),
                   help="qué modelo lee los mensajes. Por defecto, el primero que "
                        "tenga clave (nvidia antes que anthropic, por ser gratis)")
    p.add_argument("--extraccion", metavar="JSON",
                   help="usa una extracción de referencia en vez del modelo "
                        "(p.ej. golden/extraccion.json). Prueba las etapas 3-5 sola.")
    a = p.parse_args()

    fijado = None
    if a.extraccion:
        fijado = {k: v for k, v in
                  json.load(open(a.extraccion, encoding="utf-8")).items()
                  if not k.startswith("_")}
        print("  · extracción de referencia: %s (%d mensajes). El modelo NO interviene."
              % (a.extraccion, len(fijado)))

    os.makedirs(a.salida, exist_ok=True)
    print("Preparador de variables · periodo %s" % a.periodo)

    lector = None if fijado else _lector(a.proveedor)
    if lector:
        print("  · lector: %s (%s)" % (EX.PROVEEDORES[lector[0]]["modelo"], lector[0]))
    # La caché cuelga del proveedor. Sin eso, la segunda pasada leería la caché de
    # la primera y la comparación entre lectores no existiría.
    cache = os.path.join(a.cache, lector[0] if lector else "sin-lector", a.periodo)
    # Sin clave, _lector() devuelve None y la etapa 2 para en seco sin escribir nada.
    r = procesar(a.periodo, a.salida, lector, cache, fijado)
    if r is None:
        print("\nInterrumpido en la etapa 2. No se ha escrito ningún lote.")
        return 1

    print("\n" + "=" * 72)
    listos = [x for x in r["lotes"] if x["estado"] == "LISTO"]
    for x in r["lotes"]:
        print("  %-9s %-32s %-11s %2d líneas · %2d escaladas · %d avisos"
              % (x["cod_empresa"], x["denominacion"][:32], x["estado"],
                 x["lineas_propuestas"], x["lineas_escaladas"], x["avisos"]))
    print("=" * 72)
    print("  %d lote(s) LISTO(s), %d mensaje(s) sin encargo de variables."
          % (len(listos), len(r["sin_encargo"])))
    print("\n  Nada se ha depositado en entrada/. Este programa no puede hacerlo.")
    print("  Revisa %s/<empresa>/revision.md y luego:" % os.path.relpath(
        os.path.join(a.salida, a.periodo)))
    for x in listos:
        print("      python3 aprobar.py %s --periodo %s" % (x["cod_empresa"], a.periodo))
    return 0


if __name__ == "__main__":
    sys.exit(main())
