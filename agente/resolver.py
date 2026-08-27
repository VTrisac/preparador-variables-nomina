# -*- coding: utf-8 -*-
"""
Etapas 3 y 4 · IDENTIDAD y REGLAS — 100 % código, cero modelo.

El modelo ha extraído lo que el mensaje DICE. Aquí se decide lo que el sistema
TIENE. La separación es deliberada: un código de trabajador inventado es
indistinguible de uno correcto, así que el modelo nunca ve las tablas maestras y
por tanto no puede inventarse un código.

Regla que gobierna todo el fichero: cuando la resolución es ambigua, se ESCALA.
Nunca se desempata sola. Una línea mala entra en un sistema sin deshacer.
"""
import csv
import datetime
import os
import re

from ingesta import normalizar

BASE = os.path.dirname(os.path.abspath(__file__))
NOMINAS = os.path.join(BASE, "..", "caso-despacho", "sistemas", "nominas")

def _csv(ruta):
    with open(ruta, encoding="cp1252", newline="") as fh:
        return list(csv.DictReader(fh, delimiter=";"))


class Tablas:
    """Los ficheros maestros del software de nóminas, cargados una vez."""

    def __init__(self, raiz=NOMINAS):
        self.empleados = _csv(os.path.join(raiz, "maestro_empleados.csv"))
        self.empresas = _csv(os.path.join(raiz, "equivalencias_empresas.csv"))
        self.conceptos = {f["COD_CONCEPTO"]: f for f in
                          _csv(os.path.join(raiz, "salida", "listado_conceptos.csv"))}
        self.historico = _csv(os.path.join(raiz, "historico", "variables_importadas.csv"))
        # Lo que se importó el mes pasado. No decide nada: acompaña a la escalada
        # para que la persona conteste en un segundo en vez de en una llamada.
        self.precedente = {}
        ref = os.path.join(raiz, "salida", "variables_2026-07.csv")
        if os.path.exists(ref):
            for f in _csv(ref):
                self.precedente.setdefault(f["COD_EMPRESA"], set()).add(f["COD_CONCEPTO"])

        self.por_empresa = {}
        for e in self.empleados:
            self.por_empresa.setdefault(e["COD_EMPRESA"], []).append(e)
        self.cif_a_cod = {e["CIF"]: e["COD_EMPRESA"] for e in self.empresas}
        self.denominacion = {e["COD_EMPRESA"]: e["DENOMINACION"] for e in self.empresas}
        # Las marcas que identifican a cada empresa. El filtro de longitud ya se
        # come las formas jurídicas: "S.L." normaliza a dos tokens de una letra.
        self._marcas = {e["COD_EMPRESA"]: {t for t in normalizar(e["DENOMINACION"]).split()
                                           if len(t) >= 4}
                        for e in self.empresas}


# ------------------------------------------------------------------ 1 · EMPRESA

def _candidatas_por_nombre(texto, tablas):
    """Puntúa empresas por solapamiento de marcas. Devuelve las de puntuación máxima.

    La marca tiene que casar al PRINCIPIO o al FINAL de un token, nunca en medio.
    Con subcadena libre, 'viverspuigcerda' casaba con 'Clínica Veterinària Puig' y el
    sistema habría propuesto meter las variables de un cliente en el fichero de otro.
    """
    fichas = [t for t in normalizar(texto).split() if t]
    if not fichas:
        return [], 0
    puntos = {}
    for cod, marcas in tablas._marcas.items():
        n = sum(1 for m in marcas
                if any(f.startswith(m) or f.endswith(m) for f in fichas))
        if n:
            puntos[cod] = n
    if not puntos:
        return [], 0
    top = max(puntos.values())
    return [c for c, n in puntos.items() if n == top], top


def resolver_empresa(sobre, nombres, tablas, contactos):
    """Cascada con corroboración. Devuelve (cod_empresa, procedencia, motivo_escalada).

    Por qué no basta el dominio: los emails de contacto del gestor están sucios
    (`vilanovalogíst.cat` truncado, `campsmetall.cat` cuando el real es `.com`).
    Solo 3 de 7 dominios del buzón cruzan de forma exacta. Y meter variables de un
    cliente en el fichero de otro es, literalmente, el fin de la relación. Así que
    una sola señal débil nunca resuelve: hacen falta dos independientes.
    """
    # Nivel 1 · el dominio aparece tal cual en los contactos del gestor.
    if sobre.dominio:
        cifs = {c["cif"] for c in contactos
                if c.get("email", "").lower().endswith("@" + sobre.dominio)}
        cods = {tablas.cif_a_cod[c] for c in cifs if c in tablas.cif_a_cod}
        if len(cods) == 1:
            return cods.pop(), "dominio exacto en los contactos del gestor", ""

    # Nivel 2 · la denominación coincide Y la plantilla lo corrobora.
    pista = " ".join([sobre.dominio.rsplit(".", 1)[0] if sobre.dominio else "",
                      sobre.titulo_adjunto, sobre.asunto, sobre.remitente])
    candidatas, fuerza = _candidatas_por_nombre(pista, tablas)

    corroboradas = []
    for cod in candidatas:
        resueltos = [n for n in nombres if len(buscar_trabajador(n, cod, tablas)) >= 1]
        if nombres and len(resueltos) == len(nombres):
            corroboradas.append(cod)

    if len(corroboradas) == 1:
        return (corroboradas[0],
                "denominación (%d coincidencia/s) corroborada por la plantilla "
                "(%d/%d trabajadores existen en esa empresa)"
                % (fuerza, len(nombres), len(nombres)), "")

    if not candidatas:
        return None, "", ("no hay ninguna empresa cuya denominación coincida con "
                          "'%s'. El remitente no está en el maestro de equivalencias."
                          % (sobre.dominio or sobre.remitente))
    return None, "", ("la denominación no basta para decidir entre %s y la plantilla "
                      "no lo corrobora" % ", ".join(
                          "%s (%s)" % (c, tablas.denominacion[c]) for c in candidatas))


# --------------------------------------------------------------- 2 · TRABAJADOR

def _tokens_nombre(s):
    return [t for t in normalizar(s).split() if t]


def buscar_trabajador(texto, cod_empresa, tablas):
    """Candidatos dentro de ESA empresa. El aislamiento es estructural: nunca se
    busca en el maestro entero, así que un nombre de otro cliente no puede colarse."""
    consulta = _tokens_nombre(texto)
    if not consulta:
        return []
    salida = []
    for e in tablas.por_empresa.get(cod_empresa, []):
        tiene = _tokens_nombre(e["APELLIDOS_NOMBRE"])
        if all(any(t == c or (len(c) == 1 and t.startswith(c)) for t in tiene)
               for c in consulta):
            salida.append(e)
    return salida


def resolver_trabajador(texto, cod_empresa, tablas):
    """(empleado, procedencia, motivo_escalada)."""
    cand = buscar_trabajador(texto, cod_empresa, tablas)
    if len(cand) == 1:
        return cand[0], "nombre único en la empresa %s" % cod_empresa, ""
    if not cand:
        return None, "", ("'%s' no existe en el maestro de la empresa %s"
                          % (texto, cod_empresa))

    detalle = ", ".join("%s (%s, NIF %s, alta %s)"
                        % (c["COD_EMPLEADO"], c["APELLIDOS_NOMBRE"], c["NIF"], c["FECHA_ALTA"])
                        for c in cand)
    if len({c["NIF"] for c in cand}) == 1:
        reciente = max(cand, key=lambda c: c["FECHA_ALTA"])
        return None, "", (
            "'%s' tiene %d códigos con el MISMO NIF en la empresa %s: %s. Es la misma "
            "persona con dos fichas (probable cambio de centro). Recomendación: usar %s, "
            "el de alta más reciente. No lo decide el sistema."
            % (texto, len(cand), cod_empresa, detalle, reciente["COD_EMPLEADO"]))
    return None, "", (
        "'%s' es ambiguo en la empresa %s: %d personas distintas encajan — %s. "
        "Hay que preguntar al cliente de cuál se trata."
        % (texto, cod_empresa, len(cand), detalle))


# ----------------------------------------------------------------- 3 · CONCEPTO

# Diccionario escrito a mano (castellano y catalán). Si algo no está aquí, se
# escala: inventar un concepto es el error caro, y el catálogo tiene 17 entradas.
SINONIMOS = {
    "110": ["hores complementaries", "horas complementarias", "complementarias"],
    "205": ["dieta amb pernocta", "dieta con pernocta", "dietes amb pernocta",
            "dietas con pernocta", "pernocta"],
    "206": ["dieta sin pernocta", "dieta sense pernocta", "dietas sin pernocta",
            "dietes sense pernocta"],
    "210": ["kilometraje", "quilometratge", "km", "kilometros", "quilometres"],
    "301": ["nocturnidad", "nocturnitat", "plus de nocturnidad", "plus de nocturnitat"],
    "302": ["peligrosidad", "perillositat"],
    "310": ["comisiones", "comissions"],
    "401": ["ausencia no justificada", "absencia no justificada", "falta injustificada"],
    "402": ["asuntos propios", "assumptes propis", "permiso retribuido", "permis retribuit"],
    "403": ["vacaciones", "vacances", "dias de vacaciones", "dies de vacances"],
    "501": ["baja", "baixa", "incapacidad temporal", "it", "baja medica", "baixa medica",
            "contingencias comunes", "de baja", "de baixa"],
    "502": ["accidente de trabajo", "accident de treball", "accidente laboral"],
    "601": ["anticipo", "avancament", "bestreta", "anticipo a descontar", "avancament a descomptar"],
    "602": ["embargo", "embargament", "embargo judicial"],
    "701": ["prima de produccion", "prima de produccio"],
}
# Horas extra: el código decide 101 (importe) o 102 (horas) según la unidad.
EXTRA = ["horas extra", "hores extres", "horas extraordinarias", "hores extraordinaries",
         "h extra", "horas extras", "extras"]
# "dieta" a secas no dice cuál de las dos es. Ambigüedad real, no fallo.
DIETA_SIN_ESPECIFICAR = ["dieta", "dietes", "dietas"]

SALUD = {"501", "502"}


def resolver_concepto(texto, unidad):
    """(cod_concepto, procedencia, motivo_escalada)."""
    t = normalizar(texto)
    if any(e in t for e in EXTRA):
        if unidad == "importe_eur":
            return "101", "horas extra expresadas en euros -> 101 (IMPORTE)", ""
        if unidad == "horas":
            return "102", "horas extra expresadas en horas -> 102 (HORAS)", ""
        return None, "", ("'%s' son horas extra pero no se sabe si el valor son horas "
                          "(102) o euros (101). El importador no lo distingue y el "
                          "importe resultante sería otro." % texto)

    mejor, largo = None, 0
    for cod, formas in SINONIMOS.items():
        for f in formas:
            if f in t and len(f) > largo:
                mejor, largo = cod, len(f)
    if mejor:
        return mejor, "sinónimo '%s' del catálogo" % t, ""

    if any(d == t or t.startswith(d + " ") for d in DIETA_SIN_ESPECIFICAR):
        return None, "", ("'%s' no dice si es dieta CON pernocta (205) o SIN pernocta "
                          "(206). Son conceptos y cuantías distintas." % texto)

    return None, "", ("'%s' no corresponde a ninguno de los 17 conceptos del catálogo. "
                      "Inventar un código sería peor que preguntar." % texto)


# -------------------------------------------------------------------- 4 · FECHAS

EPOCA_EXCEL = datetime.date(1899, 12, 30)


def normalizar_fecha(txt, periodo):
    """Devuelve (AAAA-MM-DD, procedencia) o (None, motivo)."""
    t = (txt or "").strip()
    if not t:
        return "", ""
    anio, mes = int(periodo[:4]), int(periodo[5:7])

    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", t):
        return t, ""
    if re.fullmatch(r"4\d{4}", t):            # serial de Excel
        d = EPOCA_EXCEL + datetime.timedelta(days=int(t))
        return d.isoformat(), "serial de Excel %s -> %s" % (t, d.isoformat())
    m = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?", t)
    if m:
        d, mm = int(m.group(1)), int(m.group(2))
        a = m.group(3)
        a = int(a) + 2000 if a and len(a) == 2 else (int(a) if a else anio)
        try:
            return datetime.date(a, mm, d).isoformat(), ""
        except ValueError:
            return None, "la fecha '%s' no existe" % t
    if re.fullmatch(r"\d{1,2}", t):           # "el 21" -> día del periodo
        try:
            d = datetime.date(anio, mes, int(t))
            return d.isoformat(), "día suelto '%s' interpretado en el periodo %s" % (t, periodo)
        except ValueError:
            return None, "el día '%s' no existe en el periodo %s" % (t, periodo)
    return None, "no se ha podido interpretar la fecha '%s'" % t


# ------------------------------------------------------- 5 · REGLAS DE NEGOCIO

def normalizar_valor(valor):
    """Devuelve (valor con coma decimal, nota) o (None, motivo de escalada).

    El importador acepta el punto decimal —`float('6.5'.replace('.',''))` da 65— y
    guarda en el histórico la cadena SIN normalizar. Un '6.5' entraría multiplicado
    por cien, sin error y sin deshacer. Así que aquí se arregla una vez, antes de
    escribir nada, en vez de rechazarlo en cada llamador.

    Convención es-ES: el punto separa miles, la coma decimales.
    """
    v = (valor or "").strip().replace(" ", "").replace("€", "")
    if not v:
        return "", ""
    if "," in v:                                  # la coma manda: el punto es de miles
        limpio = v.replace(".", "")
        return (limpio, "punto de millar eliminado: '%s' -> '%s'" % (v, limpio)) \
            if "." in v else (v, "")
    m = re.fullmatch(r"(-?\d+)\.(\d+)", v)
    if m:
        if len(m.group(2)) == 3:                  # 1.500 -> mil quinientos
            return m.group(1) + m.group(2), \
                "'%s' interpretado como millar (convención es-ES) -> '%s%s'" % (
                    v, m.group(1), m.group(2))
        limpio = "%s,%s" % (m.group(1), m.group(2))
        return limpio, ("'%s' llevaba punto decimal. El importador lo aceptaría y lo "
                        "guardaría como '%s%s' (x100). Normalizado a '%s'."
                        % (v, m.group(1), m.group(2), limpio))
    if re.fullmatch(r"-?\d+", v):
        return v, ""
    return None, "el valor '%s' no es un número que el importador vaya a aceptar" % valor


def _num(valor):
    """Forma canónica de un número para compararlo: '8', '8,00' y '8.0' son el mismo.

    Sin esto, el mismo importe escrito de dos formas pasa por dos variables distintas
    y el duplicado no se detecta — que es justo lo que el importador tampoco hace.
    """
    v = (valor or "").strip().replace(" ", "").replace(".", "").replace(",", ".")
    try:
        return "%.4f" % float(v)
    except ValueError:
        return v.lower()


def clave_idempotencia(empresa, empleado, concepto, valor, ini="", fin=""):
    """Qué hace que dos variables sean «la misma» a efectos de no importarla dos veces.

    Las fechas forman parte de la clave. Sin ellas, la baja de septiembre del mismo
    trabajador con los mismos días se bloqueaba como duplicada de la de agosto: un
    falso positivo que impide trabajo legítimo.
    """
    return (empresa, empleado, concepto, _num(valor),
            (ini or "").strip(), (fin or "").strip())


def del_historico(fila):
    """La misma clave, leída de una fila del histórico del software de nóminas."""
    return clave_idempotencia(fila["COD_EMPRESA"], fila["COD_EMPLEADO"],
                              fila["COD_CONCEPTO"], fila["VALOR"],
                              fila.get("FECHA_INICIO", ""), fila.get("FECHA_FIN", ""))


def fin_de_periodo(periodo):
    return ((datetime.date(int(periodo[:4]), int(periodo[5:7]), 28)
             + datetime.timedelta(days=4)).replace(day=1) - datetime.timedelta(days=1))


def recortar_al_periodo(linea, periodo):
    """Una baja a caballo de dos meses solo entra por el tramo de ESTE periodo.

    Devuelve (bloqueo, avisos). Bloqueo = el tramo declarado no toca este periodo.

    Tiene que correr ANTES de contar los días: si no, se cuentan los del tramo
    declarado y se escriben junto a las fechas recortadas.

    Y tiene que comprobar que el intervalo SIGUE EXISTIENDO después de recortarlo.
    No hacerlo era un fallo con dientes: una baja íntegramente en el mes anterior
    dejaba fecha_inicio recortada al día 1 y fecha_fin intacta en el mes pasado, y
    el conteo daba días NEGATIVOS. El importador acepta un valor negativo sin
    pestañear —`float('-16')` parsea— así que habría entrado en la nómina.
    """
    avisos = []
    declarado_ini, declarado_fin = linea["fecha_inicio"], linea["fecha_fin"]
    ini, fin = "%s-01" % periodo, fin_de_periodo(periodo).isoformat()

    if linea["fecha_inicio"] and linea["fecha_inicio"] < ini:
        avisos.append("el periodo declarado empieza el %s, antes de %s. Recortado a %s: "
                      "el mes anterior ya está cerrado y reabrirlo es decisión de la "
                      "persona, no del sistema." % (linea["fecha_inicio"], ini, ini))
        linea["fecha_inicio"] = ini
    if linea["fecha_fin"] and linea["fecha_fin"] > fin:
        avisos.append("la fecha fin %s cae fuera del periodo; recortada a %s."
                      % (linea["fecha_fin"], fin))
        linea["fecha_fin"] = fin

    if (linea["fecha_inicio"] and linea["fecha_fin"]
            and linea["fecha_inicio"] > linea["fecha_fin"]):
        return ("el tramo declarado (%s a %s) no cae dentro del periodo %s: pertenece "
                "al periodo anterior, que ya está cerrado. Reabrirlo es decisión de "
                "una persona." % (declarado_ini, declarado_fin, periodo), avisos)
    return "", avisos


def estado_laboral(empleado, periodo):
    """¿Estaba esta persona en plantilla durante el periodo? Se comprueba nada más
    resolver al trabajador, antes que el concepto: que esté de baja es un motivo más
    fundamental y más útil para quien lee la incidencia.

    `importador.validar()` NO mira esto. Lo hemos ejecutado: una línea de un trabajador
    dado de baja pasa su validación sin una queja.
    """
    ini, fin = "%s-01" % periodo, fin_de_periodo(periodo).isoformat()
    baja = (empleado.get("FECHA_BAJA") or "").strip()
    if baja and baja < ini:
        return ("%s (%s) está DE BAJA desde %s, anterior al periodo %s. El importador no "
                "lo comprueba: esta línea entraría sin protestar."
                % (empleado["COD_EMPLEADO"], empleado["APELLIDOS_NOMBRE"], baja, periodo))
    alta = (empleado.get("FECHA_ALTA") or "").strip()
    if alta and alta > fin:
        return ("%s tiene fecha de alta %s, posterior al periodo %s."
                % (empleado["COD_EMPLEADO"], alta, periodo))
    return ""


def reglas(linea, empleado, periodo, tablas):
    """Devuelve (bloqueos, avisos). Bloqueo = la línea no entra en el lote.

    Todo lo de aquí es lo que `importador.validar()` NO comprueba. Lo sabemos
    porque lo hemos ejecutado: un trabajador de baja pasa su validación sin queja.
    """
    bloqueos, avisos = [], []
    ini_periodo = "%s-01" % periodo
    fin_periodo = fin_de_periodo(periodo)

    # Cinturón: ningún punto decimal puede llegar hasta aquí (ver normalizar_valor).
    assert not re.search(r"\d\.\d", linea["valor"]), linea["valor"]

    cod = linea["cod_concepto"]
    unidad = tablas.conceptos[cod]["UNIDAD"]
    if cod in SALUD:
        avisos.append("DATO DE SALUD (concepto %s). Categoría especial: en este informe "
                      "constan fechas, nunca diagnóstico." % cod)

    try:
        num = float(_num(linea["valor"]))
    except ValueError:
        num = None
    if num is not None:
        # Cinturón: ningún negativo llega jamás al CSV. No hay concepto del catálogo
        # donde tenga sentido —el 601 se registra en positivo, lo dice su propio
        # aviso— y el importador los acepta sin protestar. Una línea, toda la familia.
        if num < 0:
            bloqueos.append("el valor '%s' es negativo. Ningún concepto del catálogo "
                            "admite negativos, y el importador lo aceptaría igualmente."
                            % linea["valor"])
        if unidad == "HORAS" and num > 80:
            avisos.append("%s horas en un mes es mucho; revisar." % linea["valor"])
        if unidad == "IMPORTE" and num > 3000:
            avisos.append("%s € es un importe alto; revisar." % linea["valor"])
        if cod == "601":
            avisos.append("Anticipo a descontar: se registra como importe positivo en el "
                          "concepto 601, que ya es de signo negativo en nómina.")

    # Idempotencia contra lo ya importado: el importador duplica sin avisar.
    clave = clave_idempotencia(linea["cod_empresa"], linea["cod_empleado"], cod,
                               linea["valor"], linea["fecha_inicio"], linea["fecha_fin"])
    for h in tablas.historico:
        if del_historico(h) == clave:
            bloqueos.append("ya existe esta misma variable en el histórico (importada el "
                            "%s desde %s). El importador la duplicaría."
                            % (h["TS_IMPORTACION"], h["FICHERO"]))
            break
    return bloqueos, avisos
