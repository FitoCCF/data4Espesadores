#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Descarga los 52 atributos PI de los tags declarados en conf/base/tags.yaml.
Requiere Windows + AF SDK + pythonnet — no corre en este entorno Linux.

Uso:
    PYTHONPATH=src python scripts/descubrir_atributos.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from espesadores.extraccion.descubrir_atributos import extraer_atributos_afsdk

if __name__ == "__main__":
    extraer_atributos_afsdk()
