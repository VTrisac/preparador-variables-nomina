# -*- coding: utf-8 -*-
"""
Etapa 1 · INGESTA — de la carpeta del buzón a "sobres" normalizados.

Todo lo que hay aquí es código determinista. El modelo todavía no ha visto nada,
y ese es el punto: las tres inyecciones plantadas en el entorno se neutralizan en
esta etapa, por construcción y no por buena conducta del modelo.

  · HTML   -> se descarta lo que un humano no puede ver (texto blanco, 1px, display:none).
  · XLSX   -> se lee SOLO el rango contiguo de la tabla. Lo que hay fuera es incidencia.
  · Reenvíos -> lo que viene debajo de un separador de reenvío no es un encargo.
  · Ficheros sin remitente identificable no generan encargo.
"""
import email
import email.policy
import hashlib
import html as _html
import io
import os
import re
import unicodedata
import zipfile
from dataclasses import dataclass, field
from html.parser import HTMLParser

# --------------------------------------------------------------------------- sobre

@dataclass
class Sobre:
    id: str
    remitente: str
    dominio: str
    fecha: str
    asunto: str
    texto: str                        # cuerpo ya limpio, lo único que verá el modelo
    tabla: list = field(default_factory=list)      # filas del xlsx (lista de listas)
    imagenes: list = field(default_factory=list)   # (media_type, bytes)
    huellas: list = field(default_factory=list)    # sha256 de los adjuntos
    incidencias: list = field(default_factory=list)
    titulo_adjunto: str = ""          # título de la hoja: corrobora la empresa
    descartado: str = ""              # motivo, si no debe procesarse

    @property
    def procesable(self):
        return not self.descartado


# ------------------------------------------------------------------- HTML visible

INVISIBLE = re.compile(
    r"color\s*:\s*#(f{3}|f{6}|ffffff)\b"
    r"|font-size\s*:\s*[01](\.\d+)?(px|pt)\b"
    r"|display\s*:\s*none"
    r"|visibility\s*:\s*hidden"
    r"|opacity\s*:\s*0(\.0+)?\b",
    re.I,
)


class _SoloVisible(HTMLParser):
    """Extrae el texto que un humano vería. Lo oculto se aparta, no se ignora."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.visible, self.oculto, self._prof = [], [], 0

    def handle_starttag(self, tag, attrs):
        estilo = dict(attrs).get("style") or ""
        if self._prof or INVISIBLE.search(estilo):
            self._prof += 1
        elif tag in ("br", "p", "li", "div", "tr"):
            self.visible.append("\n")

    def handle_endtag(self, tag):
        if self._prof:
            self._prof -= 1

    def handle_data(self, data):
        (self.oculto if self._prof else self.visible).append(data)


def html_a_texto(html):
    p = _SoloVisible()
    p.feed(html)
    oculto = " ".join(x.strip() for x in p.oculto if x.strip())
    return "".join(p.visible), oculto


# ------------------------------------------------------------------------- XLSX

_REF = re.compile(r'r="([A-Z]+)(\d+)"')


def _col(letras):
    n = 0
    for c in letras:
        n = n * 26 + ord(c) - 64
    return n - 1


def leer_xlsx(datos_bytes):
    """Devuelve (filas del bloque contiguo, contexto, celdas sospechosas).

    `contexto` son las celdas por encima de la cabecera: el título de la hoja, que
    es información legítima y además corrobora de qué empresa hablamos.
    `sospechosas` es todo lo demás que hay fuera del bloque: nadie escribe ahí por
    accidente. Ahí es donde aparece la inyección del entorno (celda AZ80).

    ponytail: parseo XML a mano con re en vez de openpyxl. El fichero lo generamos
    nosotros no, pero es OOXML estándar y solo necesitamos valores de celda. Y el
    adjunto se abre en memoria: escribirlo a disco dejaba el Excel del cliente suelto
    en la carpeta de salida.
    """
    z = zipfile.ZipFile(io.BytesIO(datos_bytes))
    sst = []
    if "xl/sharedStrings.xml" in z.namelist():
        # `_html.unescape` es imprescindible: el xlsx guarda «Peña» como «Pe&#241;a»
        # en el XML. Sin deshacerlo, al modelo le llega el nombre roto, no resuelve
        # contra el maestro y la empresa entera acaba escalada. Lo encontró la
        # primera pasada con un lector real; el golden escrito a mano lo tapaba.
        sst = [_html.unescape(re.sub(r"<[^>]+>", "", s))
               for s in re.findall(r"<si>(.*?)</si>",
                                   z.read("xl/sharedStrings.xml").decode(), re.S)]

    hojas = sorted(n for n in z.namelist() if n.startswith("xl/worksheets/sheet"))
    celdas = {}
    for row in re.findall(r"<row[^>]*>(.*?)</row>", z.read(hojas[0]).decode(), re.S):
        for attrs, inner in re.findall(r"<c ([^>]*?)(?:/>|>(.*?)</c>)", row, re.S):
            m = _REF.search(attrs)
            if not m:
                continue
            v = re.search(r"<v>(.*?)</v>", inner or "", re.S)
            val = _html.unescape(v.group(1) if v else re.sub(r"<[^>]+>", "", inner or ""))
            if 't="s"' in attrs and val.isdigit():
                val = sst[int(val)]
            if val.strip():
                celdas[(int(m.group(2)), _col(m.group(1)))] = val.strip()

    if not celdas:
        return [], [], []

    # Cabecera = primera fila con >= 3 celdas pobladas. El bloque son las filas
    # contiguas siguientes, dentro de las columnas de la cabecera.
    por_fila = {}
    for (f, c), v in celdas.items():
        por_fila.setdefault(f, {})[c] = v
    cab = next((f for f in sorted(por_fila) if len(por_fila[f]) >= 3), None)
    if cab is None:
        return [], [], [v for v in celdas.values()]

    cols = sorted(por_fila[cab])
    filas, f = [], cab
    while f in por_fila and any(por_fila[f].get(c) for c in cols):
        filas.append([por_fila[f].get(c, "") for c in cols])
        f += 1
    ultima = f - 1

    contexto, sospechosas = [], []
    for (fi, co), v in sorted(celdas.items()):
        if cab <= fi <= ultima and co in cols:
            continue
        (contexto if fi < cab else sospechosas).append(v)
    return filas, contexto, sospechosas


# ------------------------------------------------------------------- correo / texto

SEPARADOR_REENVIO = re.compile(
    r"^\s*-{2,}\s*(mensaje reenviado|forwarded message|missatge reenviat)\s*-{2,}\s*$",
    re.I | re.M,
)


def recortar_reenvio(texto):
    """Lo que va debajo de un separador de reenvío es contexto ajeno, no un encargo.

    Regla única y sin heurística de contenido: nos quedamos con el primer bloque.
    Resuelve el caso del mensaje 06, que arrastra datos salariales confidenciales
    de otra gestoría sobre una empresa que no es cliente.
    """
    partes = SEPARADOR_REENVIO.split(texto, maxsplit=1)
    if len(partes) == 1:
        propio, ajeno = texto, ""
    else:
        propio, ajeno = partes[0], partes[-1]
    # Las líneas citadas con '>' tampoco son encargo nuevo.
    citadas = [l for l in propio.splitlines() if l.lstrip().startswith(">")]
    propio = "\n".join(l for l in propio.splitlines() if not l.lstrip().startswith(">"))
    return propio.strip(), (ajeno + "\n" + "\n".join(citadas)).strip()


def _dominio(direccion):
    m = re.search(r"@([\w.\-]+)", direccion or "")
    return m.group(1).lower() if m else ""


def normalizar(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


# ----------------------------------------------------------------------- ingesta

def _de_eml(ruta):
    with open(ruta, "rb") as fh:
        msg = email.message_from_binary_file(fh, policy=email.policy.default)
    texto, htmls, tabla, titulo, imagenes, huellas, inc = "", [], [], [], [], [], []

    for parte in msg.walk():
        if parte.is_multipart():
            continue
        ct = parte.get_content_type()
        crudo = parte.get_payload(decode=True) or b""
        nombre = parte.get_filename()
        if nombre:
            huellas.append(hashlib.sha256(crudo).hexdigest())
        if ct == "text/plain" and not nombre:
            texto += crudo.decode(parte.get_content_charset() or "utf-8", "replace")
        elif ct == "text/html" and not nombre:
            htmls.append(crudo.decode(parte.get_content_charset() or "utf-8", "replace"))
        elif ct.endswith("spreadsheetml.sheet"):
            filas, contexto, sospechosas = leer_xlsx(crudo)
            tabla += filas
            titulo += contexto
            if sospechosas:
                inc.append("SEGURIDAD · contenido fuera del bloque de la tabla en '%s', "
                           "apartado y no enviado al modelo: %s"
                           % (nombre, " | ".join(sospechosas)[:400]))
        elif ct.startswith("image/"):
            imagenes.append((ct, crudo))

    for h in htmls:
        visible, oculto = html_a_texto(h)
        if oculto:
            inc.append("SEGURIDAD · texto oculto en el HTML (invisible para el remitente "
                       "humano), apartado: %s" % oculto[:400])
        if not texto.strip():
            texto = visible

    propio, ajeno = recortar_reenvio(texto)
    if ajeno:
        inc.append("AISLAMIENTO · bloque reenviado/citado apartado, no se envía al modelo: %s"
                   % re.sub(r"\s+", " ", ajeno)[:300])

    remitente = str(msg.get("From") or "")
    return Sobre(
        titulo_adjunto=" · ".join(titulo),
        id=os.path.basename(ruta), remitente=remitente,
        dominio=_dominio(remitente), fecha=str(msg.get("Date") or ""),
        asunto=str(msg.get("Subject") or ""), texto=propio,
        tabla=tabla, imagenes=imagenes, huellas=huellas, incidencias=inc,
    )


LINEA_WA = re.compile(r"^\[(\d{1,2}/\d{1,2}/\d{2,4}),?\s*([\d:]+)\]\s*([^:]+):\s*(.*)$")


def _de_txt(ruta):
    cuerpo = open(ruta, encoding="utf-8", errors="replace").read()
    lineas = [LINEA_WA.match(l) for l in cuerpo.splitlines()]
    if any(lineas):
        autores = [m.group(3).strip() for m in lineas if m]
        # El remitente es el primer autor que no es el despacho.
        externo = next((a for a in autores if "despatx" not in a.lower()
                        and "despacho" not in a.lower()), autores[0])
        return Sobre(id=os.path.basename(ruta), remitente=externo, dominio="",
                     fecha="", asunto="Exportación de WhatsApp", texto=cuerpo)

    # Texto suelto sin remitente: no es un encargo de nadie.
    return Sobre(
        id=os.path.basename(ruta), remitente="", dominio="",
        fecha="", asunto="", texto=cuerpo,
        incidencias=["SEGURIDAD · fichero sin remitente identificable; se registra y "
                     "no genera encargo. Contenido: %s" % re.sub(r"\s+", " ", cuerpo)[:300]],
        descartado="sin remitente identificable",
    )


def ingerir(carpeta):
    """Devuelve los sobres del periodo, ya deduplicados."""
    sobres, vistos = [], {}
    for nombre in sorted(os.listdir(carpeta)):
        ruta = os.path.join(carpeta, nombre)
        if nombre.lower().endswith(".eml"):
            s = _de_eml(ruta)
        elif nombre.lower().endswith(".txt"):
            s = _de_txt(ruta)
        else:
            continue

        # Idempotencia: el importador no detecta duplicados, así que los paramos aquí.
        clave = ("|".join(sorted(s.huellas))
                 or hashlib.sha256(normalizar(s.texto).encode()).hexdigest())
        if clave in vistos and s.procesable:
            s.descartado = "duplicado de %s (mismo contenido)" % vistos[clave]
            s.incidencias.append("DEDUPE · %s" % s.descartado)
        else:
            vistos.setdefault(clave, s.id)
        sobres.append(s)
    return sobres
