"""Lectura exacta del expediente, grafo dirigido y validación de una entrega.

No consulta servicios de mapas: distancia_m es la distancia del OSM recibido.
Los caminos se comparan lexicográficamente por (metros, segundos).
"""
import csv
import heapq
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
from decimal import Decimal
from fractions import Fraction
from pathlib import Path


def leer_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def segundos(hora):
    if not isinstance(hora, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d", hora):
        raise ValueError(f"Hora no válida: {hora!r}")
    h, m, s = map(int, hora.split(":"))
    return h * 3600 + m * 60 + s


def hora(seg):
    if not 0 <= seg < 86400 or int(seg) != seg:
        raise ValueError(f"Fuera de la jornada: {seg}")
    return f"{seg // 3600:02}:{seg % 3600 // 60:02}:{seg % 60:02}"


def escalar(valor, factor):
    numero = Decimal(str(valor)) * factor
    if numero != numero.to_integral_value():
        raise ValueError(f"Pérdida de precisión: {valor} * {factor}")
    return int(numero)


def leer_grafo(path, velocidades):
    root = ET.parse(path).getroot()
    grafo = {int(e.attrib['id']): [] for e in root.findall('node')}
    bloqueadas = 0
    for way in root.findall('way'):
        tags = {t.attrib['k']: t.attrib['v'] for t in way.findall('tag')}
        if tags.get('access') == 'no':
            bloqueadas += 1
            continue
        refs = [int(n.attrib['ref']) for n in way.findall('nd')]
        # En este expediente cada way es exactamente una arista. No repartir
        # arbitrariamente una distancia entre nodos si cambia el formato.
        if len(refs) != 2:
            raise ValueError(f"Way {way.attrib['id']} no tiene dos extremos")
        distancia = int(tags['distancia_m'])
        if distancia <= 0:
            raise ValueError('Distancia no positiva')
        tiempo_exacto = Fraction(distancia) * Fraction(18, 5) / Fraction(str(velocidades[tags['highway']]))
        tiempo = -(-tiempo_exacto.numerator // tiempo_exacto.denominator)
        a, b = refs
        sentido = tags.get('oneway', 'no')
        if sentido in ('no', 'yes', '1', 'true'):
            grafo[a].append((b, distancia, tiempo))
        if sentido in ('no', '-1'):
            grafo[b].append((a, distancia, tiempo))
        if sentido not in ('no', '-1', 'yes', '1', 'true'):
            raise ValueError(f"Sentido no reconocido: {sentido}")
    return grafo, bloqueadas


def caminos(grafo, origen):
    """Dijkstra con costo de dos componentes, ambos enteros no negativos."""
    mejor = {origen: (0, 0)}
    cola = [(0, 0, origen)]
    while cola:
        d, t, u = heapq.heappop(cola)
        if mejor[u] != (d, t):
            continue
        for v, metros, segundos_arista in grafo[u]:
            candidato = (d + metros, t + segundos_arista)
            if v not in mejor or candidato < mejor[v]:
                mejor[v] = candidato
                heapq.heappush(cola, (*candidato, v))
    return mejor


class Problema:
    def __init__(self, nivel1, nivel2):
        nivel1, nivel2 = Path(nivel1), Path(nivel2)
        self.operacion = leer_json(nivel2 / 'operacion.json')
        self.flota = leer_json(nivel2 / 'flota.json')
        # No se lee pedidos.json del nivel 1.
        self.pedidos = leer_json(nivel2 / 'pedidos.json')
        self.catalogo = {p['producto']: p for p in leer_json(nivel1 / 'catalogo.json')}
        with (nivel1 / 'padron.csv').open(encoding='utf-8-sig', newline='') as f:
            padron = {(r['calle'], int(r['altura']), int(r['nodo'])) for r in csv.DictReader(f)}
        if len({p['pedido'] for p in self.pedidos}) != len(self.pedidos):
            raise ValueError('Pedidos repetidos en la entrada')
        if len({v['vehiculo'] for v in self.flota}) != len(self.flota):
            raise ValueError('Vehículos repetidos en la entrada')
        self.kg = [0]
        self.volumen = [0]
        self.servicio = [0]
        self.ventanas = [(0, 86399)]
        for p in self.pedidos:
            a = p['direccion']
            if (a['calle'], a['altura'], a['nodo']) not in padron:
                raise ValueError(f"Dirección fuera del padrón: {p['pedido']}")
            peso, volumen = Decimal(0), Decimal(0)
            for i in p['items']:
                c = self.catalogo[i['producto']]
                q = Decimal(str(i['cantidad']))
                if q <= 0 or q != q.quantize(Decimal('.01')):
                    raise ValueError('Cantidad inválida')
                if not c['fraccionable'] and q != q.to_integral_value():
                    raise ValueError('Fracción no permitida')
                peso += q * Decimal(str(c['kg']))
                volumen += q * Decimal(str(c['m3']))
            self.kg.append(escalar(peso, 10000))
            self.volumen.append(escalar(volumen, 1000000))
            s = p['descarga_segundos']
            if type(s) is not int or s <= 0:
                raise ValueError('Duración inválida')
            self.servicio.append(s)
            desde, hasta = map(segundos, (p['franja']['desde'], p['franja']['hasta']))
            if desde + s > hasta:
                raise ValueError('No cabe la descarga en la franja')
            self.ventanas.append((desde, hasta - s))
        self.grafo, self.bloqueadas = leer_grafo(nivel2 / 'siracusa.osm', self.operacion['velocidades_kmh'])
        self.nodos = [self.operacion['deposito']] + [p['direccion']['nodo'] for p in self.pedidos]
        resultados = {n: caminos(self.grafo, n) for n in set(self.nodos)}
        if any(b not in resultados[a] for a in self.nodos for b in self.nodos):
            raise ValueError('Algún traslado es inalcanzable')
        self.distancia = [[resultados[a][b][0] for b in self.nodos] for a in self.nodos]
        self.tiempo = [[resultados[a][b][1] for b in self.nodos] for a in self.nodos]
        self.indice = {p['pedido']: i for i, p in enumerate(self.pedidos, 1)}

    def programar(self, secuencias):
        """Genera horarios factibles al partir al comienzo del turno de cada vehículo."""
        rutas = []
        for vehiculo, secuencia in zip(self.flota, secuencias):
            salida = segundos(vehiculo['desde'])
            reloj, anterior = salida, 0
            paradas = []
            for i in secuencia:
                reloj = max(reloj + self.tiempo[anterior][i], self.ventanas[i][0])
                paradas.append({'pedido': self.pedidos[i-1]['pedido'], 'inicio': hora(reloj)})
                reloj += self.servicio[i]
                anterior = i
            reloj += self.tiempo[anterior][0]
            rutas.append({'vehiculo': vehiculo['vehiculo'], 'salida': hora(salida),
                          'paradas': paradas, 'regreso': hora(reloj)})
        plan = {'rutas': rutas}
        self.validar(plan)
        return plan

    def validar(self, plan):
        """Recalcula capacidad, tiempos, distancias, unicidad y esquema, sin solver."""
        if not isinstance(plan, dict) or set(plan) != {'rutas'} or not isinstance(plan['rutas'], list):
            raise ValueError('El objeto debe contener únicamente una lista rutas')
        flota = {v['vehiculo']: v for v in self.flota}
        ids = [r['vehiculo'] for r in plan['rutas']]
        if Counter(ids) != Counter(flota.keys()):
            raise ValueError('Debe haber una fila por vehículo')
        entregados, resumen = [], []
        for r in plan['rutas']:
            if set(r) != {'vehiculo', 'salida', 'paradas', 'regreso'} or not isinstance(r['paradas'], list):
                raise ValueError('Esquema de ruta inválido')
            v = flota[r['vehiculo']]
            salida, regreso = segundos(r['salida']), segundos(r['regreso'])
            if not segundos(v['desde']) <= salida <= regreso <= segundos(v['hasta']):
                raise ValueError(f"Turno incumplido: {v['vehiculo']}")
            reloj, anterior, distancia, conduccion, espera = salida, 0, 0, 0, 0
            peso, volumen, descarga, holgura = 0, 0, 0, 86400
            for parada in r['paradas']:
                if set(parada) != {'pedido', 'inicio'}:
                    raise ValueError('Esquema de parada inválido')
                i = self.indice[parada['pedido']]
                inicio = segundos(parada['inicio'])
                llegada = reloj + self.tiempo[anterior][i]
                desde, ultimo_inicio = self.ventanas[i]
                if inicio < llegada or not desde <= inicio <= ultimo_inicio:
                    raise ValueError(f"Traslado o descarga fuera de franja: {parada['pedido']}")
                distancia += self.distancia[anterior][i]
                conduccion += self.tiempo[anterior][i]
                espera += inicio - llegada
                holgura = min(holgura, ultimo_inicio - inicio)
                peso += self.kg[i]
                volumen += self.volumen[i]
                descarga += self.servicio[i]
                reloj, anterior = inicio + self.servicio[i], i
                entregados.append(parada['pedido'])
            distancia += self.distancia[anterior][0]
            conduccion += self.tiempo[anterior][0]
            llegada_deposito = reloj + self.tiempo[anterior][0]
            if regreso != llegada_deposito:
                raise ValueError('Regreso no coincide con llegada al depósito')
            if peso > escalar(v['capacidad_kg'], 10000) or volumen > escalar(v['capacidad_m3'], 1000000):
                raise ValueError(f"Capacidad excedida: {v['vehiculo']}")
            resumen.append(dict(vehiculo=v['vehiculo'], pedidos=len(r['paradas']),
                                kg=peso / 10000, m3=volumen / 1000000,
                                distancia_m=distancia, conduccion_s=conduccion,
                                descarga_s=descarga, espera_s=espera,
                                holgura_minima_s=holgura if r['paradas'] else None,
                                salida=r['salida'], regreso=r['regreso']))
        if Counter(entregados) != Counter(self.indice.keys()):
            raise ValueError('Hay pedidos omitidos o entregados más de una vez')
        return dict(valido=True, pedidos=len(entregados),
                    distancia_total_m=sum(r['distancia_m'] for r in resumen), rutas=resumen)
