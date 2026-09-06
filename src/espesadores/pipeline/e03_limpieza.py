# -*- coding: utf-8 -*-
"""E03 - Limpieza (rango físico, planta produciendo, atípicos)."""
import numpy as np
import pandas as pd

from espesadores.config import GLOBALES, PROCESO, RANGOS_POR_TIPO
from .comun import log, titulo, guardar, filtro_hampel


def e03_limpiar(df, cfg, ctx):
    """
    Limpieza en tres pasos, del error más grosero al más sutil.

    SUSTENTO:
      1. RANGO FÍSICO (Narasimhan & Jordache 2000): un valor imposible es un
         error grueso. Se anula la CELDA y no la fila, porque un instrumento
         fallado no invalida el resto de las mediciones de ese instante.
      2. PLANTA PRODUCIENDO: con el molino detenido el espesador no procesa
         nada; esas filas no informan sobre cómo operarlo.
      3. HAMPEL (1974): atípicos puntuales que sobrevivieron al rango
         físico.
    """
    titulo("E03 - LIMPIEZA")
    n0 = len(df)

    log("  Paso 1 - Validacion de rango fisico (anula celdas fuera de rango)")
    mapa_rangos = {}
    for clave, rango in RANGOS_POR_TIPO.items():
        if clave in cfg:
            mapa_rangos[cfg[clave]] = rango
        if clave in GLOBALES:
            mapa_rangos[GLOBALES[clave]] = rango
    for tren in cfg["trenes"]:
        for clave in ("descarga", "cizalle", "wt", "dit"):
            mapa_rangos[tren[clave]] = RANGOS_POR_TIPO[clave]
    for f in cfg["flujos_todos"]:
        mapa_rangos[f] = RANGOS_POR_TIPO["flujo_alim"]

    detalle = []
    total_anuladas = 0
    for col, (lo, hi) in mapa_rangos.items():
        if col not in df.columns:
            continue
        fuera = (df[col] < lo) | (df[col] > hi)
        n = int(fuera.sum())
        if n:
            df.loc[fuera, col] = np.nan
            total_anuladas += n
            detalle.append({"variable": col, "rango": f"[{lo}, {hi}]", "celdas_anuladas": n})
    log(f"      celdas anuladas por rango fisico: {total_anuladas:,}")
    if detalle:
        guardar(pd.DataFrame(detalle).set_index("variable"),
                "E03a_rango_fisico.csv", ctx["salidas"])

    log("  Paso 2 - Filtro de planta produciendo")
    col_ton = GLOBALES["alim_total_molino"]
    df = df[df[col_ton] > PROCESO["tonelaje_min_produccion"]]
    log(f"      {n0:,} -> {len(df):,} filas  (elimina {n0-len(df):,} de molino detenido)")

    log("  Paso 3 - Atipicos robustos (mediana movil + MAD)")
    v = ctx["ventanas"]["hampel"]
    columnas_hampel = [cfg["presion_cama"], cfg["torque"], cfg["nivel_interfaz"],
                       cfg["floculante"], cfg["agua_dilucion"]] + cfg["flujos_todos"]
    for tren in cfg["trenes"]:
        columnas_hampel += [tren["wt"], tren["dit"]]
    det_h = []
    for col in dict.fromkeys(columnas_hampel):
        if col not in df.columns:
            continue
        df[col], n = filtro_hampel(df[col], v)
        if n:
            det_h.append({"variable": col, "atipicos_anulados": n})
    log(f"      atipicos anulados: {sum(d['atipicos_anulados'] for d in det_h):,}")
    if det_h:
        guardar(pd.DataFrame(det_h).set_index("variable"),
                "E03b_hampel.csv", ctx["salidas"])

    ctx["n_produciendo"] = len(df)
    return df
