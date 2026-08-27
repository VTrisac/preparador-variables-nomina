# -*- coding: utf-8 -*-
"""
Cómo sabemos que funciona, y dónde está el límite.

    python3 evaluar.py

Dos cosas distintas, deliberadamente separadas:

  GOLDEN SET — se ejecuta la tubería completa sobre una extracción de referencia
  escrita a mano y se compara con la salida esperada, también escrita a mano. Como
  el modelo no interviene, mide EL CÓDIGO: identidad, conceptos, fechas, reglas.
  Incluye lo que NO debe producir línea, que es la mitad del valor.

  INVARIANTES — cuatro propiedades que tienen que cumplirse en CUALQUIER ejecución,
  no solo sobre el golden. Se comprueban también en producción, sobre los lotes que
  haya en `propuestas/`.

La métrica que importa no es la cobertura: es el FALSO POSITIVO — una línea
propuesta que un humano habría rechazado. Son las únicas que acaban en un sistema
sin deshacer. Objetivo cero, aunque cueste cobertura.
"""
import json
import os
import shutil
import sys
import tempfile

import agente as A
from ingesta import ingerir, normalizar
from validar_seco import validar_en_seco

BASE = os.path.dirname(os.path.abspath(__file__))
PERIODO = "2026-08"


def _linea_clave(csv):
    """Los 6 primeros campos. OBSERVACIONES es texto libre y no se compara."""
    return ";".join(csv[:6])


def golden(salida):
    esperado = json.load(open(os.path.join(BASE, "golden", "esperado.json"),
                              encoding="utf-8"))[PERIODO]
    fijado = {k: v for k, v in json.load(
        open(os.path.join(BASE, "golden", "extraccion.json"), encoding="utf-8")).items()
        if not k.startswith("_")}

    r = A.procesar(PERIODO, salida, lector=None, cache=None, fijado=fijado)
    lotes = {x["cod_empresa"]: x for x in r["lotes"]}
    fallos = []

    for cod, exp in esperado["lotes"].items():
        got = lotes.get(cod)
        if not got:
            fallos.append("falta el lote %s" % cod)
            continue
        if got["estado"] != exp["estado"]:
            fallos.append("%s: estado %s, esperado %s" % (cod, got["estado"], exp["estado"]))

        vistas = [_linea_clave(l["csv"]) for l in got["lineas"]]
        for e in exp["lineas"]:
            if e not in vistas:
                fallos.append("%s: FALTA la línea esperada  %s" % (cod, e))
        for v in vistas:
            if v not in exp["lineas"]:
                fallos.append("%s: FALSO POSITIVO, línea no esperada  %s" % (cod, v))

        pendientes = list(got["escaladas"])
        for origen, trozo in exp["escaladas"]:
            hit = next((x for x in pendientes
                        if x["origen"] == origen and trozo in (x["dato"] + x["motivo"])), None)
            if hit:
                pendientes.remove(hit)
            else:
                fallos.append("%s: no se escaló lo que debía — %s / %s" % (cod, origen, trozo))
        for x in pendientes:
            fallos.append("%s: escalada inesperada — %s" % (cod, x["dato"]))

    sobrantes = set(lotes) - set(esperado["lotes"])
    fallos += ["lote inesperado: %s" % c for c in sorted(sobrantes)]

    ids_sin = {x[0] for x in r["sin_encargo"]}
    for m in esperado["sin_encargo"]:
        if m not in ids_sin:
            fallos.append("%s debía quedarse sin encargo y no lo hizo" % m)

    return r, lotes, fallos


def invariantes(salida, sobres, lotes):
    """Cuatro propiedades que se comprueban en cada ejecución, no solo en el test."""
    res = []

    fallos = []
    for cod, l in lotes.items():
        if l["estado"] != "LISTO":
            continue
        csv = os.path.join(salida, PERIODO, cod, "variables.csv")
        for n, _, e in validar_en_seco(csv):
            fallos.append("%s línea %d: %s" % (cod, n, e))
    res.append(("ninguna línea propuesta falla la validación del importador", fallos))

    mezclados = [cod for cod, l in lotes.items()
                 for x in l["lineas"] if x["csv"][0] != cod and cod != "SIN_EMPRESA"]
    res.append(("ningún lote contiene dos empresas", mezclados))

    conocidos = {s.id for s in sobres}
    sin_traza = ["%s: %s" % (cod, x["csv"])
                 for cod, l in lotes.items() for x in l["lineas"]
                 if not x["cita"].strip() or x["origen"] not in conocidos]
    res.append(("toda línea cita literalmente un mensaje real del buzón", sin_traza))

    huellas, repes = {}, []
    for s in sobres:
        if not s.procesable:
            continue
        for h in s.huellas:
            if h in huellas:
                repes.append("%s repite el adjunto de %s" % (s.id, huellas[h]))
            huellas[h] = s.id
    res.append(("ningún adjunto se procesa dos veces", repes))
    return res


def seguridad(sobres, lotes, esperado):
    """Las tres inyecciones: detectadas, y sobre todo SIN efecto en ninguna línea."""
    fallos = []
    inc = {s.id: " ".join(s.incidencias) for s in sobres}
    for origen, marca in esperado["inyecciones"]:
        if marca not in inc.get(origen, ""):
            fallos.append("no se detectó la inyección de %s" % origen)

    prohibido = esperado["concepto_prohibido"]
    for cod, l in lotes.items():
        for x in l["lineas"]:
            if x["csv"][2] == prohibido:
                fallos.append("¡la inyección funcionó! concepto %s en %s" % (prohibido, cod))
    return fallos


def todo_o_nada(tmp):
    """La propiedad que justifica todo el diseño: si UNA sola línea fallaría la
    validación del importador, no se genera fichero aprobable.

    Ningún mensaje del buzón la provoca, así que se comprueba a propósito. Sin esto,
    el importador confirmaría las buenas y se detendría en la mala, dejando media
    nómina dentro y sin deshacer.
    """
    from lote import escribir_lote
    def l(empleado, valor="8,00", concepto="102"):
        return {"cod_empresa": "0087", "cod_empleado": empleado, "cod_concepto": concepto,
                "valor": valor, "fecha_inicio": "", "fecha_fin": "", "observaciones": "t",
                "trabajador": "X", "concepto_desc": "Y", "sobre_id": "test", "cita": "t",
                "procedencias": [], "avisos": []}

    fallos = []
    buenas = [l("00014"), l("00021")]
    r = escribir_lote(tmp, PERIODO, "0087", "test", buenas, [], [])
    if r["estado"] != "LISTO":
        fallos.append("un lote correcto debería quedar LISTO y quedó %s" % r["estado"])

    # La mala va en MEDIO: el importador confirmaría la primera y pararía en la segunda.
    con_mala = [l("00014"), l("00099"), l("00021")]
    r = escribir_lote(tmp, PERIODO, "0087", "test", con_mala, [], [])
    csv = os.path.join(tmp, PERIODO, "0087", "variables.csv")
    if r["estado"] != "BLOQUEADO":
        fallos.append("un lote con una línea mala debería quedar BLOQUEADO y quedó %s"
                      % r["estado"])
    if os.path.exists(csv):
        fallos.append("existe variables.csv en un lote BLOQUEADO: aprobar.py podría "
                      "depositarlo")

    # Un carácter fuera de cp1252 tumba el fichero entero en el importador.
    r = escribir_lote(tmp, PERIODO, "0087", "test",
                      [dict(l("00014"), observaciones="Kowałski")], [], [])
    if r["estado"] != "BLOQUEADO":
        fallos.append("un carácter no representable en cp1252 debería BLOQUEAR el lote")
    return fallos


def _firma(v):
    """Identidad de una variable leída: el HECHO, no la redacción.

    Casar por `concepto_texto` no vale: «AUSENCIAS», «asuntos propios» y
    «va estar de baixa» son la misma variable dicha de tres formas, y eso es
    justo lo que cambia entre lectores. Por `unidad_texto` tampoco: en una baja sin
    número de días un lector dice «dias» y otro «desconocida», y da igual, porque la
    unidad real la pone el catálogo de conceptos, no el modelo.

    El hecho es: de quién, cuánto y entre qué fechas. La redacción y la unidad se
    comparan aparte, porque son las que deciden si el diccionario lo reconoce.
    """
    nombre = normalizar(v.get("trabajador_texto", "")).split()
    return (nombre[0] if nombre else "", v.get("valor", "").strip(),
            v.get("fecha_desde", "").strip(), v.get("fecha_hasta", "").strip())


def lectura():
    """Mide LA LECTURA del modelo, no el código: compara cada extracción grabada en
    `extraccion/<proveedor>/<periodo>/` con la de referencia escrita a mano.

    Es la otra mitad de la evaluación y es deliberadamente aparte. Si el modelo lee
    16 donde pone 6, se arregla el prompt; si el código asigna 205 donde tocaba 206,
    se arregla el diccionario. Un test que mezcla las dos cosas no dice cuál se rompió.
    """
    ref = {k: v for k, v in json.load(
        open(os.path.join(BASE, "golden", "extraccion.json"), encoding="utf-8")).items()
        if not k.startswith("_")}

    raiz = os.path.join(BASE, "extraccion")
    if not os.path.isdir(raiz):
        return []

    informes = []
    for proveedor in sorted(os.listdir(raiz)):
        carpeta = os.path.join(raiz, proveedor, PERIODO)
        if not os.path.isdir(carpeta):
            continue
        modelo, faltan, sobran, difieren, casadas = proveedor, [], [], [], 0
        for nombre in sorted(os.listdir(carpeta)):
            mid = nombre[:-5]
            if mid not in ref:
                continue
            d = json.load(open(os.path.join(carpeta, nombre), encoding="utf-8"))
            modelo = d.get("modelo", proveedor)
            leidas = {_firma(v): v for v in d["variables"]}
            esperadas = {_firma(v): v for v in ref[mid]["variables"]}
            for f, v in esperadas.items():
                if f not in leidas:
                    faltan.append("%s · %s %s = %s" % (mid, v["trabajador_texto"],
                                                       v["concepto_texto"],
                                                       v.get("valor", "")))
                    continue
                casadas += 1
                otro = leidas[f]
                for campo in ("concepto_texto", "unidad_texto"):
                    if (otro.get(campo, "").strip().lower()
                            != v.get(campo, "").strip().lower()):
                        difieren.append("%s · %s · %s: dijo «%s», la referencia dice «%s»"
                                        % (mid, v["trabajador_texto"], campo,
                                           otro.get(campo), v.get(campo)))
            for f, v in leidas.items():
                if f not in esperadas:
                    sobran.append("%s · %s %s = %s" % (mid, v["trabajador_texto"],
                                                       v["concepto_texto"],
                                                       v.get("valor", "")))
        total = sum(len(x["variables"]) for k, x in ref.items())
        informes.append({"modelo": modelo, "casadas": casadas, "total": total,
                         "faltan": faltan, "sobran": sobran, "difieren": difieren})
    return informes


def regresiones():
    """Los cinco defectos que encontró la auditoría forense del 27-08-2026.

    Cada uno falla sin su arreglo. Están aquí y no en el golden porque ninguno lo
    provoca el buzón: son casos que solo aparecen con datos que todavía no han
    llegado. Y esa es justo la lección — el arnés daba «todo en verde» sobre los
    cinco, porque medía lo que yo había pensado medir.
    """
    import aprobar as AP
    import extraer as EX
    import resolver as R
    t = R.Tablas()
    fallos = []

    def check(cond, msg):
        if not cond:
            fallos.append(msg)

    empleado = {"COD_EMPLEADO": "00058", "APELLIDOS_NOMBRE": "NDIAYE, FATOU",
                "FECHA_ALTA": "2020-01-13", "FECHA_BAJA": ""}

    def linea(valor, ini="", fin="", concepto="501"):
        return {"cod_empresa": "0091", "cod_empleado": "00058",
                "cod_concepto": concepto, "valor": valor,
                "fecha_inicio": ini, "fecha_fin": fin, "avisos": []}

    # R1 · una baja del mes anterior no puede producir días negativos.
    l = linea("", "2026-07-01", "2026-07-15")
    bloqueo, _ = R.recortar_al_periodo(l, "2026-08")
    check(bloqueo, "R1: un tramo íntegramente en el mes anterior debería bloquear; "
                   "sin ese bloqueo se cuentan días negativos con fechas invertidas")
    b, _ = R.reglas(linea("-16", "2026-08-01", "2026-08-12"), empleado, "2026-08", t)
    check(b, "R1: un VALOR negativo debería bloquear la línea; el importador lo acepta")

    # R2 · el histórico manda sobre nuestra contabilidad.
    fantasma = {"importacion": {"ts": "2026-08-27T16:46:26", "resultado": "OK"},
                "lineas": [{"csv": ["0091", "00058", "501", "12",
                                    "2026-08-01", "2026-08-12", "x"]}]}
    check(not AP.ya_en_historico(fantasma),
          "R2: un lote que consta importado pero cuyas líneas no están en el histórico "
          "NO debe darse por importado — con el entorno restaurado, aprobar.py se "
          "quedaba mudo")

    # R3 · dos bajas del mismo trabajador en meses distintos son dos cosas.
    t.historico = [{"TS_IMPORTACION": "t", "FICHERO": "f", "COD_EMPRESA": "0091",
                    "COD_EMPLEADO": "00058", "COD_CONCEPTO": "501", "VALOR": "12",
                    "FECHA_INICIO": "2026-08-01", "FECHA_FIN": "2026-08-12"}]
    b, _ = R.reglas(linea("12", "2026-09-05", "2026-09-16"), empleado, "2026-09", t)
    check(not b, "R3: una baja de otro mes se estaba bloqueando como duplicada")

    # R4 · el mismo importe escrito de dos formas es el mismo importe.
    t.historico = [{"TS_IMPORTACION": "t", "FICHERO": "f", "COD_EMPRESA": "0091",
                    "COD_EMPLEADO": "00058", "COD_CONCEPTO": "110", "VALOR": "8",
                    "FECHA_INICIO": "", "FECHA_FIN": ""}]
    b, _ = R.reglas(linea("8,00", concepto="110"), empleado, "2026-08", t)
    check(b, "R4: '8' y '8,00' son el mismo valor y el duplicado debe detectarse")

    # R5 · un fixture incompleto da mensaje, no KeyError.
    try:
        vs, notas, _ = EX._validado(
            {"variables": [{"trabajador_texto": "X", "concepto_texto": "Y"}],
             "notas_del_lector": ""}, "prueba", "prueba.eml")
        check(vs == [] and "DESCARTADAS" in notas,
              "R5: una variable a la que le faltan campos debe descartarse con aviso")
    except Exception as ex:
        fallos.append("R5: un fixture incompleto reventó con %s en vez de dar un "
                      "mensaje" % type(ex).__name__)
    return fallos


def main():
    salida = tempfile.mkdtemp(prefix="eval-")
    try:
        esperado = json.load(open(os.path.join(BASE, "golden", "esperado.json"),
                                  encoding="utf-8"))[PERIODO]
        r, lotes, fallos_g = golden(salida)
        sobres = ingerir(os.path.join(A.BUZON, PERIODO))
        inv = invariantes(salida, sobres, lotes)
        seg = seguridad(sobres, lotes, esperado)
        ton = todo_o_nada(os.path.join(salida, "todo-o-nada"))
        reg = regresiones()
        lec = lectura()
    finally:
        shutil.rmtree(salida, ignore_errors=True)

    print("\n" + "=" * 72)
    print("GOLDEN SET — la tubería determinista contra la salida escrita a mano")
    print("=" * 72)
    esperadas = sum(len(v["lineas"]) for v in esperado["lotes"].values())
    propuestas = sum(len(l["lineas"]) for l in lotes.values())
    falsos = [f for f in fallos_g if "FALSO POSITIVO" in f]
    print("  %d líneas esperadas · %d propuestas · %d falso(s) positivo(s)"
          % (esperadas, propuestas, len(falsos)))
    for f in fallos_g:
        print("    ✗ %s" % f)
    if not fallos_g:
        print("    ✓ coincide exactamente, incluidas las 11 escaladas")

    print("\n" + "=" * 72)
    print("INVARIANTES — se comprueban en cada ejecución, no solo aquí")
    print("=" * 72)
    for nombre, malos in inv:
        print("  %s %s" % ("✓" if not malos else "✗", nombre))
        for m in malos:
            print("      %s" % m)

    print("\n" + "=" * 72)
    print("TODO-O-NADA — un importador sin transacción, convertido en atómico desde fuera")
    print("=" * 72)
    print("  %s una sola línea mala impide que exista fichero aprobable"
          % ("✓" if not ton else "✗"))
    for t in ton:
        print("      %s" % t)

    print("\n" + "=" * 72)
    print("REGRESIONES — los cinco defectos de la auditoría del 27-08-2026")
    print("=" * 72)
    print("  %s los cinco casos que el arnés no comprobaba" % ("✓" if not reg else "✗"))
    for x in reg:
        print("      %s" % x)

    print("\n" + "=" * 72)
    print("LECTURA — qué leyó cada modelo, contra la extracción de referencia")
    print("=" * 72)
    if not lec:
        print("  sin medir: no hay extracciones grabadas en extraccion/.")
        print("  Ejecuta `agente.py --proveedor nvidia` (o anthropic) para generarlas.")
    for i in lec:
        print("  %s" % i["modelo"])
        print("     %d/%d hechos leídos igual · %d no leídos · %d inventados · %d con "
              "otra redacción" % (i["casadas"], i["total"], len(i["faltan"]),
                                  len(i["sobran"]), len(i["difieren"])))
        for x in i["faltan"]:
            print("     ✗ NO LEYÓ:    %s" % x)
        for x in i["sobran"]:
            print("     ! DE MÁS:     %s" % x)
        for x in i["difieren"]:
            print("     ~ redacción:  %s" % x)

    print("\n" + "=" * 72)
    print("SEGURIDAD — las tres inyecciones plantadas en el buzón")
    print("=" * 72)
    print("  %s detectadas las 3 y ninguna produjo una sola línea"
          % ("✓" if not seg else "✗"))
    for s in seg:
        print("      %s" % s)

    total = fallos_g + [m for _, malos in inv for m in malos] + seg + ton + reg
    print("\n" + "=" * 72)
    if total:
        print("  %d problema(s). Ver arriba." % len(total))
    else:
        print("  Todo en verde.")
    print("""
  DÓNDE ESTÁ EL LÍMITE — dicho en claro:
   · De 8 encargos reales, se proponen 6 lotes y se escala 1 entero.
   · De 30 variables leídas, 18 llegan a línea y 11 se escalan. Ese 37 % de
     escalada no es un fallo: son dudas que un humano tiene que resolver igual.
   · El golden mide EL CÓDIGO. La lectura del modelo se mide aparte, comparando
     `extraccion/` (lo que dijo el modelo) con `golden/extraccion.json`.
   · No cubre: contabilidad, cierre trimestral, ni escrituras en el gestor.
   · El fallo que este sistema NO detectaría: que el cliente se equivoque al
     escribir. Si Vilanova pone 12 horas donde eran 2, entra un 12 bien trazado.""")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
