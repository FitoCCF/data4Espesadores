#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Busca tags PI por patrón (interactivo) y exporta sus atributos.
Requiere Windows + AF SDK + pythonnet — no corre en este entorno Linux.

Uso:
    PYTHONPATH=src python scripts/buscar_tags.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from espesadores.extraccion.buscar_tags import buscar_y_exportar_tags

if __name__ == "__main__":
    buscar_y_exportar_tags()
