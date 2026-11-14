"""Modelo entero CP-SAT para mejorar una semilla y calcular una cota inferior.

Un arco entre clientes propaga vehículo y tiempo. Las duraciones positivas
eliminan ciclos desconectados. Cada vehículo tiene una salida y un regreso
como máximo, y dos capacidades. La distancia es la única función objetivo.
"""
import argparse
import json
from pathlib import Path
from ortools.sat.python import cp_model
from problema import Problema, escalar, leer_json, segundos


def refinar(p, semilla, limite, trabajadores):
    p.validar(semilla)
    n, k = len(p.pedidos), len(p.flota)
    m = cp_model.CpModel()
    clientes = range(1, n+1)
    tiempos = {i:m.new_int_var(*p.ventanas[i], f't_{i}') for i in clientes}
    camion = {i:m.new_int_var(0, k-1, f'v_{i}') for i in clientes}
    pertenece = {(i,v):m.new_bool_var(f'y_{i}_{v}') for i in clientes for v in range(k)}
    for i in clientes:
        m.add_exactly_one(pertenece[i,v] for v in range(k))
        for v in range(k):
            m.add(camion[i] == v).only_enforce_if(pertenece[i,v])
    for v, vehiculo in enumerate(p.flota):
        m.add(sum(p.kg[i]*pertenece[i,v] for i in clientes) <= escalar(vehiculo['capacidad_kg'],10000))
        m.add(sum(p.volumen[i]*pertenece[i,v] for i in clientes) <= escalar(vehiculo['capacidad_m3'],1000000))
    arcos, entradas, salidas = {}, {i:[] for i in clientes}, {i:[] for i in clientes}
    objetivo = []
    for i in clientes:
        for j in clientes:
            if i == j or p.ventanas[i][0]+p.servicio[i]+p.tiempo[i][j] > p.ventanas[j][1]:
                continue
            x = m.new_bool_var(f'x_{i}_{j}')
            arcos[i,j] = x
            entradas[j].append(x)
            salidas[i].append(x)
            m.add(tiempos[j] >= tiempos[i]+p.servicio[i]+p.tiempo[i][j]).only_enforce_if(x)
            m.add(camion[i] == camion[j]).only_enforce_if(x)
            objetivo.append(p.distancia[i][j]*x)
    primeros, ultimos = {}, {}
    for v, vehiculo in enumerate(p.flota):
        salida, fin = segundos(vehiculo['desde']), segundos(vehiculo['hasta'])
        inicios, finales = [], []
        for i in clientes:
            if salida+p.tiempo[0][i] <= p.ventanas[i][1]:
                x = m.new_bool_var(f'inicio_{v}_{i}')
                primeros[v,i] = x
                entradas[i].append(x)
                inicios.append(x)
                m.add(camion[i] == v).only_enforce_if(x)
                m.add(tiempos[i] >= salida+p.tiempo[0][i]).only_enforce_if(x)
                objetivo.append(p.distancia[0][i]*x)
            if p.ventanas[i][0]+p.servicio[i]+p.tiempo[i][0] <= fin:
                x = m.new_bool_var(f'fin_{v}_{i}')
                ultimos[v,i] = x
                salidas[i].append(x)
                finales.append(x)
                m.add(camion[i] == v).only_enforce_if(x)
                m.add(tiempos[i]+p.servicio[i]+p.tiempo[i][0] <= fin).only_enforce_if(x)
                objetivo.append(p.distancia[i][0]*x)
        usado = m.new_bool_var(f'usado_{v}')
        m.add(sum(inicios) == usado)
        m.add(sum(finales) == usado)
        m.add(sum(pertenece[i,v] for i in clientes) <= n*usado)
    for i in clientes:
        m.add_exactly_one(entradas[i])
        m.add_exactly_one(salidas[i])
    costo = sum(objetivo)
    m.minimize(costo)
    referencia = p.validar(semilla)['distancia_total_m']
    m.add(costo <= referencia)
    rutas_semilla = {r['vehiculo']:r for r in semilla['rutas']}
    active_arcs, active_first, active_last = set(), set(), set()
    for v, vehiculo in enumerate(p.flota):
        ruta = rutas_semilla[vehiculo['vehiculo']]['paradas']
        ids = [p.indice[s['pedido']] for s in ruta]
        if ids:
            active_first.add((v,ids[0]))
            active_last.add((v,ids[-1]))
        active_arcs.update(zip(ids,ids[1:]))
        for parada,i in zip(ruta,ids):
            m.add_hint(tiempos[i],segundos(parada['inicio']))
            m.add_hint(camion[i],v)
            for vv in range(k):
                m.add_hint(pertenece[i,vv],int(v==vv))
    for grupo, activos in ((arcos,active_arcs),(primeros,active_first),(ultimos,active_last)):
        for key,var in grupo.items():m.add_hint(var,int(key in activos))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = limite
    solver.parameters.num_search_workers = trabajadores
    solver.parameters.random_seed = 20261114
    solver.parameters.log_search_progress = True
    status = solver.solve(m)
    estadisticas = dict(estado=solver.status_name(status), cota_inferior_m=solver.best_objective_bound,
                       segundos=solver.wall_time)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return semilla, estadisticas
    sucesor = {i:j for (i,j),x in arcos.items() if solver.value(x)}
    secuencias = []
    for v in range(k):
        inicio = [i for (vv,i),x in primeros.items() if vv==v and solver.value(x)]
        secuencia = []
        if inicio:
            i = inicio[0]
            while True:
                if i in secuencia:
                    raise ValueError('Ciclo inesperado')
                secuencia.append(i)
                if i not in sucesor:break
                i = sucesor[i]
        secuencias.append(secuencia)
    plan = p.programar(secuencias)
    assert p.validar(plan)['distancia_total_m'] <= referencia
    return plan, estadisticas


def main():
    a = argparse.ArgumentParser(description=__doc__)
    a.add_argument('--nivel1', required=True, type=Path)
    a.add_argument('--nivel2', required=True, type=Path)
    a.add_argument('--semilla', required=True, type=Path)
    a.add_argument('--salida', required=True, type=Path)
    a.add_argument('--segundos', type=int, default=120)
    a.add_argument('--trabajadores', type=int, default=4)
    a.add_argument('--informe', type=Path)
    args = a.parse_args()
    p = Problema(args.nivel1,args.nivel2)
    plan, estadisticas = refinar(p,leer_json(args.semilla),args.segundos,args.trabajadores)
    informe = {**p.validar(plan), 'optimizacion':estadisticas}
    args.salida.write_text(json.dumps(plan,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if args.informe:
        args.informe.write_text(json.dumps(informe,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(informe,ensure_ascii=False,indent=2),flush=True)


if __name__ == '__main__':
    main()
