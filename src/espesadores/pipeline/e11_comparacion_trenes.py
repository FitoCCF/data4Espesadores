# -*- coding: utf-8 -*-
"""E11 - Comparación de trenes de bombeo."""
import pandas as pd

from .comun import log, titulo, guardar


def e11_comparar_trenes(df, cfg, ctx):
    """
    Compara el desempeño de los trenes de bombeo a igualdad de condiciones.

    SUSTENTO: en TH-001 un tren rendía 1.25 puntos de %sólidos más que el
    otro. Para descartar que fuera un artefacto (por ejemplo, que el tren
    peor se usara solo en condiciones difíciles) se hizo un EMPAREJAMIENTO:
    se comparan los trenes solo dentro de celdas con la misma presión de
    cama, el mismo nivel y el mismo tonelaje. La ventaja se mantuvo en 14 de
    14 celdas.
    """
    titulo("E11 - COMPARACION DE TRENES DE BOMBEO")
    trenes = [t for t in df["tren"].unique() if t != "NINGUNO"]
    if len(trenes) < 2:
        log("  Solo un tren en servicio en el periodo: no hay comparacion posible.")
        ctx["trenes_ok"] = False
        return df

    log(f"  {'tren':12s} {'n':>9s} {'%tiempo':>8s} {'%solidos':>9s} "
        f"{'recuperacion':>13s} {'rebose':>8s} {'tonelaje':>9s}")
    filas = []
    for t in trenes:
        g = df[df["tren"] == t]
        filas.append({"tren": t, "n": len(g), "pct_tiempo": round(100*len(g)/len(df), 1),
                      "wt_activo": round(g.wt_activo.mean(), 2),
                      "recuperacion": round(100*g.recuperacion.mean(), 1),
                      "rebose": round(g.rebose.mean(), 0),
                      "tonelaje": round(g.ton_espesador.mean(), 0)})
        log(f"  {t:12s} {len(g):9,} {100*len(g)/len(df):7.1f}% {g.wt_activo.mean():9.2f} "
            f"{100*g.recuperacion.mean():12.1f}% {g.rebose.mean():8.0f} "
            f"{g.ton_espesador.mean():9.0f}")
    T = pd.DataFrame(filas).set_index("tren")
    guardar(T, "E11a_trenes_crudo.csv", ctx["salidas"])

    log("")
    log("  Emparejado por presion de cama, nivel de interfaz y tonelaje:")
    d = df.dropna(subset=["wt_activo", cfg["presion_cama"], cfg["nivel_interfaz"],
                          "ton_espesador"]).copy()
    d["c_cama"] = pd.qcut(d[cfg["presion_cama"]], 4, duplicates="drop")
    d["c_nivel"] = pd.qcut(d[cfg["nivel_interfaz"]], 3, duplicates="drop")
    d["c_ton"] = pd.qcut(d["ton_espesador"], 3, duplicates="drop")
    ref = trenes[0]
    celdas = []
    for llave, g in d.groupby(["c_cama", "c_nivel", "c_ton"], observed=True):
        sub = {t: g[g["tren"] == t] for t in trenes}
        if any(len(s) < 100 for s in sub.values()):
            continue
        fila = {"celda": str(llave)}
        for t in trenes:
            fila[f"wt_{t}"] = round(sub[t].wt_activo.mean(), 2)
        fila["diferencia"] = round(max(fila[f"wt_{t}"] for t in trenes) -
                                   min(fila[f"wt_{t}"] for t in trenes), 2)
        fila["gana"] = max(trenes, key=lambda t: fila[f"wt_{t}"])
        celdas.append(fila)
    if celdas:
        C = pd.DataFrame(celdas)
        ganador = C["gana"].value_counts()
        log(f"      celdas comparables: {len(C)}")
        for t, n in ganador.items():
            log(f"      gana {t}: {n} de {len(C)} celdas")
        log(f"      diferencia media emparejada: {C.diferencia.mean():.2f} puntos de %solidos "
            f"({ctx['sensibilidad']*C.diferencia.mean():.0f} m3/h)")
        guardar(C.set_index("celda"), "E11b_trenes_emparejado.csv", ctx["salidas"])
        ctx["tren_mejor"] = str(ganador.index[0])
        ctx["ventaja_tren"] = float(C.diferencia.mean())
        ctx["celdas_favorables"] = f"{int(ganador.iloc[0])} de {len(C)}"
    else:
        ctx["tren_mejor"] = None

    log("")
    log("  Consistencia de la bomba de cizallamiento por tren:")
    ciz = []
    for t in trenes:
        s = df.loc[df["tren"] == t, "vel_cizalle"].dropna()
        if len(s) < 100:
            continue
        objetivo = float(s.median())
        fuera = float((s < objetivo - 5).mean())
        ciz.append({"tren": t, "mediana": round(objetivo, 1),
                    "p10": round(float(s.quantile(.1)), 1),
                    "pct_fuera_abajo": round(100*fuera, 1)})
        log(f"      {t}: mediana={objetivo:.1f}  p10={s.quantile(.1):.1f}  "
            f"por debajo del objetivo el {100*fuera:.0f}% del tiempo")
    if ciz:
        guardar(pd.DataFrame(ciz).set_index("tren"), "E11c_cizalle.csv", ctx["salidas"])
        ctx["cizalle"] = ciz
    ctx["trenes_ok"] = True
    ctx["tabla_trenes"] = T
    return df
