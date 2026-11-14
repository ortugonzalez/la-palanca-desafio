# Nivel 2 · Rutas de reparto

## Archivos
- `grafo.py`: lee `siracusa.osm` y calcula caminos según `operacion.json`:
  menor distancia dirigida con desempate por menor tiempo, sin aristas `access=no`,
  `oneway` (`yes`, `-1`, `no`) y tiempo por arista `ceil(distancia_m * 3.6 / velocidad_kmh)`
  sumado en segundos enteros.
- `resolver.py`: arma y optimiza las rutas (VRP con ventanas horarias) y escribe `rutas.json`.

## Uso
Requiere Python 3.9+ sin dependencias externas.

```
python resolver.py --datos <carpeta> --salida ../rutas.json --semilla 3 --segundos 75
```

`<carpeta>` debe contener `pedidos.json`, `siracusa.osm`, `flota.json`, `operacion.json`,
`catalogo.json` y `padron.csv`.

## Modelo
- Una salida por vehículo, vuelta al depósito (nodo 1026), sin recarga ni pedidos divididos.
- Capacidad en kg y m3 por vehículo, calculada con el catálogo (incluye envases).
- La salida no es anterior al inicio del turno y el regreso no es posterior a su fin.
- Cada descarga completa (inicio + `descarga_segundos`) cae dentro de la franja del cliente.
  Se permite esperar antes de descargar, y las descargas de un vehículo no se superponen.
- Se valida que cada dirección exista en el padrón y que las cantidades respeten la fraccionabilidad.

## Método
1. Matriz de distancias y tiempos entre el depósito y los 80 domicilios (Dijkstra lexicográfico).
2. Solución inicial por inserción con arrepentimiento (regret-2), ordenando los pedidos por cierre de franja.
3. Mejora por búsqueda de vecindad grande (LNS): se quitan de 3 a 15 pedidos
   (al azar, relacionados por cercanía y horario, o un tramo de ruta) y se reinsertan.
   La aceptación es tipo recocido simulado. Los pedidos sin lugar se penalizan durante la búsqueda;
   la solución final los tiene todos asignados.
4. `verificar()` recalcula el plan final desde cero: horarios, franjas, capacidades, turnos,
   que no falten ni se repitan pedidos, y la distancia total.
5. La salida se demora lo máximo posible sin cambiar ningún inicio, para evitar esperas en ruta.

Resultado entregado: semilla 3, 62,694 km en total, con los 80 pedidos.
