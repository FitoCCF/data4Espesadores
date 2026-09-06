#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Extracción PI completa. Requiere Windows + AF SDK + pythonnet — no corre en
este entorno Linux (ver docs/inventario_proyecto.md §10).

Uso:
    PYTHONPATH=src python scripts/extraer.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from espesadores.extraccion.extraer_pi import main

if __name__ == "__main__":
    main()
