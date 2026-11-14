"""Nivel 2 · Rutas de reparto de La Palanca.

Uso:
    python resolver.py --datos <carpeta con los archivos> --salida ../rutas.json [--iter 40000] [--semilla 7]

Modelo: VRP con ventanas horarias (VRPTW), capacidad en kg y m3, turno por vehículo,
una salida por vehículo, sin recarga ni pedidos divididos. Objetivo: minimizar la
distancia total (incluye salidas y regresos al depósito).

Método: construcción por inserción con arrepentimiento (regret-2) y mejora por
búsqueda de vecindad grande (LNS: destruir y reparar) con aceptación tipo
recocido simulado. Toda solución aceptada es factible.
"""
import argparse
import csv
import json
import math
import os
import random

import grafo

EPS = 1e-9


def hms(s):
    h, m, x = map(int, s.split(":"))
    return h * 3600 + m * 60 + x


def fmt(s):
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


class Problema:
    def __init__(self, carpeta):
        leer = lambda n: json.load(open(os.path.join(carpeta, n), encoding="utf-8"))
        self.op = leer("operacion.json")
        self.flota = leer("flota.json")
        self.pedidos = leer("pedidos.json")
        cat = {c["producto"]: c for c in leer("catalogo.json")}
        padron = {(r["calle"], int(r["altura"]), int(r["nodo"]))
                  for r in csv.DictReader(open(os.path.join(carpeta, "padron.csv"), encoding="utf-8"))}

        self.dep = self.op["deposito"]
        self.n = len(self.pedidos)
        self.nodo, self.kg, self.m3, self.a, self.b, self.s = [], [], [], [], [], []
        for p in self.pedidos:
            d = p["direccion"]
            assert (d["calle"], d["altura"], d["nodo"]) in padron, p["pedido"]
            kg = m3 = 0.0
            for it in p["items"]:
                c = cat[it["producto"]]
                assert c["fraccionable"] or float(it["cantidad"]).is_integer(), p["pedido"]
                kg += c["kg"] * it["cantidad"]
                m3 += c["m3"] * it["cantidad"]
            self.nodo.append(d["nodo"])
            self.kg.append(kg)
            self.m3.append(m3)
            self.a.append(hms(p["franja"]["desde"]))
            self.b.append(hms(p["franja"]["hasta"]))
            self.s.append(p["descarga_segundos"])

        adj = grafo.cargar_grafo(os.path.join(carpeta, "siracusa.osm"), self.op["velocidades_kmh"])
        nodos = [self.dep] + self.nodo
        Dn, Tn = grafo.matriz(adj, list(dict.fromkeys(nodos)))
        # índice 0..n-1 = pedidos, n = depósito
        idx = self.nodo + [self.dep]
        self.D = [[Dn[u, v] for v in idx] for u in idx]
        self.T = [[Tn[u, v] for v in idx] for u in idx]

    # ---- evaluación de una ruta ----
    def factible(self, v, ruta):
        f = self.flota[v]
        if sum(self.kg[i] for i in ruta) > f["capacidad_kg"] + EPS:
            return False
        if sum(self.m3[i] for i in ruta) > f["capacidad_m3"] + EPS:
            return False
        return self.horario(v, ruta) is not None

    def horario(self, v, ruta):
        """Horas de inicio de descarga (lo antes posible) o None si no cumple."""
        f = self.flota[v]
        t, prev, inicios = hms(f["desde"]), self.n, []
        for i in ruta:
            t += self.T[prev][i]
            ini = max(t, self.a[i])
            if ini + self.s[i] > self.b[i]:
                return None
            inicios.append(ini)
            t = ini + self.s[i]
            prev = i
        t += self.T[prev][self.n]
        if t > hms(f["hasta"]):
            return None
        return inicios, t

    def dist(self, ruta):
        if not ruta:
            return 0
        d, prev = 0, self.n
        for i in ruta:
            d += self.D[prev][i]
            prev = i
        return d + self.D[prev][self.n]


# ---- búsqueda ----
def mejor_insercion(P, sol, i):
    """Lista de (costo, v, pos) factibles para insertar el pedido i."""
    opciones = []
    for v, ruta in enumerate(sol):
        f = P.flota[v]
        if sum(P.kg[j] for j in ruta) + P.kg[i] > f["capacidad_kg"] + EPS:
            continue
        if sum(P.m3[j] for j in ruta) + P.m3[i] > f["capacidad_m3"] + EPS:
            continue
        ext = [P.n] + ruta + [P.n]
        for pos in range(len(ruta) + 1):
            u, w = ext[pos], ext[pos + 1]
            delta = P.D[u][i] + P.D[i][w] - P.D[u][w]
            opciones.append((delta, v, pos))
    opciones.sort()
    validas = []
    for delta, v, pos in opciones:
        nueva = sol[v][:pos] + [i] + sol[v][pos:]
        if P.horario(v, nueva) is not None:
            validas.append((delta, v, pos))
            if len({x[1] for x in validas}) >= 2 and len(validas) >= 2:
                break
    return validas


def reparar(P, sol, pendientes, rnd):
    """Inserta por arrepentimiento (regret-2). Devuelve los pedidos que no entraron."""
    pendientes = list(pendientes)
    sin_lugar = []
    while pendientes:
        mejor = None
        for i in pendientes:
            ops = mejor_insercion(P, sol, i)
            if not ops:
                regret = math.inf  # sin lugar: se decide ya
                cand = (regret, i, None)
            else:
                otro = next((o[0] for o in ops if o[1] != ops[0][1]), ops[0][0] + 10**6)
                cand = (otro - ops[0][0] + rnd.random() * 1e-3, i, ops[0])
            if mejor is None or cand[0] > mejor[0]:
                mejor = cand
        _, i, op = mejor
        pendientes.remove(i)
        if op is None:
            sin_lugar.append(i)
        else:
            sol[op[1]].insert(op[2], i)
    return sin_lugar


def destruir(P, sol, k, rnd):
    todos = [i for r in sol for i in r]
    modo = rnd.random()
    if modo < 0.4:  # aleatorio
        quitar = set(rnd.sample(todos, k))
    elif modo < 0.8:  # relacionados (cercanía en espacio y tiempo)
        semilla = rnd.choice(todos)
        cerca = sorted(todos, key=lambda j: P.D[semilla][j] + P.D[j][semilla]
                       + 3 * abs(P.a[semilla] - P.a[j]))
        quitar = set(cerca[:k])
    else:  # tramo consecutivo de una ruta
        r = rnd.choice([r for r in sol if r])
        ini = rnd.randrange(len(r))
        quitar = set(r[ini:ini + k])
    for r in sol:
        r[:] = [i for i in r if i not in quitar]
    return list(quitar)


PENALIDAD = 10**6  # por pedido sin asignar (solo durante la búsqueda)


def total(P, sol):
    return sum(P.dist(r) for r in sol)


def resolver(P, iteraciones, semilla, segundos=None):
    import time
    fin = time.time() + segundos if segundos else math.inf
    rnd = random.Random(semilla)
    sol = [[] for _ in P.flota]
    orden = sorted(range(P.n), key=lambda i: P.b[i])
    libres = reparar(P, sol, orden, rnd)
    actual, act_libres = sol, libres
    costo = total(P, sol) + PENALIDAD * len(libres)
    mejor, mejor_libres, mejor_costo = [r[:] for r in sol], list(libres), costo
    temp0 = 600.0
    for it in range(iteraciones):
        if time.time() > fin:
            break
        temp = temp0 * (1 - it / iteraciones) + 1
        cand = [r[:] for r in actual]
        k = rnd.randint(3, 15)
        quitados = destruir(P, cand, k, rnd) + list(act_libres)
        rnd.shuffle(quitados)
        cand_libres = reparar(P, cand, quitados, rnd)
        c = total(P, cand) + PENALIDAD * len(cand_libres)
        if c < costo or rnd.random() < math.exp(max(-50, (costo - c) / temp)):
            actual, act_libres, costo = cand, cand_libres, c
            if c < mejor_costo:
                mejor, mejor_libres, mejor_costo = [r[:] for r in cand], list(cand_libres), c
    if mejor_libres:
        raise RuntimeError(f"Quedaron {len(mejor_libres)} pedidos sin asignar")
    return mejor, mejor_costo


def salida_json(P, sol):
    rutas = []
    for v, ruta in enumerate(sol):
        f = P.flota[v]
        assert P.factible(v, ruta)
        if not ruta:
            rutas.append({"vehiculo": f["vehiculo"], "salida": f["desde"], "paradas": [],
                          "regreso": f["desde"]})
            continue
        inicios, regreso = P.horario(v, ruta)
        # se sale lo más tarde posible sin cambiar ningún inicio (evita esperas innecesarias)
        salida = hms(f["desde"])
        t, prev = salida, P.n
        holgura = math.inf
        for i, ini in zip(ruta, inicios):
            t += P.T[prev][i]
            holgura = min(holgura, ini - t)
            t = ini + P.s[i]
            prev = i
        salida += holgura if holgura != math.inf else 0
        rutas.append({
            "vehiculo": f["vehiculo"],
            "salida": fmt(salida),
            "paradas": [{"pedido": P.pedidos[i]["pedido"], "inicio": fmt(ini)}
                        for i, ini in zip(ruta, inicios)],
            "regreso": fmt(regreso),
        })
    return {"rutas": rutas}


def verificar(P, plan):
    """Recalcula todo desde cero sobre el JSON final, como lo haría el juez."""
    ids = {p["pedido"]: i for i, p in enumerate(P.pedidos)}
    vistos, km = [], 0
    for r, f in zip(plan["rutas"], P.flota):
        t, prev = hms(r["salida"]), P.n
        assert t >= hms(f["desde"])
        kg = m3 = 0
        for pa in r["paradas"]:
            i = ids[pa["pedido"]]
            vistos.append(i)
            km += P.D[prev][i]
            t += P.T[prev][i]
            ini = hms(pa["inicio"])
            assert ini >= t and ini >= P.a[i] and ini + P.s[i] <= P.b[i], pa
            t = ini + P.s[i]
            kg += P.kg[i]
            m3 += P.m3[i]
            prev = i
        km += P.D[prev][P.n]
        t += P.T[prev][P.n]
        if r["paradas"]:
            assert t == hms(r["regreso"]) and t <= hms(f["hasta"]), r["vehiculo"]
        assert kg <= f["capacidad_kg"] + EPS and m3 <= f["capacidad_m3"] + EPS
    assert sorted(vistos) == list(range(P.n)), "faltan o se repiten pedidos"
    return km


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--datos", default="datos")
    ap.add_argument("--salida", default="../rutas.json")
    ap.add_argument("--iter", type=int, default=40000)
    ap.add_argument("--semilla", type=int, default=7)
    ap.add_argument("--segundos", type=float, default=None, help="tope de tiempo de búsqueda")
    args = ap.parse_args()
    P = Problema(args.datos)
    sol, costo = resolver(P, args.iter, args.semilla, args.segundos)
    plan = salida_json(P, sol)
    ids = {p["pedido"]: i for i, p in enumerate(P.pedidos)}
    metros = verificar(P, plan)
    with open(args.salida, "w", encoding="utf-8") as fh:
        json.dump(plan, fh, ensure_ascii=False, indent=2)
    print(f"Distancia total: {metros / 1000:.3f} km")
    for r, f in zip(plan["rutas"], P.flota):
        idx = [ids[x["pedido"]] for x in r["paradas"]]
        print(f'{r["vehiculo"]}: {len(idx)} pedidos, {sum(P.kg[i] for i in idx):.2f} kg, '
              f'{sum(P.m3[i] for i in idx):.3f} m3, {r["salida"]}-{r["regreso"]}')
