"""Auditoría opcional contra una segunda implementación de caminos mínimos.

Requiere SciPy y NumPy; no son necesarios para generar ni validar la entrega.
No depende de las matrices del optimizador para calcular caminos alternativos:
usa el grafo leído y scipy.sparse.csgraph.dijkstra con un costo escalar exacto.
"""
import argparse
from pathlib import Path
import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra
from scipy.optimize import linear_sum_assignment
from problema import Problema, segundos


def auditar(p):
    nodos = sorted(p.grafo)
    indice = {v:i for i,v in enumerate(nodos)}
    # Un camino óptimo con costos positivos es simple. Su tiempo no supera
    # (N-1)*max_t, por lo que M domina todo desempate temporal posible.
    escala = len(nodos)*max(t for edges in p.grafo.values() for _,_,t in edges)+1
    aristas = {}
    for a, destinos in p.grafo.items():
        for b,d,t in destinos:
            key = indice[a],indice[b]
            aristas[key] = min(aristas.get(key,float('inf')),d*escala+t)
    # SciPy usa float64; estos enteros y las sumas de caminos simples quedan
    # por debajo de 2**53, conservando representación entera exacta.
    if len(nodos)*max(aristas.values()) >= 2**53:
        raise ValueError('El costo escalar supera la precisión exacta de float64')
    g = csr_matrix((list(aristas.values()),([a for a,b in aristas],[b for a,b in aristas])),shape=(len(nodos),len(nodos)))
    distancias = dijkstra(g,directed=True,indices=[indice[n] for n in p.nodos])
    for i in range(len(p.nodos)):
        for j in range(len(p.nodos)):
            calculado = divmod(int(distancias[i,indice[p.nodos[j]]]),escala)
            if calculado != (p.distancia[i][j],p.tiempo[i][j]):
                raise ValueError(f'Diferencia en {i}, {j}: {calculado}')
    print(f'Auditoría correcta: {len(p.nodos)**2} pares dirigidos.')

    # Relajación de asignación: cada cliente tiene un sucesor y un predecesor,
    # con una copia de depósito por vehículo. Se relajan conectividad,
    # identidad de vehículo y capacidades; por ello es una cota inferior,
    # no una ruta válida ni una estimación de la referencia de la organización.
    n,k = len(p.pedidos),len(p.flota)
    prohibido = max(map(max,p.distancia))*(n+k)+1
    costos = np.full((n+k,n+k),prohibido,dtype=np.int64)
    for a in range(n+k):
        i = a+1 if a<n else 0
        temprano = p.ventanas[i][0] if i else segundos(p.flota[a-n]['desde'])
        for b in range(n+k):
            j = b+1 if b<n else 0
            tarde = p.ventanas[j][1] if j else segundos(p.flota[b-n]['hasta'])
            if i and i==j:
                continue
            if temprano+p.servicio[i]+p.tiempo[i][j] <= tarde:
                costos[a,b] = p.distancia[i][j]
    filas,columnas = linear_sum_assignment(costos)
    if any(costos[a,b] == prohibido for a,b in zip(filas,columnas)):
        raise ValueError('La relajación de asignación no es factible')
    print('Cota inferior por asignación:',int(costos[filas,columnas].sum()),'m')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--nivel1',required=True,type=Path)
    parser.add_argument('--nivel2',required=True,type=Path)
    args = parser.parse_args()
    auditar(Problema(args.nivel1,args.nivel2))
