# -*- coding: utf-8 -*-
"""
atoro_alimentacion.py
================================================================================
Análisis por episodios: qué pasa con TODOS los parámetros operativos de cada
espesador DESPUÉS de un problema en molienda, y cómo se mueven en las horas
siguientes hasta estabilizarse.

HIPÓTESIS DEL USUARIO (2026-09-16): un corte aguas arriba (cortocircuito en
un ciclón, parada de un equipo de molienda) hace que mineral grueso se
apelmace en las válvulas de ingreso. El flujo de alimentación cae. Cuando la
molienda vuelve a la normalidad, el atoro NO se resuelve solo: sigue
haciendo parecer que el flujo de alimentación está bajo, aunque el molino ya
esté produciendo normal. El operador compensa abriendo la válvula.

TIPOS DE EVENTO (`tags.yaml::globales.molinos`, verificado: solo PB01 y PB02):
  - parada_PB01 : Molino 1 bajo el umbral mientras Molino 2 sigue.
  - parada_PB02 : Molino 2 bajo el umbral mientras Molino 1 sigue.
  - parada_parcial : cualquiera de los dos (unión de las anteriores).
  - parada_total : la suma de ambos bajo el umbral (la planta entera para).

MÉTODO: análisis de épocas superpuestas (superposed epoch analysis). Se
alinean todos los episodios de cada tipo en t=0 = primer minuto en que la
condición del evento deja de cumplirse (la molienda "vuelve"), y se toma la
mediana de cada variable en bins de tiempo desde t=0, comparada contra un
período estable de referencia (lejos de cualquier evento).

Corre sobre el dataset CRUDO (antes del filtro de "planta produciendo" de
E03), porque ese filtro elimina justamente las filas de parada. Las señales
activas (vel_descarga, vel_cizalle, wt_activo) se reconstruyen con la misma
regla que E04.

Uso:
    python -m espesadores.dominio.atoro_alimentacion --espesador TH-001
"""
import argparse
import os

import numpy as np
import pandas as pd

from espesadores.config import ESPESADORES, GLOBALES, PROCESO, RUTAS

ROLES = ["presion_cama", "torque", "nivel_interfaz", "flujo_alim", "wt_activo",
         "vel_descarga", "vel_cizalle", "floculante", "valvula_alim"]


def log(msg=""):
    print(msg, flush=True)


def cargar_crudo():
    ruta = RUTAS["entrada"]
    df = pd.read_parquet(ruta) if ruta.endswith(".parquet") else pd.read_csv(ruta, low_memory=False)
    tcol = GLOBALES["timestamp"]
    if tcol in df.columns:
        df[tcol] = pd.to_datetime(df[tcol], errors="coerce")
        df = df.sort_values(tcol).set_index(tcol)
    else:
        df.index = pd.to_datetime(df.index, errors="coerce")
        df = df.sort_index()
    return df


def senales_activas(df, cfg):
    """vel_descarga / vel_cizalle / wt_activo del primer tren en servicio (regla de E04)."""
    umbral = PROCESO["umbral_bomba_on"]
    for c in ("vel_descarga", "vel_cizalle", "wt_activo"):
        df[c] = np.nan
    asignado = pd.Series(False, index=df.index)
    for tren in cfg["trenes"]:
        if tren["descarga"] not in df.columns:
            continue
        activo = (df[tren["descarga"]] > umbral) & ~asignado
        df.loc[activo, "vel_descarga"] = df.loc[activo, tren["descarga"]]
        if tren["cizalle"] in df.columns:
            df.loc[activo, "vel_cizalle"] = df.loc[activo, tren["cizalle"]]
        if tren["wt"] in df.columns:
            df.loc[activo, "wt_activo"] = df.loc[activo, tren["wt"]]
        asignado |= activo
    return df


def columnas_operativas(cfg, df):
    """[(rol, columna)] de los parámetros operativos presentes en df."""
    out = []
    for rol in ROLES:
        col = cfg.get(rol, rol)
        if col in df.columns:
            out.append((rol, col))
    return out


def detectar_episodios(condicion, min_min, max_min=None):
    """
    Bloques contiguos donde `condicion` (Series booleana con índice temporal)
    es True, de duración entre min_min y max_min. Devuelve inicio, fin,
    duración y el primer instante posterior (t=0 de la recuperación).
    """
    condicion = condicion.fillna(False).astype(bool)
    idx = condicion.index
    bloque = condicion.ne(condicion.shift()).cumsum()
    episodios = []
    for _, g in condicion.groupby(bloque):
        if not g.iloc[0]:
            continue
        duracion_min = (g.index[-1] - g.index[0]).total_seconds() / 60.0 + 1
        if duracion_min < min_min or (max_min is not None and duracion_min > max_min):
            continue
        pos = idx.get_loc(g.index[-1])
        if pos + 1 >= len(idx):
            continue
        episodios.append({"inicio": g.index[0], "fin": g.index[-1],
                          "duracion_min": round(duracion_min, 1),
                          "t0_recuperacion": idx[pos + 1]})
    return pd.DataFrame(episodios)


def perfil_desde_t0(df, t0s, cols, ventana_min, bin_min):
    """Mediana de cada columna por bin de minutos desde cada t0."""
    filas = []
    for t0 in t0s:
        ventana = df.loc[t0: t0 + pd.Timedelta(minutes=ventana_min), cols]
        if ventana.empty:
            continue
        v = ventana.copy()
        v["minuto"] = (ventana.index - t0).total_seconds() / 60.0
        filas.append(v)
    if not filas:
        return pd.DataFrame(), 0
    E = pd.concat(filas)
    E["bin"] = (E["minuto"] // bin_min * bin_min).astype(int)
    perfil = E.groupby("bin")[cols].median()
    return perfil, int(E.groupby("bin").size().min())


def baseline_lejos_de(df, condicion, cols, horas_lejos=4):
    """Mediana de cada columna a >= horas_lejos de cualquier instante con condicion=True."""
    cerca = condicion.fillna(False).astype(float).rolling(f"{horas_lejos}h", min_periods=1).max().astype(bool)
    estable = df.loc[~cerca]
    return {c: round(float(estable[c].median()), 3) for c in cols if c in estable.columns}


def analizar(espesador="TH-001", ventana_min=180, bin_min=15, min_evento_min=10,
             max_evento_min=240):
    cfg = ESPESADORES[espesador]
    log(f"Cargando dataset crudo: {RUTAS['entrada']}")
    df = senales_activas(cargar_crudo(), cfg)
    log(f"  {len(df):,} filas, {df.index.min()} -> {df.index.max()}")

    molinos = [m for m in GLOBALES["molinos"] if m in df.columns]
    umbral = PROCESO["tonelaje_min_produccion"]
    total = df[molinos].sum(axis=1, min_count=1)
    df["_molienda_total"] = total

    cols = [c for _, c in columnas_operativas(cfg, df)] + molinos + ["_molienda_total"]

    bajo = {m: (df[m] <= umbral) for m in molinos}
    total_bajo = total <= umbral
    algun_bajo = pd.concat(bajo.values(), axis=1).any(axis=1)
    cond = {"parada_total": total_bajo, "parada_parcial": algun_bajo & ~total_bajo}
    for m in molinos:
        otros = [o for o in molinos if o != m]
        sigue_otro = pd.concat([~bajo[o] for o in otros], axis=1).all(axis=1) if otros else ~total_bajo
        cond[f"parada_{m.split('_')[-1]}"] = bajo[m] & sigue_otro
    base = baseline_lejos_de(df, algun_bajo | total_bajo, cols)

    carpeta = os.path.join("data", "01_interim")
    os.makedirs(carpeta, exist_ok=True)
    resultados = {}
    for nombre, condicion in cond.items():
        log("")
        log("=" * 78)
        log(f"EVENTO: {nombre.upper()}  (umbral={umbral} t/h, {min_evento_min}-{max_evento_min} min)")
        log("=" * 78)
        todos = detectar_episodios(condicion, min_evento_min, None)
        eps = detectar_episodios(condicion, min_evento_min, max_evento_min)
        log(f"  {len(todos)} episodios en total, {len(todos) - len(eps)} excluidos por durar "
            f"mas de {max_evento_min} min -> {len(eps)} usados")
        if eps.empty:
            continue
        log(f"  duracion: mediana={eps.duracion_min.median():.0f} min  "
            f"p90={eps.duracion_min.quantile(.9):.0f}  max={eps.duracion_min.max():.0f}")
        perfil, n_min = perfil_desde_t0(df, eps["t0_recuperacion"], cols, ventana_min, bin_min)
        if perfil.empty:
            continue
        log(f"  Perfil: {ventana_min} min desde t0, bins de {bin_min} min (>= {n_min} puntos por bin)")
        log(f"  {'variable':24s} {'base':>10s} {'t=0':>10s} {'t=60':>10s} {'t=120':>10s} {'t=180':>10s}")
        for c in cols:
            fila = [base.get(c, np.nan)] + [perfil[c].get(t, np.nan) for t in (0, 60, 120, 180)]
            log(f"  {c[-24:]:24s}" + "".join(f"{v:10.2f}" for v in fila))
        base_nombre = f"atoro_{nombre}_{espesador.replace('-', '')}"
        perfil.to_csv(os.path.join(carpeta, base_nombre + "_perfil.csv"))
        eps.to_csv(os.path.join(carpeta, base_nombre + "_episodios.csv"), index=False)
        pd.Series(base, name="base").to_csv(os.path.join(carpeta, base_nombre + "_base.csv"))
        log(f"  [OK] {carpeta}/{base_nombre}_{{perfil,episodios,base}}.csv")
        resultados[nombre] = {"perfil": perfil, "episodios": eps, "base": base}
    return resultados


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--espesador", default="TH-001", choices=list(ESPESADORES.keys()))
    ap.add_argument("--ventana-min", type=int, default=180)
    ap.add_argument("--bin-min", type=int, default=15)
    ap.add_argument("--min-evento-min", type=int, default=10)
    ap.add_argument("--max-evento-min", type=int, default=240)
    args = ap.parse_args()
    analizar(args.espesador, args.ventana_min, args.bin_min, args.min_evento_min,
             args.max_evento_min)


if __name__ == "__main__":
    main()
