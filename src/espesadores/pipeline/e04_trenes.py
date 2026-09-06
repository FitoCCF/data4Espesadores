# -*- coding: utf-8 -*-
"""E04 - Trenes de bombeo (duty/standby)."""
import numpy as np
import pandas as pd

from espesadores.config import PROCESO
from .comun import log, titulo, guardar


def e04_trenes(df, cfg, ctx):
    """
    Reconstruye la señal física única de descarga a partir de las
    mediciones parciales de cada tren, y verifica si los trenes están
    acoplados.

    SUSTENTO (hallazgo en TH-001): el %sólidos de cada bomba solo tiene
    sentido cuando ESA bomba corre. Usar WT_146 cruda daba correlación
    falsa de +0.065 con el rebose porque estaba muerta el 68% del tiempo.
    Al construir la señal activa, la correlación parcial subió a +0.85 y
    apareció la palanca real.

    Además se comprobó que descarga y cizalle arrancan siempre juntos: los
    trenes son bloques acoplados, no bombas independientes.
    """
    titulo("E04 - TRENES DE BOMBEO (DUTY / STANDBY)")
    umbral = PROCESO["umbral_bomba_on"]

    df["tren"] = "NINGUNO"
    df["wt_activo"] = np.nan
    df["dit_activo"] = np.nan
    df["vel_descarga"] = np.nan
    df["vel_cizalle"] = np.nan

    for tren in cfg["trenes"]:
        if tren["descarga"] not in df.columns:
            continue
        activo = (df[tren["descarga"]] > umbral) & (df["tren"] == "NINGUNO")
        df.loc[activo, "tren"] = tren["nombre"]
        df.loc[activo, "wt_activo"] = df.loc[activo, tren["wt"]]
        df.loc[activo, "dit_activo"] = df.loc[activo, tren["dit"]]
        df.loc[activo, "vel_descarga"] = df.loc[activo, tren["descarga"]]
        if tren["cizalle"] in df.columns:
            df.loc[activo, "vel_cizalle"] = df.loc[activo, tren["cizalle"]]

    uso = df["tren"].value_counts()
    resumen = []
    for nombre, n in uso.items():
        log(f"  {nombre:10s}: {n:>9,} filas ({100*n/len(df):5.1f}% del tiempo)")
        resumen.append({"tren": nombre, "filas": n, "pct_tiempo": round(100*n/len(df), 2)})

    log("  Verificacion de acoplamiento descarga/cizalle:")
    for tren in cfg["trenes"]:
        if tren["cizalle"] not in df.columns:
            continue
        en_tren = df["tren"] == tren["nombre"]
        if en_tren.sum() < 100:
            continue
        junto = (df.loc[en_tren, tren["cizalle"]] > umbral).mean()
        log(f"      {tren['nombre']}: cizalle {tren['cizalle']} activo el {100*junto:.1f}% "
            f"-> {'ACOPLADO' if junto > 0.9 else 'independiente'}")

    guardar(pd.DataFrame(resumen).set_index("tren"), "E04_trenes.csv", ctx["salidas"])
    df = df[df["tren"] != "NINGUNO"]
    log(f"  Filas con descarga en servicio: {len(df):,}")
    return df
