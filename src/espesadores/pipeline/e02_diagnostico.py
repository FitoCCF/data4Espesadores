# -*- coding: utf-8 -*-
"""E02 - Diagnóstico de variables inservibles."""
import numpy as np
import pandas as pd

from espesadores.config import GLOBALES, PROCESO, DIAGNOSTICO
from .comun import log, titulo, guardar


def e02_diagnostico(df, cfg, ctx):
    """
    Detecta variables que NO sirven, antes de que contaminen el análisis.

    SUSTENTO EMPÍRICO (hallazgos reales en TH-001):
      (a) Ratio_concentracion_Output tenía 94 valores distintos en 1 064 161
          filas y el 86% era un solo número (hold del reporte de
          Metalurgia). Al usarla en clustering, el algoritmo "descubría" ese
          escalón y entregaba una partición degenerada con silhouette falso
          de 0.92.
      (b) La gravedad específica de sólidos implícita salió constante
          (2.7700, CV 0.67%): el DCS calcula el %sólidos DESDE la densidad
          con SG fijo. No son dos mediciones independientes, por lo que
          ninguna combinación de ambas aporta información mineralógica.

    Esta etapa vuelve a correr esos dos diagnósticos para CUALQUIER
    espesador y descarta automáticamente lo que falle.
    """
    titulo("E02 - DIAGNOSTICO DE VARIABLES INSERVIBLES")
    descartadas = []
    filas = []

    log("  (a) Deteccion de holds (un valor domina la serie)")
    candidatas = [GLOBALES["ratio_conc_reporte"], GLOBALES["ley_rougher"],
                  GLOBALES["ratio_cu"]]
    for col in candidatas:
        if col not in df.columns:
            continue
        s = df[col].dropna()
        if len(s) == 0:
            descartadas.append(col)
            continue
        share = s.value_counts(normalize=True).iloc[0]
        n_unicos = s.nunique()
        sirve = (share <= DIAGNOSTICO["max_share_valor_unico"] and
                 n_unicos >= DIAGNOSTICO["min_valores_unicos"])
        filas.append({"variable": col, "valores_unicos": n_unicos,
                      "share_valor_top": round(share, 4),
                      "veredicto": "SIRVE" if sirve else "DESCARTADA"})
        log(f"      {col:30s} unicos={n_unicos:>7,}  top1={100*share:5.1f}%  "
            f"-> {'SIRVE' if sirve else 'DESCARTADA'}")
        if not sirve:
            descartadas.append(col)

    log("  (b) Columnas 100% nulas")
    for col in df.columns:
        if df[col].isna().all():
            log(f"      {col:30s} 100% nula -> DESCARTADA")
            descartadas.append(col)
            filas.append({"variable": col, "valores_unicos": 0,
                          "share_valor_top": np.nan, "veredicto": "DESCARTADA"})

    log("  (c) ¿Son independientes %solidos y densidad de descarga?")
    sg_independiente = {}
    for tren in cfg["trenes"]:
        wt, dit, vel = tren["wt"], tren["dit"], tren["descarga"]
        if not all(c in df.columns for c in (wt, dit, vel)):
            continue
        activa = df[vel] > PROCESO["umbral_bomba_on"]
        w = df.loc[activa, wt] / 100.0
        rho = df.loc[activa, dit]
        denominador = (1.0 / rho) - (1.0 - w)
        sg = (w / denominador).replace([np.inf, -np.inf], np.nan)
        sg = sg[(sg > 2.0) & (sg < 5.5)].dropna()
        if len(sg) < 100:
            continue
        cv = sg.std() / sg.mean()
        indep = cv > DIAGNOSTICO["cv_max_sg_independiente"]
        sg_independiente[tren["nombre"]] = indep
        log(f"      {tren['nombre']}: SG implicita mediana={sg.median():.4f} "
            f"CV={100*cv:.2f}%  -> {'independientes' if indep else 'LIGADAS (SG fijo)'}")
        filas.append({"variable": f"SG_{tren['nombre']}", "valores_unicos": sg.nunique(),
                      "share_valor_top": np.nan,
                      "veredicto": "INDEPENDIENTES" if indep else "LIGADAS"})

    ctx["descartadas"] = list(set(descartadas))
    ctx["sg_independiente"] = sg_independiente
    log(f"  RESUMEN: {len(ctx['descartadas'])} variables descartadas: {ctx['descartadas']}")
    guardar(pd.DataFrame(filas).set_index("variable"),
            "E02_diagnostico_variables.csv", ctx["salidas"])
    return df
