# -*- coding: utf-8 -*-
"""
GESTOR — API REST del sistema de gestión interno del despacho.

    python3 sistemas/gestor/servidor.py            # escucha en http://127.0.0.1:8080

Autenticación: cabecera  X-API-Key: despacho-demo-2026
Solo biblioteca estándar. No modificar este fichero.
"""
import json
import os
import sqlite3
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

RUTA_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gestor.db")
API_KEY = "despacho-demo-2026"
LIMITE_MAX = 50
LIMITE_DEF = 20
VENTANA_S = 10
MAX_PETICIONES = 20

_peticiones = deque()


def conectar():
    cx = sqlite3.connect(RUTA_DB)
    cx.row_factory = sqlite3.Row
    cx.execute("""CREATE TABLE IF NOT EXISTS notas (
        id INTEGER PRIMARY KEY AUTOINCREMENT, empresa_id TEXT, ts TEXT,
        autor TEXT, texto TEXT)""")
    cx.commit()
    return cx


def paginar(qs):
    try:
        limite = int(qs.get("limit", [LIMITE_DEF])[0])
    except ValueError:
        limite = LIMITE_DEF
    try:
        offset = int(qs.get("offset", [0])[0])
    except ValueError:
        offset = 0
    return min(max(limite, 1), LIMITE_MAX), max(offset, 0)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        print("  %s - %s" % (self.address_string(), fmt % args))

    # ---------------------------------------------------------------- helpers
    def responder(self, codigo, cuerpo, cabeceras=None):
        datos = json.dumps(cuerpo, ensure_ascii=False, indent=1).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(datos)))
        for k, v in (cabeceras or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(datos)

    def autorizado(self):
        if self.headers.get("X-API-Key") != API_KEY:
            self.responder(401, {"error": "falta o es incorrecta la cabecera X-API-Key"})
            return False
        ahora = time.time()
        while _peticiones and ahora - _peticiones[0] > VENTANA_S:
            _peticiones.popleft()
        if len(_peticiones) >= MAX_PETICIONES:
            espera = round(VENTANA_S - (ahora - _peticiones[0]), 1)
            self.responder(429, {"error": "demasiadas peticiones",
                                 "reintentar_en_s": espera},
                           {"Retry-After": str(int(espera) + 1)})
            return False
        _peticiones.append(ahora)
        return True

    def cuerpo_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None

    # -------------------------------------------------------------------- GET
    def do_GET(self):
        if not self.autorizado():
            return
        u = urlparse(self.path)
        p = [x for x in u.path.split("/") if x]
        qs = parse_qs(u.query)
        cx = conectar()
        try:
            if p == ["salud"]:
                return self.responder(200, {"estado": "ok", "version": "1.4.2"})

            if p == ["empresas"]:
                limite, offset = paginar(qs)
                where, args = [], []
                if "q" in qs:
                    where.append("(razon_social LIKE ? OR nombre_comercial LIKE ? OR cif LIKE ?)")
                    args += ["%%%s%%" % qs["q"][0]] * 3
                if "estado" in qs:
                    where.append("estado = ?")
                    args.append(qs["estado"][0])
                w = ("WHERE " + " AND ".join(where)) if where else ""
                total = cx.execute("SELECT COUNT(*) FROM empresas_cliente " + w, args).fetchone()[0]
                filas = cx.execute(
                    "SELECT * FROM empresas_cliente %s ORDER BY id LIMIT ? OFFSET ?" % w,
                    args + [limite, offset]).fetchall()
                return self.responder(200, {"total": total, "limit": limite, "offset": offset,
                                            "datos": [dict(f) for f in filas]})

            if len(p) == 2 and p[0] == "empresas":
                f = cx.execute("SELECT * FROM empresas_cliente WHERE id=?", (p[1],)).fetchone()
                if not f:
                    return self.responder(404, {"error": "no existe la empresa %s" % p[1]})
                return self.responder(200, dict(f))

            if len(p) == 3 and p[0] == "empresas" and p[2] in ("contactos", "servicios", "notas"):
                tabla = {"contactos": "contactos", "servicios": "servicios", "notas": "notas"}[p[2]]
                filas = cx.execute("SELECT * FROM %s WHERE empresa_id=?" % tabla, (p[1],)).fetchall()
                return self.responder(200, {"datos": [dict(f) for f in filas]})

            if p == ["facturas"] or p == ["imputaciones"]:
                tabla = p[0]
                limite, offset = paginar(qs)
                where, args = [], []
                for campo, col in (("empresa_id", "empresa_id"), ("estado", "estado"), ("tipo", "tipo")):
                    if campo in qs and (tabla == "facturas" or campo == "empresa_id"):
                        where.append("%s = ?" % col)
                        args.append(qs[campo][0])
                if "desde" in qs:
                    where.append("fecha >= ?")
                    args.append(qs["desde"][0])
                if "hasta" in qs:
                    where.append("fecha <= ?")
                    args.append(qs["hasta"][0])
                w = ("WHERE " + " AND ".join(where)) if where else ""
                total = cx.execute("SELECT COUNT(*) FROM %s %s" % (tabla, w), args).fetchone()[0]
                filas = cx.execute("SELECT * FROM %s %s ORDER BY fecha LIMIT ? OFFSET ?" % (tabla, w),
                                   args + [limite, offset]).fetchall()
                return self.responder(200, {"total": total, "limit": limite, "offset": offset,
                                            "datos": [dict(f) for f in filas]})

            if p == ["personal"]:
                filas = cx.execute("SELECT * FROM personal").fetchall()
                return self.responder(200, {"datos": [dict(f) for f in filas]})

            # Informe "oficial" del sistema. Lento y viejo: nadie lo ha revisado desde 2021.
            if p == ["informes", "facturacion-cliente"]:
                time.sleep(2.0)
                filas = cx.execute(
                    "SELECT e.id, e.razon_social, ROUND(SUM(f.total),2) AS facturado "
                    "FROM empresas_cliente e JOIN facturas f ON f.empresa_id = e.id "
                    "GROUP BY e.id ORDER BY facturado DESC").fetchall()
                return self.responder(200, {"generado": "informe estandar v1 (2021)",
                                            "datos": [dict(f) for f in filas]})

            return self.responder(404, {"error": "ruta no encontrada", "ruta": u.path})
        finally:
            cx.close()

    # ------------------------------------------------------------ POST / PATCH
    def do_POST(self):
        if not self.autorizado():
            return
        p = [x for x in urlparse(self.path).path.split("/") if x]
        cuerpo = self.cuerpo_json()
        if cuerpo is None:
            return self.responder(400, {"error": "cuerpo JSON inválido"})
        cx = conectar()
        try:
            if len(p) == 3 and p[0] == "empresas" and p[2] == "notas":
                if not cx.execute("SELECT 1 FROM empresas_cliente WHERE id=?", (p[1],)).fetchone():
                    return self.responder(404, {"error": "no existe la empresa %s" % p[1]})
                if not cuerpo.get("texto"):
                    return self.responder(422, {"error": "falta 'texto'"})
                cur = cx.execute(
                    "INSERT INTO notas (empresa_id, ts, autor, texto) VALUES (?,?,?,?)",
                    (p[1], time.strftime("%Y-%m-%d %H:%M:%S"),
                     cuerpo.get("autor", "desconocido"), cuerpo["texto"]))
                cx.commit()
                return self.responder(201, {"id": cur.lastrowid, "empresa_id": p[1]})
            return self.responder(404, {"error": "ruta no encontrada"})
        finally:
            cx.close()

    def do_PATCH(self):
        if not self.autorizado():
            return
        p = [x for x in urlparse(self.path).path.split("/") if x]
        cuerpo = self.cuerpo_json()
        if cuerpo is None:
            return self.responder(400, {"error": "cuerpo JSON inválido"})
        cx = conectar()
        try:
            if len(p) == 2 and p[0] == "facturas":
                f = cx.execute("SELECT * FROM facturas WHERE id=?", (p[1],)).fetchone()
                if not f:
                    return self.responder(404, {"error": "no existe la factura %s" % p[1]})
                if "estado" not in cuerpo:
                    return self.responder(422, {"error": "solo se admite el campo 'estado'"})
                if cuerpo["estado"] not in ("emitida", "cobrada", "vencida", "anulada"):
                    return self.responder(422, {"error": "estado no válido"})
                cx.execute("UPDATE facturas SET estado=? WHERE id=?", (cuerpo["estado"], p[1]))
                cx.commit()
                return self.responder(200, {"id": p[1], "estado": cuerpo["estado"]})
            return self.responder(404, {"error": "ruta no encontrada"})
        finally:
            cx.close()


if __name__ == "__main__":
    if not os.path.exists(RUTA_DB):
        raise SystemExit("No existe gestor.db. Restaura la copia limpia de la carpeta caso-despacho/.")
    srv = ThreadingHTTPServer(("127.0.0.1", 8080), Handler)
    print("GESTOR escuchando en http://127.0.0.1:8080  (X-API-Key: %s)" % API_KEY)
    print("Prueba:  curl -H 'X-API-Key: %s' http://127.0.0.1:8080/salud" % API_KEY)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nParado.")
