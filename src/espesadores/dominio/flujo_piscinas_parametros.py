# -*- coding: utf-8 -*-
"""
flujo_piscinas_parametros.py
================================================================================
¿Cómo están TODOS los parámetros de cada espesador, por tren, cuando una
señal de planta está SUBIENDO? (pedido del usuario 2026-09-17). Señales
(`--senal`):
  fit114  : flujo hacia las piscinas FIT_114 (por defecto)
  tanques : nivel de los tanques temporales, promedio de LIT_108 y LIT_109
            (corr. 0.85 entre ambos; el promedio reduce el ruido de un sensor)

Para cada espesador x tren en servicio x estado de la señal:
  subiendo : cambio en 60 min >= +umbral
  bajando  : cambio en 60 min <= -umbral
  estable  : |cambio| < umbral
(señal suavizada con mediana móvil de 30 min; umbral FIT_114 = 2 % de su
mediana por hora, el de piscina_episodios.tendencia; umbral tanques = 1 pp
por hora, el cambio típico — los tanques viven en ~35 % y suben a 70-100 %
por episodios, por eso un umbral relativo a la mediana sería ruido). Solo minutos con la
planta produciendo (suma de molinos > tonelaje_min_produccion) y con
exactamente UN tren de descarga en servicio — así cada fila es atribuible
a un tren. Los minutos con ambos trenes se reportan aparte como "AMBOS".

Por parámetro: mínimo, p10, mediana, p90, máximo y minutos. Antes se
anulan las celdas fuera del rango físico de calidad.yaml (misma regla que
E03: los centinelas 99 999 / 88 431 del DCS no son un máximo real) y, para
las señales de planta sin rango declarado, un rango amplio de sentido
común (niveles 0-105 %, FIT_114 0-10 000). El mínimo y el máximo absolutos
siguen siendo sensibles a un dato suelto; p10/p90 son la "ventana
operativa" robusta. Se reportan los dos.

Salidas (data/06_reporting/flujo_piscinas/ o tanques/):
  parametros_por_tren.csv   formato largo, todo
  parametros_por_tren.md    tablas por espesador y tren + extremos entre
                            espesadores/trenes con la señal subiendo

Uso:
    python -m espesadores.dominio.flujo_piscinas_parametros [--senal fit114|tanques] [--umbral X]
"""
import argparse
import os

import numpy as np
import pandas as pd

from espesadores.config import ESPESADORES, GLOBALES, PROCESO, RANGOS_POR_TIPO, RUTAS
from espesadores.dominio.atoro_alimentacion import cargar_crudo
from espesadores.dominio.piscinas import derivar_nivel

ROLES_ESPESADOR = ["flujo_alim", "valvula_alim", "presion_cama", "torque", "nivel_interfaz",
                   "nivel_cajon", "floculante", "agua_dilucion"]
ROLES_TREN = [("descarga", "vel_descarga"), ("cizalle", "vel_cizalle"), ("wt", "wt_solidos"), ("dit", "densidad")]
PLANTA = {"FIT_114": "flujo_piscinas", "LIT_108": "tk001", "LIT_109": "tk002"}
ESTADOS = ["subiendo", "estable", "bajando"]

# Señal que define sube/baja: columna (o derivada), nombre corto, umbral por
# defecto y si el umbral es relativo (% de la mediana) o absoluto (unidades).
SENALES = {
    "fit114": {"columna": "FIT_114", "nombre": "FIT_114", "umbral": 2.0, "relativo": True,
               "carpeta": "flujo_piscinas", "unidad": "m3/h"},
    "tanques": {"columna": "tanques_prom", "nombre": "tanques TK001/TK002 (prom. LIT_108/LIT_109)",
                "umbral": 1.0, "relativo": False, "carpeta": "tanques", "unidad": "pp"},
}


def log(msg=""):
    print(msg, flush=True)


def estado_senal(df, senal, umbral=None):
    cfg = SENALES[senal]
    col = cfg["columna"]
    s = df[col].rolling(30, min_periods=10, center=True).median()
    u = cfg["umbral"] if umbral is None else umbral
    umbral_abs = u / 100.0 * float(s.median()) if cfg["relativo"] else u
    cambio = s.diff(60)
    estado = pd.Series("estable", index=df.index)
    estado[cambio >= umbral_abs] = "subiendo"
    estado[cambio <= -umbral_abs] = "bajando"
    estado[cambio.isna() | df[col].isna()] = np.nan
    return estado, umbral_abs, cambio


RANGOS_PLANTA = {"FIT_114": (0, 10000), "LIT_108": (0, 105), "LIT_109": (0, 105)}


def anular_fuera_de_rango(df):
    """Celda -> NaN si sale del rango físico (E03), sin tocar la fila."""
    mapa = {}
    for cfg in ESPESADORES.values():
        for rol in ROLES_ESPESADOR:
            mapa[cfg[rol]] = RANGOS_POR_TIPO[rol]
        for t in cfg["trenes"]:
            for campo, _rol in ROLES_TREN:
                mapa[t[campo]] = RANGOS_POR_TIPO[campo]
    for m in GLOBALES["molinos"]:
        mapa[m] = RANGOS_POR_TIPO["alim_total_molino"]
    mapa.update(RANGOS_PLANTA)
    anuladas = {}
    for col, (lo, hi) in mapa.items():
        if col not in df.columns:
            continue
        fuera = df[col].notna() & ((df[col] < lo) | (df[col] > hi))
        if fuera.any():
            anuladas[col] = int(fuera.sum())
            df.loc[fuera, col] = np.nan
    if anuladas:
        log("Celdas fuera de rango anuladas: " + ", ".join(f"{c} {n}" for c, n in sorted(anuladas.items(), key=lambda x: -x[1])))
    return df


def preparar(df):
    df = anular_fuera_de_rango(df)
    molinos = [m for m in GLOBALES["molinos"] if m in df.columns]
    df["molienda_total"] = df[molinos].sum(axis=1, min_count=1)
    df["produciendo"] = df["molienda_total"] > PROCESO["tonelaje_min_produccion"]
    df["nivel_piscina"] = derivar_nivel(df)["nivel_piscina"]
    df["tanques_prom"] = df[["LIT_108", "LIT_109"]].mean(axis=1)
    return df


def tren_en_servicio(df, cfg):
    """'TREN 1' | 'TREN 2' | 'AMBOS' | NaN según las bombas de descarga."""
    umbral = PROCESO["umbral_bomba_on"]
    on = [(df[t["descarga"]] > umbral) if t["descarga"] in df.columns else pd.Series(False, index=df.index)
          for t in cfg["trenes"]]
    tren = pd.Series(np.nan, index=df.index, dtype=object)
    tren[on[0] & ~on[1]] = cfg["trenes"][0]["nombre"]
    tren[on[1] & ~on[0]] = cfg["trenes"][1]["nombre"]
    tren[on[0] & on[1]] = "AMBOS"
    return tren


def estadisticas(s):
    s = s.dropna()
    if len(s) < 30:
        return None
    return {"min": s.min(), "p10": s.quantile(0.10), "p50": s.median(),
            "p90": s.quantile(0.90), "max": s.max(), "minutos": int(len(s))}


def analizar(senal="fit114", umbral=None):
    log("Cargando dataset crudo…")
    df = preparar(cargar_crudo())
    estado, umbral_abs, _ = estado_senal(df, senal, umbral)
    df["estado_senal"] = estado
    base = df["produciendo"] & estado.notna()
    cfg = SENALES[senal]
    log(f"{cfg['nombre']} mediana {df[cfg['columna']].median():.1f}; umbral subiendo/bajando = ±{umbral_abs:.2f} por hora")
    log("Reparto del tiempo (planta produciendo): " + ", ".join(
        f"{e} {100 * (base & (estado == e)).sum() / base.sum():.1f} %" for e in ESTADOS))

    filas = []
    for esp, cfg in ESPESADORES.items():
        tren = tren_en_servicio(df, cfg)
        for nombre_tren in [t["nombre"] for t in cfg["trenes"]] + ["AMBOS"]:
            sel_tren = base & (tren == nombre_tren)
            cfg_tren = next((t for t in cfg["trenes"] if t["nombre"] == nombre_tren), None)
            for est in ESTADOS:
                sel = sel_tren & (estado == est)
                d = df[sel]
                variables = [(rol, cfg[rol]) for rol in ROLES_ESPESADOR if cfg[rol] in df.columns]
                if cfg_tren is not None:
                    variables += [(rol, cfg_tren[campo]) for campo, rol in ROLES_TREN if cfg_tren[campo] in df.columns]
                else:
                    # AMBOS: los dos trenes, con su nombre
                    for t in cfg["trenes"]:
                        variables += [(f"{rol}_{t['nombre'].replace(' ', '').lower()}", t[campo])
                                      for campo, rol in ROLES_TREN if t[campo] in df.columns]
                variables += [(rol, col) for col, rol in PLANTA.items() if col in df.columns]
                variables += [("tanques_prom", "tanques_prom"), ("nivel_piscina", "nivel_piscina"),
                              ("molienda_total", "molienda_total")]
                for rol, col in variables:
                    e = estadisticas(d[col])
                    if e is None:
                        continue
                    filas.append({"espesador": esp, "tren": nombre_tren, "estado": est,
                                  "variable": rol, "columna": col, **e})
    res = pd.DataFrame(filas)
    res.attrs["senal"] = senal
    return res, umbral_abs


# ============================================================================
# Reporte
# ============================================================================
def _fmt(v, nd=2):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "—"
    return f"{v:,.{nd}f}" if abs(v) < 100 else f"{v:,.0f}"


def escribir_markdown(res, umbral, ruta, senal="fit114"):
    cfg = SENALES[senal]
    lineas = [f"# Parámetros de cada espesador, por tren, según {cfg['nombre']}", "",
              f"Dataset: `{os.path.basename(RUTAS['entrada'])}`. Solo minutos con planta produciendo "
              f"(molinos > {PROCESO['tonelaje_min_produccion']:g} t/h). {cfg['nombre']} suavizado (mediana 30 min); "
              f"**subiendo** = +{umbral:.2g} {cfg['unidad']} o más en 60 min, **bajando** = −{umbral:.2g} o menos, "
              "**estable** entre ambos. Un tren = exactamente una bomba de descarga en servicio. "
              "Celdas fuera del rango físico de `calidad.yaml` anuladas antes de calcular (regla E03).", "",
              "Por variable: mínimo · p10 · **mediana** · p90 · máximo (minutos). "
              "p10–p90 es la ventana operativa robusta; min/max absolutos pueden ser un dato suelto.", ""]

    for esp in res["espesador"].unique():
        lineas += [f"## {esp}", ""]
        for tren in res[res.espesador == esp]["tren"].unique():
            sub = res[(res.espesador == esp) & (res.tren == tren)]
            n = {e: int(sub[sub.estado == e]["minutos"].max()) if (sub.estado == e).any() else 0 for e in ESTADOS}
            lineas += [f"### {esp} · {tren}  (minutos: subiendo {n['subiendo']:,}, estable {n['estable']:,}, bajando {n['bajando']:,})", ""]
            lineas += ["| variable | SUBIENDO min · p10 · **p50** · p90 · max | estable p50 | bajando p50 | Δ sube−baja |",
                       "|---|---|---:|---:|---:|"]
            for var in sub["variable"].unique():
                s = sub[(sub.variable == var) & (sub.estado == "subiendo")]
                e = sub[(sub.variable == var) & (sub.estado == "estable")]
                b = sub[(sub.variable == var) & (sub.estado == "bajando")]
                if s.empty:
                    continue
                s = s.iloc[0]
                p50_e = e.iloc[0]["p50"] if not e.empty else np.nan
                p50_b = b.iloc[0]["p50"] if not b.empty else np.nan
                delta = s["p50"] - p50_b if not np.isnan(p50_b) else np.nan
                lineas.append(f"| {var} | {_fmt(s['min'])} · {_fmt(s['p10'])} · **{_fmt(s['p50'])}** · {_fmt(s['p90'])} · {_fmt(s['max'])} "
                              f"| {_fmt(p50_e)} | {_fmt(p50_b)} | {_fmt(delta)} |")
            lineas.append("")

    # Extremos entre espesadores/trenes con FIT_114 subiendo (solo trenes individuales)
    lineas += [f"## Extremos con {cfg['nombre']} subiendo (entre espesadores y trenes)", "",
               "Máximo y mínimo de la **mediana** de cada variable entre las seis combinaciones espesador·tren "
               "(sin AMBOS). Las variables de planta son iguales para todos; se omiten.", "",
               "| variable | mediana más alta | mediana más baja | rango p10–p90 más amplio |", "|---|---|---|---|"]
    sube = res[(res.estado == "subiendo") & (res.tren != "AMBOS")].copy()
    sube["amplitud"] = sube["p90"] - sube["p10"]
    for var in [v for v in sube["variable"].unique() if v not in list(PLANTA.values()) + ["tanques_prom", "nivel_piscina", "molienda_total"]]:
        g = sube[sube.variable == var]
        hi, lo, am = g.loc[g.p50.idxmax()], g.loc[g.p50.idxmin()], g.loc[g.amplitud.idxmax()]
        lineas.append(f"| {var} | {hi.espesador} {hi.tren}: **{_fmt(hi.p50)}** | {lo.espesador} {lo.tren}: **{_fmt(lo.p50)}** "
                      f"| {am.espesador} {am.tren}: {_fmt(am.p10)}–{_fmt(am.p90)} |")
    lineas.append("")
    with open(ruta, "w", encoding="utf-8") as f:
        f.write("\n".join(lineas))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--senal", choices=list(SENALES), default="fit114")
    ap.add_argument("--umbral", type=float, default=None,
                    help="cambio en 1 h para declarar sube/baja (fit114: %% de la mediana, tanques: pp)")
    ap.add_argument("--salida", default=None)
    args = ap.parse_args()
    salida = args.salida or os.path.join(RUTAS["salidas"], SENALES[args.senal]["carpeta"])
    res, umbral = analizar(args.senal, args.umbral)
    os.makedirs(salida, exist_ok=True)
    res.to_csv(os.path.join(salida, "parametros_por_tren.csv"), index=False)
    escribir_markdown(res, umbral, os.path.join(salida, "parametros_por_tren.md"), args.senal)
    log(f"\nEscrito en {salida}/parametros_por_tren.{{csv,md}}  ({len(res)} filas)")


if __name__ == "__main__":
    main()
