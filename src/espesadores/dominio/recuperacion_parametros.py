# -*- coding: utf-8 -*-
"""
recuperacion_parametros.py
================================================================================
¿Con qué valores de cada parámetro recupera MÁS agua cada espesador, por
tren? (pedido del usuario 2026-09-17)

La recuperación se mide en el propio espesador con el balance de agua de
E05 (pipeline/e05_balance.py), minuto a minuto, con los tags de tags.yaml:

  particion      = flujo_alim / (suma de los tres flujos de alimentación)
  ton_espesador  = alim_total_molino * particion              [t/h]
  agua_alim      = agua_dilucion * 3.6 + ton * (100/sol_alim - 1)   [m3/h]
  agua_descarga  = ton * (100/wt_activo - 1)                  [m3/h]
  rebose         = agua_alim - agua_descarga                  [m3/h]
  recuperacion   = rebose / agua_alim                         [0-1]

sol_alim = 36 % fijo (PROCESO.sol_alim_default) porque el tag del %sólidos
de alimentación (`globales.sol_overflow`) no existe en PI (H-E): el NIVEL
de recuperación tiene ese sesgo, el RANKING entre minutos no, porque
depende de wt_activo (medido). wt_activo = %sólidos del tren en servicio
(bomba de descarga > umbral_bomba_on), regla E04.

Luego, para cada espesador, se parten los minutos válidos en tercios de
recuperación (BAJA / MEDIA / ALTA) y se describe cada parámetro por tren
en cada tercio: mín · p10 · mediana · p90 · máx. Solo planta produciendo
y exactamente un tren en servicio; celdas fuera de rango físico anuladas
(E03). Igual que E10 pero sin partir por tipo de mineral (más simple de
leer; el tonelaje del espesador se reporta para ver si es comparable).

Salidas (data/06_reporting/recuperacion/):
  parametros_por_tren.csv, parametros_por_tren.md, tags_usados.csv

Uso:
    python -m espesadores.dominio.recuperacion_parametros
"""
import argparse
import os

import numpy as np
import pandas as pd

from espesadores.config import ESPESADORES, GLOBALES, PROCESO, RUTAS, TAGS_EXTRACCION_PI
from espesadores.dominio.atoro_alimentacion import cargar_crudo
from espesadores.dominio.flujo_piscinas_parametros import (PLANTA, ROLES_ESPESADOR, ROLES_TREN,
                                                           estadisticas, preparar, tren_en_servicio)

NIVELES = ["ALTA", "MEDIA", "BAJA"]
COLUMNA_A_TAG = {col: tag for tag, col, _g, _d in TAGS_EXTRACCION_PI}
DESCRIPCION = {col: d for _t, col, _g, d in TAGS_EXTRACCION_PI}
# Variables calculadas del balance (rol -> columna en df)
BALANCE = [("recuperacion", "recuperacion"), ("rebose", "rebose"), ("agua_alim", "agua_alim"),
           ("agua_descarga", "agua_descarga"), ("ton_espesador", "ton_espesador")]


def log(msg=""):
    print(msg, flush=True)


def balance_e05(df, cfg, tren):
    """Columnas ton_espesador, agua_alim, agua_descarga, rebose, recuperacion
    y wt_activo para un espesador, con la fórmula de E05."""
    flujos = [f for f in cfg["flujos_todos"] if f in df.columns]
    total = df[flujos].sum(axis=1, min_count=1)
    particion = df[cfg["flujo_alim"]] / total.replace(0, np.nan)
    ton = df[GLOBALES["alim_total_molino"]] * particion
    wt = pd.Series(np.nan, index=df.index)
    for t in cfg["trenes"]:
        sel = tren == t["nombre"]
        wt[sel] = df.loc[sel, t["wt"]]
    sol_alim = PROCESO["sol_alim_default"]
    agua_alim = df[cfg["agua_dilucion"]] * PROCESO["factor_dilucion"] + (ton / sol_alim * 100 - ton)
    agua_desc = ton / wt * 100 - ton
    rebose = agua_alim - agua_desc
    rec = rebose / agua_alim
    ok = rec.between(0, 1) & rebose.between(0, 5000)
    out = pd.DataFrame({"ton_espesador": ton, "wt_activo": wt, "agua_alim": agua_alim,
                        "agua_descarga": agua_desc, "rebose": rebose, "recuperacion": rec})
    out[~ok] = np.nan
    return out


def tags_usados(esp):
    """[(rol, columna, tag PI, descripción)] de todo lo que entra al cálculo
    y a las tablas de este espesador."""
    cfg = ESPESADORES[esp]
    filas = [("alim_total_molino", GLOBALES["alim_total_molino"])]
    filas += [(f"flujo_alim_{i+1}", f) for i, f in enumerate(cfg["flujos_todos"])]
    filas += [(rol, cfg[rol]) for rol in ROLES_ESPESADOR]
    for t in cfg["trenes"]:
        n = t["nombre"].replace("TREN ", "T")
        filas += [(f"{rol}_{n}", t[campo]) for campo, rol in ROLES_TREN]
    filas += [(rol, col) for col, rol in PLANTA.items()]
    filas += [("molino_1", GLOBALES["molinos"][0]), ("molino_2", GLOBALES["molinos"][1]),
              ("piscina_a", "LIT_106"), ("piscina_b", "LIT_107")]
    return [(rol, col, COLUMNA_A_TAG.get(col, ""), DESCRIPCION.get(col, "")) for rol, col in filas]


def analizar():
    log("Cargando dataset crudo…")
    df = preparar(cargar_crudo())
    filas, resumen = [], []
    for esp, cfg in ESPESADORES.items():
        tren = tren_en_servicio(df, cfg)
        bal = balance_e05(df, cfg, tren)
        base = df["produciendo"] & tren.isin([t["nombre"] for t in cfg["trenes"]]) & bal["recuperacion"].notna()
        rec = bal.loc[base, "recuperacion"]
        q1, q2 = rec.quantile([1 / 3, 2 / 3])
        nivel = pd.Series(np.nan, index=df.index, dtype=object)
        nivel[base & (bal["recuperacion"] <= q1)] = "BAJA"
        nivel[base & (bal["recuperacion"] > q1) & (bal["recuperacion"] <= q2)] = "MEDIA"
        nivel[base & (bal["recuperacion"] > q2)] = "ALTA"
        resumen.append({"espesador": esp, "minutos_validos": int(base.sum()),
                        "corte_baja_media": round(float(q1), 4), "corte_media_alta": round(float(q2), 4),
                        "rec_mediana": round(float(rec.median()), 4)})
        log(f"{esp}: {base.sum():,} min válidos; recuperación mediana {100*rec.median():.1f} %, "
            f"tercios en {100*q1:.1f} % y {100*q2:.1f} %")
        d_all = pd.concat([df, bal], axis=1)
        for nombre_tren in [t["nombre"] for t in cfg["trenes"]]:
            cfg_tren = next(t for t in cfg["trenes"] if t["nombre"] == nombre_tren)
            for niv in NIVELES:
                sel = (tren == nombre_tren) & (nivel == niv)
                d = d_all[sel]
                variables = list(BALANCE)
                variables += [(rol, cfg[rol]) for rol in ROLES_ESPESADOR if cfg[rol] in df.columns]
                variables += [(rol, cfg_tren[campo]) for campo, rol in ROLES_TREN if cfg_tren[campo] in df.columns]
                variables += [(rol, col) for col, rol in PLANTA.items() if col in df.columns]
                variables += [("tanques_prom", "tanques_prom"), ("nivel_piscina", "nivel_piscina"),
                              ("molienda_total", "molienda_total")]
                for rol, col in variables:
                    e = estadisticas(d[col])
                    if e is None:
                        continue
                    filas.append({"espesador": esp, "tren": nombre_tren, "estado": niv,
                                  "variable": rol, "columna": col, "tag_pi": COLUMNA_A_TAG.get(col, ""), **e})
    return pd.DataFrame(filas), pd.DataFrame(resumen)


def _fmt(v, nd=2):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "—"
    return f"{v:,.{nd}f}" if abs(v) < 100 else f"{v:,.0f}"


def escribir_markdown(res, resumen, ruta):
    L = ["# Con qué valores de cada parámetro recupera más agua cada espesador, por tren", "",
         f"Dataset `{os.path.basename(RUTAS['entrada'])}`; planta produciendo (molinos > {PROCESO['tonelaje_min_produccion']:g} t/h), "
         "un tren en servicio, celdas fuera de rango físico anuladas (E03). Recuperación = balance de agua E05 "
         f"(sol. alimentación fija {PROCESO['sol_alim_default']:g} %). Tercios de recuperación por espesador.", ""]
    L += ["| espesador | minutos válidos | recuperación mediana | corte BAJA/MEDIA | corte MEDIA/ALTA |", "|---|---:|---:|---:|---:|"]
    for _, r in resumen.iterrows():
        L.append(f"| {r.espesador} | {r.minutos_validos:,} | {100*r.rec_mediana:.1f} % | {100*r.corte_baja_media:.1f} % | {100*r.corte_media_alta:.1f} % |")
    L.append("")
    for esp in res.espesador.unique():
        L += [f"## {esp}", ""]
        for tren in res[res.espesador == esp].tren.unique():
            sub = res[(res.espesador == esp) & (res.tren == tren)]
            n = {v: int(sub[sub.estado == v].minutos.max()) for v in NIVELES if (sub.estado == v).any()}
            L += [f"### {esp} · {tren}  (minutos: " + ", ".join(f"{k} {v:,}" for k, v in n.items()) + ")", "",
                  "| variable | tag PI | ALTA min · p10 · **p50** · p90 · max | MEDIA p50 | BAJA p50 | Δ ALTA−BAJA |", "|---|---|---|---:|---:|---:|"]
            for var in sub.variable.unique():
                a = sub[(sub.variable == var) & (sub.estado == "ALTA")]
                m = sub[(sub.variable == var) & (sub.estado == "MEDIA")]
                b = sub[(sub.variable == var) & (sub.estado == "BAJA")]
                if a.empty:
                    continue
                a = a.iloc[0]
                pm = m.iloc[0].p50 if not m.empty else np.nan
                pb = b.iloc[0].p50 if not b.empty else np.nan
                L.append(f"| {var} | `{a.tag_pi or a.columna}` | {_fmt(a['min'])} · {_fmt(a.p10)} · **{_fmt(a.p50)}** · {_fmt(a.p90)} · {_fmt(a['max'])} "
                         f"| {_fmt(pm)} | {_fmt(pb)} | {_fmt(a.p50 - pb) if not np.isnan(pb) else '—'} |")
            L.append("")
    with open(ruta, "w", encoding="utf-8") as f:
        f.write("\n".join(L))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--salida", default=os.path.join(RUTAS["salidas"], "recuperacion"))
    args = ap.parse_args()
    res, resumen = analizar()
    os.makedirs(args.salida, exist_ok=True)
    res.to_csv(os.path.join(args.salida, "parametros_por_tren.csv"), index=False)
    resumen.to_csv(os.path.join(args.salida, "tercios.csv"), index=False)
    pd.DataFrame([(esp, *fila) for esp in ESPESADORES for fila in tags_usados(esp)],
                 columns=["espesador", "rol", "columna", "tag_pi", "descripcion"]
                 ).to_csv(os.path.join(args.salida, "tags_usados.csv"), index=False)
    escribir_markdown(res, resumen, os.path.join(args.salida, "parametros_por_tren.md"))
    log(f"\nEscrito en {args.salida}/  ({len(res)} filas)")


if __name__ == "__main__":
    main()
