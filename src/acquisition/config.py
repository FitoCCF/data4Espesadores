# ============================================================
# src/acquisition/config.py — rutas del paquete de adquisición
# ============================================================
# Este paquete se copió desde data2TesisV2, donde las rutas venían de
# `src.pipeline.config`. Aquí no existe ese módulo (el paquete de análisis es
# `espesadores`), así que las rutas se definen localmente para que
# `acquisition` sea autocontenido: no importa nada de otro proyecto ni de
# `espesadores`, y se puede ejecutar con `PYTHONPATH=src python -m
# acquisition.<modulo>` desde la raíz del repo.
# ============================================================

from pathlib import Path

# src/acquisition/config.py -> src/acquisition -> src -> raíz del repo.
RAIZ = Path(__file__).resolve().parents[2]

# Carpeta de datos crudos de este repo (en data2TesisV2 era data/raw).
DATA_RAW = RAIZ / "data" / "00_raw"
