# -*- coding: utf-8 -*-
"""E06 - Estado estacionario."""
import numpy as np
import pandas as pd

from espesadores.config import GLOBALES, CV_ESTADO_ESTACIONARIO
from .comun import log, titulo, guardar


def e06_estado_estacionario(df, cfg, ctx):
    """
    Conserva solo los períodos de operación estable.

    SUSTENTO (Cao & Rhinehart 1995): durante un transitorio, las variables
    no están en equilibrio y la relación causa-efecto que se quiere medir
    queda enmascarada por la dinámica. Para inferir ventanas operativas hay
    que mirar operación estable.

    Criterio: el coeficiente de variación dentro de la ventana móvil debe
    ser menor al umbral para el tonelaje y para el flujo de alimentación a
    la vez.
    """
    titulo("E06 - ESTADO ESTACIONARIO")
    v = ctx["ventanas"]["estado_estacionario"]
    estable = pd.Series(True, index=df.index)

    for col in [GLOBALES["alim_total_molino"], cfg["flujo_alim"]]:
        if col not in df.columns:
            continue
        media = df[col].rolling(v, center=True, min_periods=v).mean()
        desv = df[col].rolling(v, center=True, min_periods=v).std()
        cv = desv / media.abs().replace(0, np.nan)
        col_estable = (cv < CV_ESTADO_ESTACIONARIO).fillna(False)
        log(f"  {col:24s} estable en {int(col_estable.sum()):>9,} filas "
            f"({100*col_estable.mean():5.1f}%)")
        estable &= col_estable

    antes = len(df)
    df = df[estable]
    log(f"  Estable simultaneamente: {antes:,} -> {len(df):,} filas "
        f"({100*len(df)/ctx['n_crudo']:.1f}% del crudo original)")
    ctx["n_limpio"] = len(df)

    retencion = pd.DataFrame([
        {"etapa": "E01 crudo", "filas": ctx["n_crudo"]},
        {"etapa": "E03 planta produciendo", "filas": ctx["n_produciendo"]},
        {"etapa": "E06 estado estacionario", "filas": len(df)},
    ]).set_index("etapa")
    retencion["pct_del_crudo"] = (100 * retencion.filas / ctx["n_crudo"]).round(1)
    guardar(retencion, "E06_retencion.csv", ctx["salidas"])
    return df
