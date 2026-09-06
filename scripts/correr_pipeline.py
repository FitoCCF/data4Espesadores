#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Punto de entrada único de punta a punta (criterio de aceptación 3 de la
migración): corre las 11 etapas del pipeline para un espesador y genera el
one-pager.

Uso:
    pixi run pipeline TH-001            # vía el task de pixi.toml
    PYTHONPATH=src python scripts/correr_pipeline.py TH-001
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from espesadores.pipeline.orquestador import ejecutar
from espesadores.reportes.onepager import generar_onepager


def main():
    espesador = sys.argv[1] if len(sys.argv) > 1 else "TH-001"
    ctx = ejecutar(espesador)
    generar_onepager(ctx)


if __name__ == "__main__":
    main()
