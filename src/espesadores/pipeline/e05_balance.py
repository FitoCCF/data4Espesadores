# -*- coding: utf-8 -*-
"""E05 - Balance de agua y métrica de recuperación."""
import pandas as pd

from espesadores.config import GLOBALES, PROCESO
from .comun import log, titulo, guardar


def e05_balance(df, cfg, ctx):
    """
    Recalcula el rebose desde el balance de agua, en vez de confiar en el
    estimador del DCS.

    SUSTENTO (hallazgo en TH-001): el tag del estimador de rebose quedaba
    congelado (last-value-hold) en el 70.5% de las filas, pero sus ENTRADAS
    seguían vivas en el 68.3%. Filtrar por el estimador borraba el 99% del
    dataset; recalcular desde las entradas conserva el 17%.

    Esta etapa NO usa el tag crudo `FLUJO_REBOSE_AGUA_*` en ningún momento
    (confirmado en la auditoría de 2026-09-06, hallazgo N-6 del inventario):
    usa `wt_activo` (%sólidos de descarga), que tiene cobertura casi
    completa desde 2024-07, exactamente la "ruta alternativa" que H-C
    recomienda como ancla.

    Fórmula (equivalente a la del DCS, simplificada al cancelar el término
    de sólidos que aparece en alimentación y descarga):
        agua_alimentacion = dilucion*3.6 + (ton/sol_alim*100 - ton)
        agua_descarga     = ton/wt_activo*100 - ton
        rebose            = agua_alimentacion - agua_descarga
        recuperacion      = rebose / agua_alimentacion
    """
    titulo("E05 - BALANCE DE AGUA Y RECUPERACION")

    flujos = [f for f in cfg["flujos_todos"] if f in df.columns]
    total_flujo = df[flujos].sum(axis=1)
    df["particion"] = df[cfg["flujo_alim"]] / total_flujo.replace(0, float("nan"))

    df["ton_espesador"] = df[GLOBALES["alim_total_molino"]] * df["particion"]

    col_sol = GLOBALES["sol_overflow"]
    if col_sol in df.columns and col_sol not in ctx["descartadas"]:
        sol_alim = df[col_sol].fillna(PROCESO["sol_alim_default"])
        log(f"  %solidos alimentacion: desde {col_sol}")
    else:
        sol_alim = pd.Series(PROCESO["sol_alim_default"], index=df.index)
        log(f"  %solidos alimentacion: valor por defecto {PROCESO['sol_alim_default']}% "
            f"(tag no disponible, igual que en la logica del DCS)")

    ton = df["ton_espesador"]
    dilucion = df[cfg["agua_dilucion"]] * PROCESO["factor_dilucion"]
    df["agua_alim"] = dilucion + (ton / sol_alim * 100 - ton)
    df["agua_descarga"] = ton / df["wt_activo"] * 100 - ton
    df["rebose"] = df["agua_alim"] - df["agua_descarga"]
    df["recuperacion"] = df["rebose"] / df["agua_alim"]

    antes = len(df)
    df = df[df["recuperacion"].between(0, 1) & df["rebose"].between(0, 5000)]
    log(f"  Balance coherente: {antes:,} -> {len(df):,} filas")
    log(f"  Rebose      : mediana={df.rebose.median():.0f} m3/h  "
        f"p10={df.rebose.quantile(.1):.0f}  p90={df.rebose.quantile(.9):.0f}")
    log(f"  Recuperacion: mediana={100*df.recuperacion.median():.1f}%  "
        f"p10={100*df.recuperacion.quantile(.1):.1f}%  p90={100*df.recuperacion.quantile(.9):.1f}%")

    c_reb = df["rebose"].corr(df["ton_espesador"])
    c_rec = df["recuperacion"].corr(df["ton_espesador"])
    log(f"  Control de normalizacion:")
    log(f"      corr(rebose, tonelaje)       = {c_reb:+.3f}   (alto: arrastra la produccion)")
    log(f"      corr(recuperacion, tonelaje) = {c_rec:+.3f}   (bajo: sirve para comparar)")

    ctx["agua_alim_ref"] = float(df["agua_alim"].median())
    log(f"  Agua de alimentacion de referencia: {ctx['agua_alim_ref']:.0f} m3/h")

    guardar(df[["ton_espesador", "agua_alim", "agua_descarga", "rebose",
                "recuperacion", "wt_activo"]].describe(),
            "E05_balance_agua.csv", ctx["salidas"])
    return df
