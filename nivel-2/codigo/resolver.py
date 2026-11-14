"""Optimiza distancia total mediante OR-Tools y valida antes de guardar.

Uso completo y decisiones del modelo en README.md. No hay rutas prefijadas.
"""
import argparse
import json
import time
from pathlib import Path

from ortools.constraint_solver import pywrapcp, routing_enums_pb2
from problema import Problema, escalar, leer_json, segundos


def resolver(problema, limite, estrategia, semilla=None):
    n, k = len(problema.nodos), len(problema.flota)
    manager = pywrapcp.RoutingIndexManager(n, k, 0)
    routing = pywrapcp.RoutingModel(manager)
    def metros(a, b):
        return problema.distancia[manager.IndexToNode(a)][manager.IndexToNode(b)]
    costo = routing.RegisterTransitCallback(metros)
    routing.SetArcCostEvaluatorOfAllVehicles(costo)

    def traslado_y_descarga(a, b):
        i, j = manager.IndexToNode(a), manager.IndexToNode(b)
        return problema.servicio[i] + problema.tiempo[i][j]
    transit = routing.RegisterTransitCallback(traslado_y_descarga)
    routing.AddDimension(transit, 86400, 86399, False, 'Tiempo')
    tiempo = routing.GetDimensionOrDie('Tiempo')
    for i in range(1, n):
        tiempo.CumulVar(manager.NodeToIndex(i)).SetRange(*problema.ventanas[i])
    for v, camioneta in enumerate(problema.flota):
        inicio, fin = segundos(camioneta['desde']), segundos(camioneta['hasta'])
        tiempo.CumulVar(routing.Start(v)).SetRange(inicio, inicio)
        tiempo.CumulVar(routing.End(v)).SetRange(inicio, fin)
    for nombre, demandas, campo, factor in (
        ('Peso', problema.kg, 'capacidad_kg', 10000),
        ('Volumen', problema.volumen, 'capacidad_m3', 1000000),
    ):
        # Mantener referencias a las listas mediante argumento por defecto.
        def demanda(index, valores=demandas):
            return valores[manager.IndexToNode(index)]
        callback = routing.RegisterUnaryTransitCallback(demanda)
        routing.AddDimensionWithVehicleCapacity(
            callback, 0, [escalar(v[campo], factor) for v in problema.flota], True, nombre)

    # La búsqueda puede pasar por soluciones incompletas para escapar de
    # callejones sin salida de la inserción. La penalización domina cualquier
    # distancia posible: (n-1+k) tramos como máximo. Nunca se exporta una
    # solución incompleta: se comprueba cobertura al terminar y al validar.
    penalizacion = max(max(row) for row in problema.distancia) * (n + k) + 1
    for i in range(1, n):
        routing.AddDisjunction([manager.NodeToIndex(i)], penalizacion)
    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = getattr(routing_enums_pb2.FirstSolutionStrategy, estrategia)
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    params.time_limit.seconds = limite
    params.log_search = False
    mejor = [None]
    comienzo = time.monotonic()
    def progreso():
        valor = routing.CostVar().Value()
        if mejor[0] is None or valor < mejor[0]:
            mejor[0] = valor
            omitidos = sum(routing.NextVar(manager.NodeToIndex(i)).Value() == manager.NodeToIndex(i) for i in range(1, n))
            print(json.dumps({'segundos': round(time.monotonic()-comienzo, 1),
                              'omitidos': omitidos, 'distancia_m': valor - omitidos * penalizacion}), flush=True)
    routing.AddAtSolutionCallback(progreso)
    if semilla:
        problema.validar(semilla)
        por_vehiculo = {r['vehiculo']: r for r in semilla['rutas']}
        rutas = [[problema.indice[p['pedido']] for p in por_vehiculo[v['vehiculo']]['paradas']]
                 for v in problema.flota]
        initial = routing.ReadAssignmentFromRoutes(rutas, True)
        if initial is None:
            raise ValueError('La semilla no es admisible para el modelo')
        solucion = routing.SolveFromAssignmentWithParameters(initial, params)
    else:
        solucion = routing.SolveWithParameters(params)
    if solucion is None:
        raise RuntimeError(f'No se encontró solución; status={routing.status()}')
    secuencias = []
    for v in range(k):
        secuencia, index = [], routing.Start(v)
        while not routing.IsEnd(index):
            node = manager.IndexToNode(index)
            if node:
                secuencia.append(node)
            index = solucion.Value(routing.NextVar(index))
        secuencias.append(secuencia)
    presentes = [i for ruta in secuencias for i in ruta]
    faltantes = sorted(set(range(1, n)) - set(presentes))
    if faltantes:
        raise RuntimeError(f'No se exporta: faltan {len(faltantes)} pedidos: {faltantes}')
    return problema.programar(secuencias)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--nivel1', required=True, type=Path, help='Carpeta con catalogo.json y padron.csv originales')
    parser.add_argument('--nivel2', required=True, type=Path, help='Carpeta con los cuatro archivos originales de nivel 2')
    parser.add_argument('--salida', required=True, type=Path)
    parser.add_argument('--segundos', type=int, default=180)
    parser.add_argument('--estrategia', choices=['PARALLEL_CHEAPEST_INSERTION', 'PATH_CHEAPEST_ARC', 'LOCAL_CHEAPEST_INSERTION', 'SAVINGS'], default='PARALLEL_CHEAPEST_INSERTION')
    parser.add_argument('--semilla', type=Path, help='Plan válido anterior para continuar la mejora')
    args = parser.parse_args()
    if args.segundos <= 0:
        parser.error('--segundos debe ser positivo')
    problema = Problema(args.nivel1, args.nivel2)
    print(json.dumps({'pedidos':len(problema.pedidos), 'nodos':len(problema.grafo),
                      'ways_prohibidos':problema.bloqueadas,
                      'kg_totales':sum(problema.kg)/10000,
                      'm3_totales':sum(problema.volumen)/1000000}), flush=True)
    plan = resolver(problema, args.segundos, args.estrategia, leer_json(args.semilla) if args.semilla else None)
    informe = problema.validar(plan)
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    args.salida.write_text(json.dumps(plan, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(informe, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
