# -*- coding: utf-8 -*-
"""
piscina_episodios.py
================================================================================
Dos análisis sobre la piscina de recuperación de agua y FIT_114, para cada
espesador, sobre el dataset crudo:

(1) EPISODIOS DE PISCINA BAJA (< 75 %, R1): qué hacen todos los parámetros
    operativos cuando el nivel cruza bajo el mínimo, minuto a minuto, contra
    una referencia con la piscina sana (>= 90 %, R2).
    Hipótesis del usuario: con la piscina baja se BAJA la descarga a
    propósito para favorecer el rebose.

(2) TENDENCIA — "¿qué se hizo para que la piscina suba?" (pedido del usuario
    2026-09-16): ventana (p10-p90, mediana) de todos los parámetros operativos
    en los minutos en que la piscina está SUBIENDO y llega al tercio alto en
    la hora siguiente, contrastada con la mediana cuando está BAJANDO desde el
    tercio alto. Lo mismo para FIT_114 (flujo hacia las piscinas).
      subiendo : cambio en 60 min >= +umbral y nivel(t+60) en tercio alto
      bajando  : cambio en 60 min <= -umbral y nivel(t-60) en tercio alto
    (nivel suavizado con mediana móvil de 30 min; umbral 1 pp/h para la
    piscina y 2 % de la mediana por hora para FIT_114). Solo minutos con la
    planta produciendo y con un tren de descarga en servicio, como E03/E04.

Las señales activas (vel_descarga, vel_cizalle, wt_activo) se reconstruyen
con la misma regla que E04 (`atoro_alimentacion.senales_activas`).

Uso:
    python -m espesadores.dominio.piscina_episodios --espesador TH-001
"""
import argparse
import os

import pandas as pd

from espesadores.config import ESPESADORES, GLOBALES, PROCESO, REGLAS_PISCINAS
from espesadores.dominio.piscinas import derivar_nivel
from espesadores.dominio.atoro_alimentacion import (
    cargar_crudo, senales_activas, columnas_operativas, detectar_episodios,
    perfil_desde_t0, log)


def _ventana(df, mascara, cols):
    sub = df.loc[mascara, cols]
    return pd.DataFrame({
        "p10": sub.quantile(.10), "mediana": sub.median(), "p90": sub.quantile(.90),
        "n": sub.count()}).round(3)


def tendencia(df, senal, cols, umbral_por_hora, nombre, produciendo):
    """Ventana de `cols` cuando `senal` sube al tercio alto vs cuando baja desde él."""
    s = df[senal].rolling(30, min_periods=10, center=True).median()
    cambio = s.diff(60)                       # variación en los últimos 60 min
    tercio_alto = s >= s.quantile(2 / 3)
    llega_alto = tercio_alto.shift(-60).fillna(False).astype(bool)
    venia_alto = tercio_alto.shift(60).fillna(False).astype(bool)
    subiendo = (cambio >= umbral_por_hora) & llega_alto & produciendo
    bajando = (cambio <= -umbral_por_hora) & venia_alto & produciendo
    log(f"\n  {nombre}: subiendo hacia el tercio alto = {subiendo.mean()*100:.1f}% del tiempo, "
        f"bajando desde el tercio alto = {bajando.mean()*100:.1f}%  (umbral {umbral_por_hora:g}/h, "
        f"tercio alto >= {s.quantile(2/3):.1f})")
    sube, baja = _ventana(df, subiendo, cols), _ventana(df, bajando, cols)
    out = sube.rename(columns=lambda c: f"subiendo_{c}").join(
        baja.rename(columns=lambda c: f"bajando_{c}"))
    log(f"  {'variable':24s} {'sube p10':>10s} {'sube med':>10s} {'sube p90':>10s} {'baja med':>10s}")
    for c in cols:
        log(f"  {c[-24:]:24s}{out.loc[c,'subiendo_p10']:10.2f}{out.loc[c,'subiendo_mediana']:10.2f}"
            f"{out.loc[c,'subiendo_p90']:10.2f}{out.loc[c,'bajando_mediana']:10.2f}")
    return out


def analizar(espesador="TH-001", ventana_min=120, bin_min=10, umbral_pct=None,
             min_episodio_min=None, max_episodio_min=720):
    cfg = ESPESADORES[espesador]
    umbral_pct = umbral_pct or REGLAS_PISCINAS["nivel_minimo_pct"]
    sano_pct = REGLAS_PISCINAS["nivel_cierre_guardia_pct"]
    min_episodio_min = min_episodio_min or REGLAS_PISCINAS["episodio_minimo_reportable_min"]

    log("Cargando dataset crudo...")
    df = senales_activas(cargar_crudo(), cfg)
    df["nivel_piscina"] = derivar_nivel(df)["nivel_piscina"]
    cols = [c for _, c in columnas_operativas(cfg, df)]
    molinos = [m for m in GLOBALES["molinos"] if m in df.columns]
    produciendo = (df[molinos].sum(axis=1, min_count=1) > PROCESO["tonelaje_min_produccion"]) \
        & df["vel_descarga"].notna()

    carpeta = os.path.join("data", "01_interim")
    os.makedirs(carpeta, exist_ok=True)
    tag = espesador.replace("-", "")

    # ---------------- (1) episodios de piscina baja ----------------
    log(f"  nivel de piscina: mediana={df.nivel_piscina.median():.1f}%  "
        f"tiempo bajo {umbral_pct}% = {100*(df.nivel_piscina < umbral_pct).mean():.2f}%")
    baja = df["nivel_piscina"] < umbral_pct
    sana = df["nivel_piscina"] >= sano_pct
    cols_ep = cols + ["nivel_piscina"]
    base = {c: round(float(df.loc[sana & produciendo, c].median()), 3) for c in cols_ep}
    durante = {c: round(float(df.loc[baja & produciendo, c].median()), 3) for c in cols_ep}
    todos = detectar_episodios(baja, min_episodio_min, None)
    eps = detectar_episodios(baja, min_episodio_min, max_episodio_min)
    log(f"\n  Episodios de piscina < {umbral_pct}% durante >= {min_episodio_min} min: "
        f"{len(todos)} en total -> {len(eps)} usados (<= {max_episodio_min} min)")
    if not eps.empty:
        perfil, n_min = perfil_desde_t0(df, eps["inicio"], cols_ep, ventana_min, bin_min)
        log(f"  Perfil desde el cruce bajo {umbral_pct}% ({ventana_min} min, bins {bin_min} min, "
            f">= {n_min} puntos por bin)")
        log(f"  {'variable':24s} {'sana':>10s} {'baja':>10s} {'t=0':>10s} {'t=60':>10s} {'t=120':>10s}")
        for c in cols_ep:
            fila = [base[c], durante[c]] + [perfil[c].get(t, float("nan")) for t in (0, 60, 120)]
            log(f"  {c[-24:]:24s}" + "".join(f"{v:10.2f}" for v in fila))
        perfil.to_csv(os.path.join(carpeta, f"piscina_baja_{tag}_perfil.csv"))
        eps.to_csv(os.path.join(carpeta, f"piscina_baja_{tag}_episodios.csv"), index=False)
        pd.DataFrame({"sana": base, "baja": durante}).to_csv(
            os.path.join(carpeta, f"piscina_baja_{tag}_base.csv"))
        log(f"  [OK] {carpeta}/piscina_baja_{tag}_{{perfil,episodios,base}}.csv")

    # ---------------- (2) tendencia: subiendo vs bajando ----------------
    T = tendencia(df, "nivel_piscina", cols, 1.0, "PISCINA", produciendo)
    T.to_csv(os.path.join(carpeta, f"piscina_subiendo_{tag}.csv"))
    log(f"  [OK] {carpeta}/piscina_subiendo_{tag}.csv")
    if "FIT_114" in df.columns:
        umbral_f = 0.02 * float(df["FIT_114"].median())
        F = tendencia(df, "FIT_114", cols, umbral_f, "FIT_114", produciendo)
        F.to_csv(os.path.join(carpeta, f"fit114_subiendo_{tag}.csv"))
        log(f"  [OK] {carpeta}/fit114_subiendo_{tag}.csv")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--espesador", default="TH-001", choices=list(ESPESADORES.keys()))
    ap.add_argument("--ventana-min", type=int, default=120)
    ap.add_argument("--bin-min", type=int, default=10)
    ap.add_argument("--umbral-pct", type=float, default=None)
    ap.add_argument("--min-episodio-min", type=int, default=None)
    ap.add_argument("--max-episodio-min", type=int, default=720)
    args = ap.parse_args()
    analizar(args.espesador, args.ventana_min, args.bin_min, args.umbral_pct,
             args.min_episodio_min, args.max_episodio_min)


if __name__ == "__main__":
    main()
