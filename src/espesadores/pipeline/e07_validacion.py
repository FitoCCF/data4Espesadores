# -*- coding: utf-8 -*-
"""E07 - Validación de la palanca principal (control de calidad)."""
import numpy as np
import pandas as pd

from .comun import log, titulo, guardar, corr_parcial


def e07_validar_palanca(df, cfg, ctx):
    """
    CONTROL DE CALIDAD DEL ANALISIS. Si esta etapa falla, no hay que seguir.

    La física del balance de agua predice exactamente cuánto rebose gana el
    espesador por cada punto de %sólidos de descarga:

        d(rebose)/d(wt) = 100 * ton / wt^2

    Esta etapa compara esa pendiente TEÓRICA con la pendiente EMPÍRICA
    medida en los datos limpios, banda de tonelaje por banda de tonelaje. Si
    coinciden, la limpieza y el balance están bien hechos. Si no coinciden,
    hay un problema aguas arriba y las ventanas que se calculen después no
    serán confiables.
    """
    titulo("E07 - VALIDACION DE LA PALANCA PRINCIPAL (control de calidad)")

    cp = corr_parcial(df, "wt_activo", "rebose", ["ton_espesador"])
    cb = df["wt_activo"].corr(df["rebose"])
    log(f"  Correlacion bruta   (wt_activo vs rebose)              = {cb:+.3f}")
    log(f"  Correlacion parcial (wt_activo vs rebose | tonelaje)   = {cp:+.3f}")
    log("  La parcial debe ser claramente mayor: el tonelaje enmascara la palanca.")

    d = df.dropna(subset=["wt_activo", "rebose", "ton_espesador"]).copy()
    d["banda"] = pd.qcut(d["ton_espesador"], 5,
                         labels=["muy bajo", "bajo", "medio", "alto", "muy alto"])
    filas = []
    log("")
    log(f"  {'banda':11s} {'ton':>7s} {'n':>8s} {'pend.empirica':>14s} "
        f"{'pend.teorica':>13s} {'desvio':>8s}")
    for banda, g in d.groupby("banda", observed=True):
        if len(g) < 200:
            continue
        A = np.c_[np.ones(len(g)), g["wt_activo"].values]
        pend_emp = np.linalg.lstsq(A, g["rebose"].values, rcond=None)[0][1]
        ton_m, wt_m = g["ton_espesador"].mean(), g["wt_activo"].mean()
        pend_teo = 100 * ton_m / wt_m ** 2
        desvio = 100 * (pend_emp - pend_teo) / pend_teo
        filas.append({"banda": str(banda), "ton_medio": round(ton_m, 0), "n": len(g),
                      "pendiente_empirica": round(pend_emp, 2),
                      "pendiente_teorica": round(pend_teo, 2),
                      "desvio_pct": round(desvio, 1)})
        log(f"  {str(banda):11s} {ton_m:7.0f} {len(g):8,} {pend_emp:14.2f} "
            f"{pend_teo:13.2f} {desvio:+7.1f}%")

    R = pd.DataFrame(filas)
    guardar(R.set_index("banda"), "E07_validacion_palanca.csv", ctx["salidas"])

    if len(R):
        ok = (R["desvio_pct"].abs() < 30).sum()
        log("")
        log(f"  VEREDICTO: {ok} de {len(R)} bandas con desvio menor a 30%.")
        if ok >= max(1, len(R) - 2):
            log("  -> VALIDACION SUPERADA: el balance y la limpieza son consistentes.")
            ctx["validacion_ok"] = True
        else:
            log("  -> ATENCION: la pendiente medida no reproduce la fisica.")
            log("     Revisar E02-E05 antes de usar las ventanas de E10.")
            ctx["validacion_ok"] = False

    ton_op = df["ton_espesador"].mean()
    wt_op = df["wt_activo"].mean()
    ctx["sensibilidad"] = 100 * ton_op / wt_op ** 2
    ctx["ton_operacion"] = ton_op
    ctx["wt_operacion"] = wt_op
    log(f"  Sensibilidad en el punto de operacion (ton={ton_op:.0f}, wt={wt_op:.1f}%): "
        f"{ctx['sensibilidad']:.1f} m3/h por punto de %solidos")
    return df
