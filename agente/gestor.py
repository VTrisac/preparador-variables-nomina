# -*- coding: utf-8 -*-
"""
Cliente del GESTOR — la API que hizo un proveedor que ya no existe.

Dos rarezas suyas que condicionan cualquier cosa que se hable con ella, verificadas
leyendo `servidor.py`:

  · El límite de peticiones es GLOBAL, no por clave: `_peticiones` es un deque de
    módulo, 20 peticiones cada 10 s para todo el proceso. Paralelizar se
    autoenvenena, así que aquí se va en serie y se respeta `Retry-After`.
  · `limit` tiene tope 50 y la respuesta trae `total`: hay que paginar a mano.

Solo lectura. Este agente no escribe nada en el gestor: ver DECISIONES.md.
"""
import json
import os
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8080"
CLAVE = "despacho-demo-2026"
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache_gestor.json")
CADUCA_S = 24 * 3600


def _pedir(ruta, intentos=4):
    for i in range(intentos):
        req = urllib.request.Request(BASE + ruta, headers={"X-API-Key": CLAVE})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code != 429 or i == intentos - 1:
                raise
            espera = float(e.headers.get("Retry-After") or 2)
            time.sleep(espera + 0.2)      # su propia cabecera manda
    raise RuntimeError("no se pudo leer %s" % ruta)


def paginar(ruta):
    """Recorre una colección respetando el tope de 50 por página."""
    salida, offset = [], 0
    while True:
        sep = "&" if "?" in ruta else "?"
        d = _pedir("%s%slimit=50&offset=%d" % (ruta, sep, offset))
        salida += d["datos"]
        offset += 50
        if offset >= d["total"]:
            return salida


def contactos(cache=CACHE):
    """Con caché en disco: leer la agenda entera cuesta 65 peticiones y, con el tope
    de 20 cada 10 segundos, unos 34 segundos de reloj. Los contactos de 400 empresas
    no cambian de un día para otro; el ciclo de nóminas sí es diario entre el 17 y el
    25. Se relee una vez al día."""
    if cache and os.path.exists(cache) and time.time() - os.path.getmtime(cache) < CADUCA_S:
        return json.load(open(cache, encoding="utf-8"))
    datos = _contactos_de_la_api()
    if cache:
        json.dump(datos, open(cache, "w", encoding="utf-8"), ensure_ascii=False)
    return datos


def _contactos_de_la_api():
    """[{empresa_id, cif, email}] — el puente dominio -> empresa, cuando funciona.

    Ojo: los emails del gestor están sucios ('vilanovalogíst.cat' truncado y con
    acento, 'campsmetall.cat' cuando el real es '.com'). Solo 3 de los 7 dominios
    del buzón cruzan de forma exacta. Por eso resolver_empresa() no se fía de una
    sola señal.
    """
    cif = {e["id"]: e["cif"] for e in paginar("/empresas")}
    salida = []
    for eid in cif:
        for c in _pedir("/empresas/%s/contactos" % eid)["datos"]:
            salida.append({"empresa_id": eid, "cif": cif[eid],
                           "email": (c.get("email") or "").lower()})
    return salida


def disponible():
    try:
        return _pedir("/salud", intentos=1).get("estado") == "ok"
    except Exception:
        return False
