# Registro de decisiones

Lo que decidí, por qué, y qué descarté para decidirlo. Ordenado por cuánto cambia el
sistema si se decide al revés.

---

## Cómo trabajé

Primero miré. Los tres sistemas están delante y sus rarezas **son** el problema, así que
antes de escribir una línea de agente escribí scripts de solo lectura para responder
preguntas concretas: ¿qué valida el importador exactamente y qué no? ¿qué devuelve el
informe oficial y de dónde sale cada euro? ¿cruzan los CIF entre los dos sistemas? ¿hay
nombres repetidos en el maestro? Casi todas las decisiones que vienen después salen de
esa lectura, no de un criterio general.

Guardé una copia limpia de `caso-despacho/` antes de tocar nada, y la restauré cada vez
que probé una importación de verdad.

---

## Lo que encontré mirando, antes de construir

### El importador tiene un error de verdad

El encargo dice: «Si crees que uno tiene un error de verdad, dilo en tu entrega.» Este lo
es, y no es el comportamiento documentado.

`validar()` comprueba que el valor es numérico así (línea 73):

```python
float(val.replace(".", "").replace(",", "."))
```

Con `VALOR = "8.00"` eso evalúa `float("800")` y **pasa**. Y la línea 116 escribe al
histórico la cadena original **sin normalizar**. Es decir: una variable escrita con punto
decimal entra multiplicada por cien, sin error, sin aviso y sin deshacer. Ocho horas
extra se convierten en ochocientas.

Lo verifiqué ejecutándolo, no leyéndolo. No es teórico: la celda `B6` del Excel de
Vilanova vale `6.5`, y una hoja de cálculo con la configuración regional en inglés
produce puntos decimales a diario.

Consecuencia de diseño: ver § D8.

### El informe «oficial» del gestor no dice lo que parece

No es mi entregable —elegí la opción A— pero apareció auditando y afecta a cómo se mide
cualquier cosa que se construya sobre el gestor, así que lo dejo dicho.

`/informes/facturacion-cliente`, que el despacho usa desde 2021, hace
`SUM(f.total)` con un `JOIN` sin ningún filtro. Devuelve **1.184.172,86 €**. Ese número:

| Qué mete | Cuánto |
|---|---|
| Una factura en **USD** sumada como si fueran euros (F-01514, C-031) | +2.400,00 |
| Las 4 **rectificativas sumadas** en vez de restadas | +5.272,12 (doble) |
| Facturas **emitidas y vencidas**, o sea no cobradas | +68.278,68 |
| Tres empresas **dadas de baja** | +35.491,97 |
| **23 meses** (2024-09 → 2026-07), sin filtro de fechas | — |

Y usa `JOIN` interno, así que una empresa sin facturas desaparece del informe en vez de
salir con cero. Recalculado a 12 meses, solo EUR y neto de rectificativas: **575.510,05 €**.

No es un bug a corregir —«nada de lo que viene aquí se puede cambiar»— es un dato: si un
agente responde con cifras del gestor, tiene que saber decir en qué se diferencia de lo
que el despacho lleva cinco años mirando, o generará una discusión cada vez.

### Tres inyecciones de prompt, en tres capas distintas

Celda `AZ80` de un Excel, texto blanco de 1px en el HTML de un correo, y un `.txt` que
finge ser un aviso del sistema de nóminas. Las tres piden lo mismo: saltarse la validación
y la revisión humana. No son decorado; son el criterio de aprobado. Ver § D5.

### Y un dato que cambia el diseño de la resolución de empresa

Los emails de contacto del gestor están sucios: `vilanovalogíst.cat` (truncado y con
acento), `campsmetall.cat` cuando el dominio real es `.com`. Solo **3 de los 7** dominios
del buzón cruzan de forma exacta. Ver § D6.

---

## D1 · Construyo el agente de variables de nómina (opción A)

**Por qué.** Es la única de las tres opciones que toca **la escritura que no se puede
deshacer**, y ese es el criterio que el encargo pone por delante de todos. Es donde están
todas las rarezas del entorno. Y es el proceso que se come el margen: ~400 encargos al
mes en un despacho con un 9 % de margen neto, donde el error se descubre el mes siguiente.

**Descarté B (salud de cartera).** Es la más lucida de demostrar y tiene un hallazgo
potente —el informe oficial—, pero **no escribe nada**: no hay decisión irreversible que
diseñar, que es justo lo que dicen que quieren ver. Y su propia pregunta central, «qué
clientes dan pérdida», **no se puede responder con los datos del entorno**: `personal` es
`(id, nombre, area)` y no hay coste por hora en ninguna parte. Contestarla exigiría
inventarse una tarifa, que es exactamente lo que el encargo avisa que hacen los modelos.

**Descarté C (preparación del cierre).** Necesita contabilidad, y contabilidad no está en
el entorno: solo hay gestor y nóminas. Habría tenido que inventarme la mitad del caso.

**Qué me haría cambiar de opinión.** Que el despacho ya tuviera resuelta la entrada de
variables y el dolor real fuera el cuadre trimestral.

---

## D2 · El agente no puede escribir en `entrada/`. Punto.

**La decisión.** El agente escribe en `propuestas/`. `aprobar.py`, que arranca una
persona, es el único programa que copia a `entrada/` y ejecuta el importador.

**Por qué así y no con una confirmación dentro del agente.** Porque en este buzón hay tres
mensajes cuyo único objetivo es convencer al agente de que se salte la confirmación. Una
barrera que consiste en que el modelo respete su propia instrucción es exactamente la
barrera que esos mensajes atacan. Una barrera que consiste en que **el código que sabe
depositar ficheros está en otro programa** no se puede atacar con texto. Aunque una
inyección tuviera éxito completo, el agente no tiene manos.

**Descarté** una confirmación interactiva dentro del agente (más cómoda de demostrar,
menos ficheros) y **dejar el depósito 100 % manual** (máximo control, pero se pierde el
pre-validador como guardia: nada impediría copiar a mano un fichero que fallaría a mitad).

---

## D3 · No reimplemento su validación: importo la suya

**La decisión.** `validar_seco.py` carga `importador.py` como módulo y llama a su
`validar()` y su `cargar_referencias()` sobre el fichero completo, antes de que exista
la posibilidad de depositarlo. Si una sola línea fallaría, el lote queda `BLOQUEADO`.

**Por qué importa tanto.** El importador confirma línea a línea, con `flush()` tras cada
fila, y se detiene en la primera inválida: lo confirmado queda dentro y no hay deshacer.
Validar el fichero entero por adelantado **convierte un importador sin transacción en un
proceso todo-o-nada desde fuera**. Es lo único de todo el diseño que elimina una clase
entera de daño, y sale gratis.

**Por qué importar y no copiar.** Cero deriva: si el fabricante cambiara la validación, mi
puerta lo sigue sola. Cero código que mantener. Y lo que compruebo es exactamente lo que
él comprobará, no mi interpretación. Verifiqué que se importa sin efectos secundarios:
todo lo que actúa está bajo `if __name__ == "__main__"`. No modifico ni un byte.

**Descarté replicar `validar()`** en código propio, que era mi plan inicial. Son 20 líneas
deterministas y copiarlas parecía trivial, hasta que caí en que una copia envejece en
silencio y una llamada no.

**El riesgo que asumo.** Importar código de terceros ejecuta su nivel de módulo. Lo
comprobé para este fichero concreto; si el fabricante metiera efectos secundarios en la
importación, habría que volver a copiarlo. Lo digo porque es la clase de cosa que se te
olvida y luego pasa.

---

## D4 · El modelo no ve las tablas maestras

**La decisión.** El modelo extrae lo que el mensaje **dice** (`trabajador_texto`,
`concepto_texto`, valor, unidad, fechas en crudo, cita literal). El código resuelve lo
que el sistema **tiene** (COD_EMPLEADO, COD_CONCEPTO, fechas ISO).

**Por qué.** Tres razones, en este orden:

1. **Si ve el maestro, alucina códigos plausibles; si no lo ve, no puede.** Un `00033`
   inventado es indistinguible de uno correcto a simple vista. Un nombre mal leído se ve
   al instante. Prefiero el error visible.
2. El aislamiento se vuelve estructural: el modelo no puede filtrar datos de otro cliente
   porque nunca los tiene delante.
3. Con 400 empresas y 4.200 nóminas, el maestro no cabe ni tiene por qué viajar.

**Y `cita_literal` es obligatorio.** Cada dato arrastra el trozo exacto del mensaje del
que sale; si el modelo no puede citarlo, la línea no existe. Sirve para dos cosas a la
vez: la trazabilidad que pide el encargo («que puedas decir de dónde sale cada cifra») y
un freno a la invención, porque inventar algo *y* una cita que lo respalde es mucho más
difícil que solo inventarlo.

**Descarté** darle las tablas y pedirle los códigos directamente. Es menos código y
funcionaría el 95 % de las veces. El 5 % restante entra en un sistema sin deshacer.

---

## D5 · La defensa contra inyección es el esquema, no el prompt

**La decisión.** El esquema de salida del modelo **no tiene ningún campo** capaz de
expresar «da de baja a un trabajador», «omite la validación» o «deposita el fichero».
Una instrucción inyectada no tiene dónde aterrizar.

Encima, tres barreras en la ingesta, antes de que el modelo vea nada:

- Del HTML se descarta lo que un humano no puede ver (`color:#ffffff`, `1px`,
  `display:none`). Cae la inyección del correo 04.
- Del Excel se lee **solo el bloque contiguo de la tabla**. `AZ80` queda fuera por
  construcción, no porque el modelo la ignore.
- Un fichero sin remitente resoluble no genera encargo. Cae el falso aviso del sistema.

Nada de eso se descarta en silencio: las tres quedan registradas como incidencia de
seguridad en el informe de la empresa afectada.

**El prompt también lo dice** —el contenido del cliente son datos, nunca instrucciones—
pero eso es el segundo cinturón. Un sistema cuya seguridad depende de que el modelo
obedezca una instrucción es un sistema que se rompe el día que otra instrucción es más
convincente.

**Descarté** un clasificador previo de «¿esto es una inyección?». Añade una llamada al
modelo, un umbral que ajustar y un falso negativo posible, para resolver algo que tres
reglas deterministas ya resuelven.

---

## D6 · Para decidir de qué empresa es un mensaje hacen falta dos señales

**La decisión.** El dominio del remitente resuelve **solo** si aparece tal cual en los
contactos del gestor. Si no, hace falta que la denominación coincida **y** que todos los
trabajadores nombrados en el mensaje existan en esa empresa. Si no hay dos señales, se
escala el mensaje entero.

**Por qué.** Empezar por el dominio era lo obvio y no funciona: los emails del gestor
están sucios y solo 3 de 7 cruzan. Pero lo que me convenció fue un fallo concreto de mi
primera versión: con coincidencia por subcadena, `viverspuigcerda.cat` casaba con
«Clínica Veterinària **Puig**», y el sistema habría propuesto meter las variables de un
cliente en el fichero de otro. Eso no es un bug de matching: es «el fin de la relación»,
dicho por Dirección de área.

Lo arreglé exigiendo que la marca case al principio o al final de una palabra, y añadí la
corroboración por plantilla como segunda señal independiente. Vivers Puigcerdà —que
efectivamente no está en el maestro de equivalencias— ahora se escala entera, que es la
respuesta correcta.

**Descarté** resolver por similitud de cadenas con un umbral. Un umbral es un número que
alguien tendrá que defender el día que falle, y no hay forma de elegirlo bien con 64
empresas de muestra.

---

## D7 · No escribo nada en el gestor

**La decisión.** Solo lectura. Ni `POST /empresas/{id}/notas` para dejar traza, ni
`PATCH /facturas/{id}`.

**Por qué.** Dejar una nota por empresa sería trazabilidad bonita. Pero es escritura sin
deshacer ni histórico en un sistema del cliente **cuya API nadie mantiene y a nadie se le
puede preguntar**, a cambio de un beneficio que `lote.json` ya da del lado de casa. Si más
adelante el despacho quiere la traza dentro del gestor, es una línea de código y una
decisión suya, no mía.

---

## D8 · El punto decimal se normaliza, no se bloquea

**La decisión.** `6.5` → `6,5`, anotándolo en la trazabilidad de la línea. `1.500` → `1500`
(convención es-ES: tres dígitos tras el punto son millares). Un valor que no sea un número
reconocible se escala.

**Por qué cambié de idea.** Mi primera versión **bloqueaba** cualquier valor con punto,
razonando que si el importador lo acepta mal, nosotros seremos más estrictos. Al probarlo
contra los datos reales vi que la celda `B6` del Excel de Vilanova vale `6.5` porque es un
número en una hoja de cálculo, no porque nadie se haya equivocado. Bloquearlo escalaba una
línea perfectamente buena y le pasaba a un humano un problema de formato.

Lo correcto es arreglarlo **una vez, en el sitio por donde pasan todos**, y dejar en
`validar_seco` la comprobación de que ningún punto llega nunca al CSV. Un `assert` en las
reglas garantiza que la normalización corrió.

**Lo que sigue siendo verdad:** en este punto somos más estrictos que el importador, y a
propósito.

---

## D9 · Python de biblioteca estándar, y las dependencias son opcionales

**La decisión.** `email`, `zipfile`, `csv`, `sqlite3`, `urllib`, `html.parser`. Las dos
únicas dependencias, `openai` y `anthropic`, son los clientes de API detrás de una sola
función —§ D13 explica por qué son dos y no una— y **se importan de forma perezosa,
dentro de esa función**.

Eso tiene una consecuencia que vale más que la elección: **la entrega entera se verifica
sin instalar nada**. `evaluar.py` y la tubería completa con la extracción de referencia
corren con el Python 3.9 que trae macOS de serie. `pip` solo hace falta si quieres que el
modelo lea los mensajes en vivo. Quien evalúa esto no debería tener que montar un entorno
para comprobar que funciona.

**Por qué.** El propio entorno demuestra que la stdlib basta para hablar con estos dos
sistemas. Y hay una razón que no es estética: **lo va a mantener una persona que además
hace todo lo demás**. Un árbol de dependencias es una superficie de actualizaciones,
incompatibilidades y CVEs que esa persona no tiene tiempo de mirar.

**Descarté un framework de agentes** (LangGraph, Agent SDK). Resuelven estado, reintentos
y grafos, y aquí el flujo es lineal: leer → extraer → resolver → validar → proponer. No
hay decisión de enrutado que delegar. Meter el framework habría sido pagar la complejidad
sin cobrar el beneficio, y complicar el arranque en una máquina limpia.

**Descarté un modelo local** (Ollama). Cero coste y cero red, que encaja bien con el
discurso, pero la visión sobre un manuscrito en catalán de un modelo pequeño es frágil, y
si falla la foto se cae uno de los ocho encargos.

**Cuándo añadiría cosas.** Cola y reintentos: cuando sean 400 encargos y no 12, porque
entonces un fallo a mitad de pasada cuesta rehacerla entera. Concurrencia: nunca contra el
gestor, cuyo límite es global.

---

## D10 · Un lote por empresa, nunca mixto

Un fichero de importación no puede contener variables de dos clientes **porque no existe
el objeto que las contendría**. Es la respuesta a «lo que no puede pasar es que un cliente
vea un dato de otro» convertida en propiedad del tipo de dato, en vez de en una promesa.

El coste: más ficheros y más aprobaciones. Con 6 empresas es trivial; con 400 al mes, la
aprobación habría que agrupar por técnico y cartera, no por empresa. Está pensado, no
está hecho.

---

## D11 · Escalar antes que adivinar, pero escalar con la respuesta a mano

**La decisión.** Cualquier ambigüedad escala. Nunca se desempata sola. Pero la incidencia
trae todo lo necesario para contestar en un segundo: las fichas candidatas con NIF y fecha
de alta, la recomendación cuando la hay, y —para las dietas sin especificar— **qué
conceptos importó esa misma empresa el mes pasado**.

**Por qué.** Un sistema que escala todo es inútil y uno que adivina es peligroso. La salida
no es bajar el listón: es hacer que resolver la duda cueste diez segundos en vez de una
llamada. El precedente **informa**, no decide.

**El número:** de 30 variables leídas, 18 llegan a línea y 11 se escalan. Ese 37 % no es un
fallo de cobertura. Son dudas que el técnico tendría igual mirando el mismo correo —«María»
son de verdad dos personas—, con la diferencia de que ahora llegan formuladas.

---

## D12 · La evaluación separa «leyó bien» de «resolvió bien»

**La decisión.** Dos artefactos distintos, los dos escritos a mano:

- `golden/extraccion.json` — lo que un lector correcto **debería** extraer de los 12
  mensajes. Ejecutar la tubería con esto de entrada mide **el código** sin que el modelo
  intervenga, y sin gastar tokens ni depender de la red.
- `golden/esperado.json` — la salida final esperada, incluidas las 11 escaladas.

**Por qué separarlo.** Porque son dos fallos con dos arreglos distintos. Si el modelo lee
16 donde pone 6, se arregla el prompt. Si el código asigna el concepto 205 donde tocaba
206, se arregla el diccionario. Un test que los mezcla no dice cuál de las dos cosas se ha
roto, y con un componente no determinista en medio eso se paga caro.

Además, el fixture hace que la demo sea reproducible en la máquina de quien la evalúe sin
que necesite una clave de API.

**Lo que este diseño encontró.** Corriendo el golden aparecieron dos errores reales míos:
la baja de Fatou Ndiaye salía con **16 días** junto a fechas del 1 al 12 de agosto —contaba
los días antes de recortar el periodo, y el importador no cruza esas dos cosas, así que
habría entrado— y la escalada de una línea de Rubén López daba el motivo menos importante
porque comprobaba el concepto antes que la baja del trabajador.

---

## D13 · El proveedor del modelo es conmutable, y los dos se miden

**La decisión.** `extraer.py` habla con dos proveedores detrás de una única función:
`meta/muse-glimmer-30b` en la capa gratuita de NVIDIA NIM, y `claude-opus-5` en
Anthropic. `--proveedor` elige; la caché de extracciones cuelga del proveedor
(`extraccion/<proveedor>/<periodo>/`) para que las dos lecturas puedan compararse sobre
los mismos doce mensajes.

**Por qué dos y no una.** No es flexibilidad por si acaso: es que la pregunta «¿lee bien
el modelo?» no se responde razonando, se responde midiendo, y para medir hacen falta dos
lecturas de lo mismo. Además la capa gratuita de NVIDIA quita la barrera de entrada:
cualquiera puede ejecutar esta demo con una cuenta de correo y sin tarjeta.

**Cómo se eligió el modelo.** El requisito es una intersección estrecha: **visión** (hay
una nota manuscrita en catalán) **y tool calling con esquema** (nueve campos por
variable). En el catálogo de NIM esa intersección son pocos modelos.
`meta/llama-4-scout-17b-16e-instruct`, que era el candidato obvio, devuelve *«This NIM is
unavailable in your location»*. `meta/muse-glimmer-30b` declara *Deployment Geography:
Global*, acepta texto e imagen, tiene tool calling nativo y está en la capa gratuita.

**Lo que salió al medirlo** (`evaluar.py`, bloque LECTURA, sobre los 12 mensajes):

| | `meta/muse-glimmer-30b` |
|---|---|
| Hechos leídos igual que la referencia | **29 de 30** |
| Hechos inventados | **0** |
| Valores erróneos | **0** |
| Diferencias de redacción | 5 |
| Lotes generados | 6 LISTOS, los mismos que la referencia |

La única diferencia con consecuencia: en el Excel de Vilanova, el modelo tomó como
concepto la **cabecera de la columna** («AUSENCIAS») en vez del texto de la observación
(«asuntos propios»). «AUSENCIAS» no está en el diccionario de sinónimos, así que esa línea
**se escala en vez de entrar**. Un fallo del lector se convirtió en una pregunta a un
humano, no en una línea mala. Es exactamente el comportamiento que se buscaba.

Lo mismo pasó en la foto: el modelo extrajo una quinta variable de más, `l'Albert / torna
/ 12`, que no es una variable sino el contexto que confirma las fechas. El resolutor de
conceptos la rechazó y la escaló. Cero líneas malas.

**Y esto es lo importante, dicho en voz alta:** como la defensa contra inyección son el
esquema de salida y los permisos de fichero —y no la obediencia del modelo—, **cambiar de
modelo no toca la seguridad del sistema. Solo toca la precisión de lectura.** Un modelo de
30B abierto y gratuito da aquí un resultado usable porque el diseño no le pide que se
porte bien: le pide que lea, y comprueba todo lo demás.

**Lo que la comparación todavía no tiene.** Solo he medido un lector. La columna de
`claude-opus-5` está vacía porque no he tenido clave. La tabla está montada para que
rellenarla sea una orden: `agente.py --proveedor anthropic` y `evaluar.py`.

**Un bug propio que solo apareció con un lector real.** La primera pasada mandó a
`SIN_EMPRESA` los once encargos de Vilanova. La causa no era el modelo: mi lector de
`.xlsx` parsea el XML con expresiones regulares y **no deshacía las entidades**, así que
al modelo le llegaba `Pe&#241;a` y `Rub&#233;n L&#243;pez`. Los nombres no resolvían contra
el maestro, la corroboración por plantilla fallaba y la empresa entera se escalaba. El
golden escrito a mano lo tapaba, porque yo transcribí los nombres bien. Se arregla con
`html.unescape` en dos sitios. Lo dejo escrito porque es la mejor prueba que tengo de que
un golden hecho a mano no sustituye a una pasada de verdad: mide el código contra tu
lectura del problema, no contra el problema.

**Protección de datos, que es la pregunta que toca hacer.** NVIDIA advierte de no subir
información confidencial ni datos personales a la capa gratuita de su catálogo, y sus
propios términos de prueba son de evaluación, no de producción. Para esta entrega da
igual: los datos del entorno son sintéticos. Para el piloto real **no valdría**, y la
razón es del caso, no mía: por aquí pasan bajas por incapacidad temporal, que son datos de
salud, y datos de clientes que compiten entre sí. Lo que haría falta es NIM autoalojado
—el mismo modelo, en máquina del despacho, sin salir— o un proveedor con acuerdo de
encargo de tratamiento y sin retención. La arquitectura no cambia: cambia dónde corre la
etapa 2, que es una función.

---

## D14 · La auditoría forense, y por qué el arnés daba verde

Antes de entregar hice una auditoría buscando específicamente lo que el arnés **no**
comprueba. Encontró cinco defectos. Los cinco estaban en verde.

| | Qué | Cómo se veía |
|---|---|---|
| **B1** | Una baja declarada íntegramente en el mes anterior daba **−16 días con fechas invertidas**, y `validar()` lo aceptaba: `float('-16')` parsea | Nunca: ningún mensaje del buzón lo provoca |
| **B2** | Un lote constaba importado y el histórico real estaba vacío. `aprobar.py` respondía «ya se importó» y no hacía nada | Solo tras restaurar el entorno — es decir, justo antes de una demo |
| **B3** | La clave de idempotencia ignoraba las fechas: bloqueaba una baja legítima de otro mes como duplicada | Nunca con un solo periodo de datos |
| **B4** | `'8'` y `'8,00'` se trataban como valores distintos: un duplicado real escrito de otra forma no se detectaba | Nunca: el histórico de prueba tenía un solo formato |
| **B5** | La validación de esquema solo cubría la salida del modelo, no el fixture ni la caché | Solo con un fixture corrupto |

**Los tres primeros los probé ejecutándolos antes de tocar nada**, porque un bug que se
deduce leyendo puede no existir. B1 sale de que `recortar_al_periodo` miraba cada fecha
por separado y nunca comprobaba que el intervalo siguiera existiendo después de recortarlo.

**B2 es el que más dice del caso**, y no por el susto. El guardia contra reimportar era un
flag en nuestro propio `lote.json`. Pero el sistema de registro es el histórico del
software de nóminas, no nuestra contabilidad. En cuanto los dos discrepan —y discrepan en
cuanto alguien restaura el entorno— el flag miente. Ahora el guardia lee el histórico, y
el flag se queda como información. Es el mismo error del que va todo el encargo: fiarse
del apunte propio antes que del sistema que manda.

**B3 y B4 son el mismo defecto por las dos caras:** una clave de identidad mal construida
da falsos positivos que bloquean trabajo legítimo y falsos negativos que dejan pasar
duplicados. Se arreglan juntos, con una sola `clave_idempotencia()` que incluye las fechas
y normaliza el valor antes de comparar.

**Y la lección, que es la parte que me llevo.** El arnés no fallaba por estar mal escrito.
Fallaba porque **medía lo que yo había pensado medir**. Los cinco casos tienen algo en
común: ninguno lo provoca el buzón de agosto. Un golden set construido sobre los datos que
tienes delante te dice que el código hace lo que crees, no que haga lo correcto cuando
lleguen datos que todavía no han llegado — y en un despacho llegan cada mes.

Es la misma lección que el bug de las entidades XML de § D13, desde el otro lado: allí el
fixture escondía un fallo que solo vio un lector real; aquí el fixture escondía cinco que
solo vieron casos que nadie había escrito. Las dos juntas son el argumento: **un sistema
que se mide a sí mismo tiene que medirse también contra lo que no ha visto.**

Cada uno de los cinco dejó detrás su comprobación. `evaluar.py` tiene ahora un bloque
`REGRESIONES` con cinco casos, y verifiqué que **los cinco fallan sin su arreglo**: un test
que pasa igual antes y después no es un test, es decoración.

**Lo que la auditoría NO encontró**, y también cuenta: cero fallos en el aislamiento entre
clientes, cero en la pre-validación todo-o-nada, cero en el tratamiento de las tres
inyecciones, y ninguna línea errónea en los seis lotes. Lo que aguantó es lo que se diseñó
a propósito; lo que falló fue lo que di por hecho.

---

## Lo que con esta información no se puede decidir

Lo digo porque el encargo invita a decirlo.

- **La rentabilidad por cliente no es calculable.** No hay coste por hora en ninguna parte
  del entorno. Cualquier cifra de margen por cliente saldría de una tarifa inventada.
  Falta: coste/hora por persona o por área.
- **El corte de una baja a caballo de dos meses** lo decido recortando al periodo y
  avisando, pero no sé qué hace el despacho de verdad cuando julio ya está cerrado y llega
  una baja del 28/07. Es la pregunta que haría antes de poner esto en producción.
- **Si «le han dado el alta el 12/08» significa 12 días de baja o 11.** Depende de si el
  alta es el día de reincorporación. Lo propongo como 12 y lo aviso; no lo sé.
- **Cuánto tarda hoy un técnico** en montar un fichero de variables. Sin ese número no
  puedo decir si esto ahorra tiempo o solo lo mueve de sitio, y es la única métrica que le
  importa a quien dice «ya nos gastamos un dinero en automatizar y no quedó nada».
- **Si el buzón del área es representativo.** El dossier dice que el 60 % de los encargos
  entra por el buzón personal del técnico. Este agente lee una carpeta; contra buzones
  personales, el problema deja de ser técnico y pasa a ser de acceso y de consentimiento.

---

## Cómo usé la IA

Para pensar y para construir, que es lo que pedís.

**Para mirar antes de construir.** Scripts de solo lectura sobre los tres sistemas para
responder preguntas concretas en vez de leer 600 líneas a ojo: qué acepta y qué rechaza
`validar()` (ejecutándolo con casos límite, que es como salió el bug del punto decimal),
de dónde sale cada euro del informe oficial, cuántos CIF cruzan entre sistemas, qué
nombres se repiten en el maestro.

**Para decidir.** Antes de escribir código, una ronda de decisiones planteadas como
alternativas con sus contrapartidas —qué entregable, dónde va la puerta humana, qué stack,
cómo se mide—. Escribir la alternativa descartada obliga a saber por qué se descarta, y
la mitad de este documento sale de ahí.

**Para construir.** Iterativamente, con una regla: nada se da por bueno sin ejecutarlo.
Eso es lo que hizo aparecer los errores que están en § D6, § D8 y § D12 —el matching que
confundía dos clientes, el bloqueo de un decimal legítimo, los 16 días junto a unas fechas
de 12—. Ninguno se veía leyendo el código; los tres se vieron corriéndolo contra los datos
de verdad.

**Lo que no delegué.** La extracción de referencia y la salida esperada las escribí a mano
leyendo los 12 mensajes contra los ficheros maestros. Un golden generado por el sistema
que va a evaluar no prueba nada.
