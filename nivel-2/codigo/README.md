# Nivel 2 — cálculo y validación de rutas

La entrega es `nivel-2/rutas.json`. Contiene un recorrido por vehículo,
con salida del depósito, pedidos en orden de descarga y regreso al depósito.
El código lee los archivos del expediente: no contiene rutas prefijadas ni
utiliza servicios de mapas externos. No lee los pedidos del nivel 1.

## Archivos de entrada

Mantener los originales en dos carpetas separadas:

- `originales/nivel-1/`: `catalogo.json` y `padron.csv`.
- `originales/nivel-2/`: `pedidos.json`, `siracusa.osm`, `flota.json` y `operacion.json`.

Estos archivos se abren exclusivamente para lectura. No se incluyen paquetes,
entornos, modelos ni credenciales en el repositorio.

## Requisitos y uso

Python 3.11 y OR-Tools 9.15.6755 para optimizar. La validación y las pruebas
solo usan la biblioteca estándar de Python.

Desde la raíz del repositorio, instalar la dependencia en el entorno elegido:

```shell
python -m pip install ortools==9.15.6755
```

Generar un candidato (cambiar las rutas de entrada según dónde se guarden):

```shell
python nivel-2/codigo/resolver.py --nivel1 originales/nivel-1 --nivel2 originales/nivel-2 --salida candidato.json --segundos 120
```

Se ensayaron tres estrategias iniciales, cada una con 120 segundos de búsqueda:
`PARALLEL_CHEAPEST_INSERTION`, `PATH_CHEAPEST_ARC` y
`LOCAL_CHEAPEST_INSERTION`. Se selecciona mediante `--estrategia`.
Para continuar desde un plan válido, usar `--semilla candidato.json`.

Refinar el candidato con un segundo modelo y obtener su cota inferior:

```shell
python nivel-2/codigo/refinar.py --nivel1 originales/nivel-1 --nivel2 originales/nivel-2 --semilla candidato.json --salida nivel-2/rutas.json --segundos 120 --trabajadores 4 --informe informe-local.json
```

Comprobar la entrega sin OR-Tools:

```shell
python nivel-2/codigo/validar.py --nivel1 originales/nivel-1 --nivel2 originales/nivel-2 --rutas nivel-2/rutas.json
python nivel-2/codigo/pruebas.py
```

Los informes se imprimen fuera del JSON de entrega. `validar.py` admite
`--informe informe-local.json` para guardarlos por separado. No es necesario
subir candidatos ni informes. La búsqueda usa un límite de tiempo; el orden
exacto de la solución puede variar entre equipos y ejecuciones. Siempre se
valida el resultado antes de escribirlo.

## Interpretación del mapa

1. Cada `way` recibido tiene dos nodos. Se toma su etiqueta `distancia_m`;
   no se calcula distancia geodésica ni se usan coordenadas como atajo.
2. Se excluyen los `way` con `access=no`.
3. `oneway=yes` permite el orden de los nodos; `oneway=-1`, el inverso;
   `oneway=no`, ambos sentidos.
4. La velocidad es la de `operacion.json` según `highway`.
5. Se calcula `ceil(distancia_m * 3.6 / velocidad_kmh)` en cada arista,
   con aritmética racional exacta; luego se suman segundos enteros.
6. Dijkstra minimiza el par `(distancia, tiempo)` lexicográficamente. Un
   camino más rápido pero más largo no sustituye al de menor distancia.

La matriz incluye el depósito y los 80 pedidos: 81 × 81 pares dirigidos.
Las direcciones se contrastan con una misma fila del padrón.

## Modelo de operación y objetivo

- Objetivo: minimizar la suma de metros de los recorridos, incluyendo cada
  salida y cada regreso al depósito.
- Un pedido es una parada indivisible y se asigna a un único vehículo.
- Una ruta por vehículo, sin recargas. El peso y el volumen se suman desde
  el catálogo, que ya incluye envases.
- El peso se representa en unidades de 0,0001 kg y el volumen en unidades
  de 0,000001 m³, sin redondeos que relajen las capacidades.
- La variable de tiempo de cada pedido es el comienzo de la descarga.
  Su intervalo permitido es `[desde, hasta - descarga_segundos]`.
- Cada traslado agrega el servicio de la parada anterior y el tiempo
  correspondiente a su camino de menor distancia.
- Se permite esperar; las descargas de cada vehículo son secuenciales.
- Cada vehículo sale al comienzo de su disponibilidad. Puede esperar en
  destino. El regreso debe ocurrir antes o en el fin de su turno.

`resolver.py` usa inserción inicial y búsqueda local guiada. Durante la
búsqueda admite estados incompletos con una penalización que supera toda
distancia posible del lote. Esos estados nunca se exportan: la cobertura
completa es obligatoria al terminar y vuelve a comprobarse en el validador.

`refinar.py` formula otro modelo con arcos binarios, asignación de vehículo,
dos capacidades y tiempos de descarga. Los arcos propagan el vehículo y
el tiempo. Las duraciones positivas impiden ciclos sin depósito. El plan
válido inicial sirve como pista y como límite superior de distancia.

## Controles

`validar.py` no depende del optimizador: vuelve a leer los originales,
reconstruye las matrices y comprueba esquema exacto, una fila por vehículo,
todos los pedidos una sola vez, capacidad de carga, tiempos de traslado,
descarga completa dentro de las franjas, espera y regreso dentro del turno.

`pruebas.py` cubre prioridad de distancia sobre tiempo, desempate por tiempo,
sentidos inversos, calles bloqueadas, redondeo por arista, llegada, final de
descarga, capacidad, omisión y campos adicionales.

Se realizó además una auditoría local con SciPy, codificando cada arista
como `distancia * M + tiempo`, con `M` mayor que el tiempo de cualquier
camino simple. Los 6.561 pares coincidieron exactamente con Dijkstra.

Para repetir esa auditoría opcional en un entorno separado (se usaron
SciPy 1.15.3 y NumPy 1.26.4):

```shell
python -m pip install scipy==1.15.3 numpy==1.26.4
python nivel-2/codigo/auditar_mapa.py --nivel1 originales/nivel-1 --nivel2 originales/nivel-2
```

## Alcance del resultado

El plan publicado atiende 80 pedidos y recorre **61.602 metros**:

| Vehículo | Pedidos | kg | m³ | Distancia (m) | Salida | Regreso |
|---|---:|---:|---:|---:|---|---|
| V1 | 27 | 298,64 | 1,3016 | 20.007 | 08:00:00 | 11:19:26 |
| V2 | 27 | 280,64 | 1,2936 | 21.912 | 08:10:00 | 11:42:41 |
| V3 | 26 | 525,40 | 1,8260 | 19.683 | 08:20:00 | 11:38:42 |

Las tres búsquedas iniciales alcanzaron la misma distancia. La entrega
corresponde al candidato de `PARALLEL_CHEAPEST_INSERTION`, seguido de
120 segundos de refinamiento con cuatro trabajadores. CP-SAT conservó ese
plan, terminó con estado `FEASIBLE` y cota inferior de 46.409 metros.
No es un certificado de optimalidad ni del margen exigido por el juez.
La menor holgura entre fin de descarga y cierre de franja es 108 segundos.

La distancia de referencia de la organización no está en el expediente.
La validación local demuestra el cumplimiento de las restricciones aquí
comprobadas; la evaluación oficial del margen del 10 % corresponde al juez.
Una solución factible encontrada por una heurística no demuestra por sí
sola optimalidad global. El refinador informa su estado y cota inferior.

Referencias de la biblioteca utilizada:

- [OR-Tools: ventanas horarias](https://developers.google.com/optimization/routing/vrptw).
- [OR-Tools: opciones de búsqueda](https://developers.google.com/optimization/routing/routing_options).
