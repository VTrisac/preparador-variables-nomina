# Entorno de pruebas — Despacho profesional

Réplica reducida de los tres sistemas con los que trabaja el despacho. Todo corre
en local, sin dependencias externas y sin red. Los datos son sintéticos.

Requisitos para **levantar estos sistemas**: Python 3.9+, solo biblioteca estándar.
Los datos ya vienen generados: no hay nada que instalar ni que sembrar.

> **Tu agente lo construyes con lo que quieras.** Estos tres sistemas son el
> software del cliente, no tu stack. El gestor se habla por HTTP y nóminas son
> ficheros: cualquier lenguaje, framework o plataforma sirve. Si tu herramienta
> necesita licencia, sácala tú y te la reembolsamos (dínoslo antes si pasa de 50 €).

---

## 1. GESTOR — sistema de gestión interno (API REST)

Dónde vive el maestro de empresas cliente, la facturación del despacho y las horas
que el equipo imputa a cada cliente.

```bash
python3 sistemas/gestor/servidor.py     # http://127.0.0.1:8080
curl -H 'X-API-Key: despacho-demo-2026' http://127.0.0.1:8080/salud
```

| Método | Ruta | Notas |
|---|---|---|
| GET | `/salud` | |
| GET | `/empresas` | `q`, `estado`, `limit`, `offset` |
| GET | `/empresas/{id}` | |
| GET | `/empresas/{id}/contactos` · `/servicios` · `/notas` | |
| GET | `/facturas` | `empresa_id`, `tipo`, `estado`, `desde`, `hasta`, `limit`, `offset` |
| GET | `/imputaciones` | `empresa_id`, `desde`, `hasta`, `limit`, `offset` |
| GET | `/personal` | |
| GET | `/informes/facturacion-cliente` | informe estándar del sistema |
| POST | `/empresas/{id}/notas` | `{"autor": "...", "texto": "..."}` |
| PATCH | `/facturas/{id}` | `{"estado": "emitida\|cobrada\|vencida\|anulada"}` |

- Autenticación por cabecera `X-API-Key`.
- Paginación: `limit` por defecto 20, **máximo 50**. La respuesta trae `total`.
- Hay un límite de peticiones por ventana de tiempo. Al superarlo responde `429`
  con `Retry-After`.

## 2. NÓMINAS — software de nóminas (sin API)

El software de nóminas **no tiene API**. La única vía de entrada es depositar un
CSV en `entrada/` y ejecutar el importador.

```bash
python3 sistemas/nominas/importador.py
```

```
sistemas/nominas/
├── maestro_empleados.csv          empresas, trabajadores, altas y bajas
├── equivalencias_empresas.csv     tabla que mantiene el despacho a mano
├── salida/
│   ├── listado_conceptos.csv      catálogo de conceptos y su unidad
│   └── variables_2026-07.csv      lo importado el mes pasado (formato de referencia)
├── entrada/                       aquí se deja el fichero a importar
├── procesados/                    a dónde va el fichero después
├── historico/variables_importadas.csv
└── registro.log
```

Lee la cabecera de `importador.py` antes de escribir nada en `entrada/`: describe
exactamente cómo se comporta el proceso de importación. **Ese comportamiento es un
dato del problema, no un fallo a corregir.**

Formato del fichero de importación:

```
COD_EMPRESA;COD_EMPLEADO;COD_CONCEPTO;VALOR;FECHA_INICIO;FECHA_FIN;OBSERVACIONES
```

cp1252 · separador `;` · decimales con coma · fechas `AAAA-MM-DD`.

## 3. BUZÓN — correo del área laboral

`sistemas/buzon/2026-08/` contiene los mensajes recibidos durante el periodo, tal y
como llegan: `.eml` (algunos con adjuntos), exportaciones de WhatsApp en `.txt`,
hojas de cálculo y fotografías. No están filtrados ni ordenados.

---

## Reiniciar el entorno

No hay forma de deshacer una importación: eso es parte del problema. Si quieres
poder volver al estado inicial, guarda una copia limpia de esta carpeta antes de
empezar y restáurala cuando la necesites.
