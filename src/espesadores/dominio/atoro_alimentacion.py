# -*- coding: utf-8 -*-
"""
atoro_alimentacion.py
================================================================================
Análisis por episodios: qué pasa con el flujo de alimentación y la apertura
de la válvula de cada espesador DESPUÉS de un problema en molienda.

HIPÓTESIS DEL USUARIO (2026-09-16): un corte aguas arriba (cortocircuito en
un ciclón, parada de un equipo de molienda) hace que mineral grueso se
apelmace en las válvulas de ingreso. El flujo de alimentación cae. Cuando la
molienda vuelve a la normalidad, el atoro NO se resuelve solo: sigue
haciendo parecer que el flujo de alimentación está bajo, aunque el molino ya
esté produciendo normal. El operador compensa abriendo la válvula.

DOS TIPOS DE EVENTO (revisión 2026-09-16, a pedido del usuario: considerar
todos los molinos, no solo PB01 — `tags.yaml::globales.molinos`):
  - PARADA TOTAL: la suma de los molinos cae bajo el umbral de "planta
    produciendo". La planta entera se detiene y arranca de nuevo.
  - PARADA PARCIAL: un molino cae bajo el umbral mientras la suma sigue
    arriba (el otro sigue produciendo). Es el escenario más parecido al que
    describe el usuario: la planta no para, pero aguas arriba hay una
    perturbación que puede mandar material distinto a los espesadores.

MÉTODO: análisis de épocas superpuestas (superposed epoch analysis). Se
alinean todos los episodios de cada tipo en t=0 = primer minuto en que la
condición del evento deja de cumplirse (la molienda "vuelve"), y se toma la
mediana de cada variable en bins de tiempo desde t=0, comparada contra un
período estable de referencia (lejos de cualquier evento).

Corre sobre el dataset CRUDO (antes del filtro de "planta produciendo" de
E03), porque ese filtro elimina justamente las filas de parada.

Uso:
    python -m espesadores.dominio.atoro_alimentacion --espesador TH-001
"""
import argparse
import os

import pandas as pd

from espesadores.config import ESPESADORES, GLOBALES, PROCESO, RUTAS


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


def detectar_episodios(condicion, min_min, max_min=None):
    """
    Bloques contiguos donde `condicion` (Series booleana con índice temporal)
    es True, de duración entre min_min y max_min. Devuelve inicio, fin,
    duración y el primer instante posterior (t=0 de la recuperación).

    `max_min` separa el evento breve del prolongado (p.ej. una parada de
    planta de días): la dinámica de recuperación de uno y otro no es
    comparable, y mezclarlos diluye cualquier patrón.
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
        ventana = df.loc[t0: t0 + pd.Timedelta(minutes=ventana_min)]
        if ventana.empty:
            continue
        minutos = (ventana.index - t0).total_seconds() / 60.0
        for col in cols:
            if col in ventana.columns:
                for m, v in zip(minutos, ventana[col].values):
                    filas.append({"variable": col, "minuto": m, "valor": v})
    E = pd.DataFrame(filas)
    if E.empty:
        return pd.DataFrame(), 0
    E["bin"] = (E["minuto"] // bin_min * bin_min).astype(int)
    perfil = E.groupby(["bin", "variable"])["valor"].median().unstack("variable")
    return perfil, int(E.groupby("bin").size().min())


def baseline_lejos_de(df, condicion, cols, horas_lejos=4):
    """Mediana de cada columna a >= horas_lejos de cualquier instante con condicion=True."""
    cerca = condicion.fillna(False).astype(float).rolling(f"{horas_lejos}h", min_periods=1).max().astype(bool)
    estable = df.loc[~cerca]
    return {c: round(float(estable[c].median()), 2) for c in cols if c in estable.columns}


def _imprimir_perfil(perfil, cols, base):
    log(f"  {'minuto':>7s}" + "".join(f"{c[-18:]:>20s}" for c in cols))
    log(f"  {'base':>7s}" + "".join(f"{base.get(c, float('nan')):20.2f}" for c in cols))
    for m, row in perfil.iterrows():
        log(f"  {m:7d}" + "".join(f"{row.get(c, float('nan')):20.2f}" for c in cols))


def analizar(espesador="TH-001", ventana_min=180, bin_min=15, min_evento_min=10,
             max_evento_min=240):
    cfg = ESPESADORES[espesador]
    log(f"Cargando dataset crudo: {RUTAS['entrada']}")
    df = cargar_crudo()
    log(f"  {len(df):,} filas, {df.index.min()} -> {df.index.max()}")

    molinos = [m for m in GLOBALES["molinos"] if m in df.columns]
    umbral = PROCESO["tonelaje_min_produccion"]
    total = df[molinos].sum(axis=1, min_count=1)
    df["_molienda_total"] = total

    particion = cfg["flujo_alim"] + "_particion"
    flujos = [f for f in cfg["flujos_todos"] if f in df.columns]
    if len(flujos) == 3:
        df[particion] = 100.0 * df[cfg["flujo_alim"]] / df[flujos].sum(axis=1).replace(0, float("nan"))

    cols = [c for c in (cfg["flujo_alim"], particion, cfg["valvula_alim"]) if c in df.columns]
    cols += molinos + ["_molienda_total"]

    # Condiciones de evento
    algun_molino_bajo = (df[molinos] <= umbral).any(axis=1)
    total_bajo = total <= umbral
    cond = {
        "parada_total": total_bajo,
        "parada_parcial": algun_molino_bajo & ~total_bajo,
    }
    cualquier_evento = algun_molino_bajo | total_bajo
    base = baseline_lejos_de(df, cualquier_evento, cols)

    resultados = {}
    carpeta = os.path.join("data", "01_interim")
    os.makedirs(carpeta, exist_ok=True)
    for nombre, condicion in cond.items():
        log("")
        log("=" * 78)
        log(f"EVENTO: {nombre.upper()}  (molinos={molinos}, umbral={umbral} t/h, "
            f"{min_evento_min}-{max_evento_min} min)")
        log("=" * 78)
        todos = detectar_episodios(condicion, min_evento_min, None)
        eps = detectar_episodios(condicion, min_evento_min, max_evento_min)
        log(f"  {len(todos)} episodios en total, {len(todos) - len(eps)} excluidos por durar "
            f"mas de {max_evento_min} min -> {len(eps)} usados")
        if eps.empty:
            log("  Sin episodios de este tipo.")
            continue
        log(f"  duracion: mediana={eps.duracion_min.median():.0f} min  "
            f"p90={eps.duracion_min.quantile(.9):.0f}  max={eps.duracion_min.max():.0f}")
        perfil, n_min = perfil_desde_t0(df, eps["t0_recuperacion"], cols, ventana_min, bin_min)
        if perfil.empty:
            continue
        log(f"  Perfil de recuperacion: {ventana_min} min desde t0, bins de {bin_min} min "
            f"(>= {n_min} puntos por bin). 'base' = periodo estable >= 4h lejos de todo evento.")
        log("")
        _imprimir_perfil(perfil, cols, base)

        base_nombre = f"atoro_{nombre}_{espesador.replace('-', '')}"
        perfil.to_csv(os.path.join(carpeta, base_nombre + "_perfil.csv"))
        eps.to_csv(os.path.join(carpeta, base_nombre + "_episodios.csv"), index=False)
        pd.Series(base, name="base").to_csv(os.path.join(carpeta, base_nombre + "_base.csv"))
        log(f"\n  [OK] {carpeta}/{base_nombre}_perfil.csv / _episodios.csv / _base.csv")
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
