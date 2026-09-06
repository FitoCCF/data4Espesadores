# -*- coding: utf-8 -*-
"""E01 - Carga y perfilado estructural."""
import pandas as pd

from espesadores.config import GLOBALES, VENTANAS_MIN, RUTAS
from .comun import log, titulo, guardar


def e01_cargar(cfg, ctx):
    """
    Carga el dataset, ordena por tiempo y detecta el período de muestreo.

    SUSTENTO: CRISP-DM fase "Data Understanding". Antes de limpiar hay que
    saber qué hay: cuántas filas, qué rango temporal, cada cuánto se
    muestrea. El período de muestreo define el tamaño de TODAS las ventanas
    móviles del pipeline; si se asume mal, los filtros quedan mal
    dimensionados.
    """
    titulo("E01 - CARGA Y PERFILADO ESTRUCTURAL")
    ruta = RUTAS["entrada"]

    if ruta.endswith(".parquet"):
        df = pd.read_parquet(ruta)
    elif ruta.endswith(".pkl"):
        df = pd.read_pickle(ruta)
    else:
        df = pd.read_csv(ruta, low_memory=False)
    log(f"  Archivo: {ruta}")
    log(f"  Dimensiones crudas: {df.shape[0]:,} filas x {df.shape[1]} columnas")

    tcol = GLOBALES["timestamp"]
    if tcol in df.columns:
        df[tcol] = pd.to_datetime(df[tcol], errors="coerce")
        df = df.sort_values(tcol).set_index(tcol)
    else:
        # El dataset canónico se guardó con el índice de tiempo ya nombrado
        # 'timestamp': pandas lo restaura como índice al leer el parquet (no
        # queda como columna). Se normaliza igual que en el caso anterior.
        df.index = pd.to_datetime(df.index, errors="coerce")
        df = df.sort_index()
        df.index.name = tcol
    log(f"  Rango temporal: {df.index.min()}  ->  {df.index.max()}")

    dt = df.index.to_series().diff().dt.total_seconds()
    dt_seg = float(dt.mode().iloc[0]) if len(dt.mode()) else 60.0
    dt_min = dt_seg / 60.0
    log(f"  Periodo de muestreo detectado: {dt_seg:.0f} s ({dt_min:.1f} min)")

    ctx["ventanas"] = {k: max(3, int(round(v / dt_min))) for k, v in VENTANAS_MIN.items()}
    log(f"  Ventanas en muestras: {ctx['ventanas']}")

    perfil = pd.DataFrame({
        "tipo": df.dtypes.astype(str),
        "nulos": df.isna().sum(),
        "pct_nulos": (100 * df.isna().mean()).round(2),
        "ceros": (df == 0).sum(numeric_only=True),
        "unicos": df.nunique(),
    })
    guardar(perfil, "E01_perfil_estructural.csv", ctx["salidas"])

    ctx["dt_min"] = dt_min
    ctx["n_crudo"] = len(df)
    return df
