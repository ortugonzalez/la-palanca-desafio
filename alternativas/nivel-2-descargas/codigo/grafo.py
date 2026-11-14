"""Lectura del mapa OSM y cálculo de recorridos según operacion.json.

Reglas (operacion.json):
- recorrido: menor distancia dirigida; empate por menor tiempo.
- access=no no es transitable.
- tiempo_arista = ceil(distancia_m * 3.6 / velocidad_kmh), en segundos enteros por arista.
- oneway: "yes" = sentido de los nodos; "-1" = sentido inverso; "no" = doble mano.
"""
import heapq
import math
import xml.etree.ElementTree as ET


def cargar_grafo(ruta_osm, velocidades):
    """Devuelve adyacencia dirigida: nodo -> lista de (vecino, metros, segundos)."""
    adj = {}
    for _, el in ET.iterparse(ruta_osm, events=("end",)):
        if el.tag == "node":
            adj.setdefault(int(el.get("id")), [])
        elif el.tag == "way":
            nds = [int(nd.get("ref")) for nd in el.findall("nd")]
            tags = {t.get("k"): t.get("v") for t in el.findall("tag")}
            el.clear()
            if tags.get("access") == "no":
                continue
            vel = velocidades[tags["highway"]]
            dist = int(tags["distancia_m"])
            seg = math.ceil(dist * 3.6 / vel)
            sentido = tags.get("oneway", "no")
            for a, b in zip(nds, nds[1:]):
                if sentido in ("no", "yes"):
                    adj.setdefault(a, []).append((b, dist, seg))
                if sentido in ("no", "-1"):
                    adj.setdefault(b, []).append((a, dist, seg))
    return adj


def dijkstra(adj, origen):
    """Camino mínimo lexicográfico (metros, segundos) desde origen a todos los nodos."""
    mejor = {origen: (0, 0)}
    cola = [(0, 0, origen)]
    while cola:
        d, t, u = heapq.heappop(cola)
        if (d, t) > mejor.get(u, (math.inf, math.inf)):
            continue
        for v, dm, ts in adj.get(u, ()):
            cand = (d + dm, t + ts)
            if cand < mejor.get(v, (math.inf, math.inf)):
                mejor[v] = cand
                heapq.heappush(cola, (cand[0], cand[1], v))
    return mejor


def matriz(adj, nodos):
    """Matrices de distancia (m) y tiempo (s) entre todos los nodos pedidos."""
    D, T = {}, {}
    for o in nodos:
        res = dijkstra(adj, o)
        for d in nodos:
            if d not in res:
                raise ValueError(f"Nodo {d} inalcanzable desde {o}")
            D[o, d], T[o, d] = res[d]
    return D, T
