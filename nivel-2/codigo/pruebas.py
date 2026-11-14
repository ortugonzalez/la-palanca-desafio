"""Pruebas de reglas que podrían producir rutas aparentemente válidas."""
import copy
import tempfile
import unittest
from pathlib import Path
from problema import Problema, caminos, leer_grafo


class PruebasMapa(unittest.TestCase):
    def test_prioridad_distancia_y_desempate_tiempo(self):
        g = {1: [(2, 10, 50), (3, 6, 1)], 2: [], 3: [(2, 5, 1)]}
        self.assertEqual(caminos(g, 1)[2], (10, 50))
        g[3] = [(2, 4, 1)]
        self.assertEqual(caminos(g, 1)[2], (10, 2))

    def test_sentidos_bloqueos_y_redondeo_por_arista(self):
        xml = '''<osm>
        <node id="1"/><node id="2"/><node id="3"/><node id="4"/>
        <way id="1"><nd ref="1"/><nd ref="2"/><tag k="highway" v="residential"/><tag k="distancia_m" v="101"/><tag k="oneway" v="yes"/></way>
        <way id="2"><nd ref="3"/><nd ref="2"/><tag k="highway" v="residential"/><tag k="distancia_m" v="101"/><tag k="oneway" v="-1"/></way>
        <way id="3"><nd ref="1"/><nd ref="3"/><tag k="highway" v="residential"/><tag k="distancia_m" v="1"/><tag k="access" v="no"/></way>
        <way id="4"><nd ref="3"/><nd ref="4"/><tag k="highway" v="residential"/><tag k="distancia_m" v="10"/><tag k="oneway" v="no"/></way>
        </osm>'''
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'mapa.osm'
            path.write_text(xml, encoding='utf-8')
            g, cerradas = leer_grafo(path, {'residential': 24})
        self.assertEqual(cerradas, 1)
        self.assertEqual(caminos(g, 1)[3], (202, 32))
        self.assertNotIn(1, caminos(g, 2))
        self.assertEqual(caminos(g, 4)[3], (10, 2))


class PruebasPlan(unittest.TestCase):
    def setUp(self):
        p = Problema.__new__(Problema)
        p.flota = [dict(vehiculo='V1', desde='08:00:00', hasta='09:00:00', capacidad_kg=1, capacidad_m3=1)]
        p.indice = {'P2-001': 1}
        p.ventanas = [(0, 86399), (8*3600, 8*3600+120)]
        p.servicio = [0, 60]
        p.kg = [0, 10000]
        p.volumen = [0, 1000000]
        p.distancia = [[0, 100], [200, 0]]
        p.tiempo = [[0, 30], [40, 0]]
        self.p = p
        self.plan = {'rutas': [dict(vehiculo='V1', salida='08:00:00', paradas=[dict(pedido='P2-001', inicio='08:01:00')], regreso='08:02:40')]}

    def test_plan_valido_y_distancia_dirigida(self):
        informe = self.p.validar(self.plan)
        self.assertEqual(informe['distancia_total_m'], 300)
        self.assertEqual(informe['rutas'][0]['espera_s'], 30)

    def test_descarga_completa_y_llegada(self):
        for inicio in ('08:02:01', '08:00:29'):
            plan = copy.deepcopy(self.plan)
            plan['rutas'][0]['paradas'][0]['inicio'] = inicio
            with self.assertRaises(ValueError):
                self.p.validar(plan)

    def test_capacidad(self):
        self.p.kg[1] += 1
        with self.assertRaises(ValueError):
            self.p.validar(self.plan)

    def test_omision(self):
        plan = copy.deepcopy(self.plan)
        plan['rutas'][0]['paradas'] = []
        plan['rutas'][0]['regreso'] = '08:00:00'
        with self.assertRaises(ValueError):
            self.p.validar(plan)

    def test_campos_adicionales(self):
        self.plan['rutas'][0]['distancia'] = 300
        with self.assertRaises(ValueError):
            self.p.validar(self.plan)


if __name__ == '__main__':
    unittest.main()
