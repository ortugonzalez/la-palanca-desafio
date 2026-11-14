"""Validación independiente del optimizador; solo requiere Python estándar."""
import argparse
import json
from pathlib import Path
from problema import Problema, leer_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--nivel1', required=True, type=Path)
    parser.add_argument('--nivel2', required=True, type=Path)
    parser.add_argument('--rutas', required=True, type=Path)
    parser.add_argument('--informe', type=Path)
    args = parser.parse_args()
    problema = Problema(args.nivel1, args.nivel2)
    informe = problema.validar(leer_json(args.rutas))
    text = json.dumps(informe, ensure_ascii=False, indent=2)+'\n'
    if args.informe:
        args.informe.parent.mkdir(parents=True, exist_ok=True)
        args.informe.write_text(text, encoding='utf-8')
    print(text)


if __name__ == '__main__':
    main()
