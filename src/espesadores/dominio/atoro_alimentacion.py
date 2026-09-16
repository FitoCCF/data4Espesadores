# -*- coding: utf-8 -*-
"""
atoro_alimentacion.py
================================================================================
Análisis por episodios: qué pasa con el flujo de alimentación y la apertura
de la válvula de cada espesador DESPUÉS de que la molienda se detiene y
vuelve a arrancar.

HIPÓTESIS DEL USUARIO (2026-09-16): un corte aguas arriba (cortocircuito en
un ciclón, parada de un equipo de molienda) hace que mineral grueso se
apelmace en las válvulas de ingreso. El flujo de alimentación cae. Cuando la
molienda vuelve a la normalidad, el atoro NO se resuelve solo: sigue
haciendo parecer que el flujo de alimentación está bajo, aunque el molino ya
esté produciendo normal. El operador compensa abriendo la válvula.

MÉTODO: análisis de épocas superpuestas (superposed epoch analysis), la
técnica estándar para esta pregunta ("¿qué pasa en promedio en los N minutos
siguientes a un tipo de evento?"). Se detectan episodios donde el tonelaje
del molino cae por debajo del umbral de "planta produciendo" (el mismo que
usa E03) durante al menos `min_parada_min`, y luego se recupera. Se alinean
todos los episodios en el instante t=0 = primer minuto con tonelaje normal
otra vez, y se promedia (mediana) cada variable en bins de tiempo desde t=0,
comparado contra un período estable de referencia (lejos de cualquier
parada).

Corre sobre el dataset CRUDO (antes del filtro de "planta produciendo" de
E03), porque ese filtro elimina justamente las filas de parada que este
análisis necesita para detectar los episodios.

Uso:
    python -m espesadores.dominio.atoro_alimentacion --espesador TH-001
    python -m espesadores.dominio.atoro_alimentacion --espesador TH-001 \
        --ventana-min 180 --bin-min 15 --min-parada-min 10
"""
import argparse
import os

import pandas as pd

from espesadores.config import ESPESADORES, GLOBALES, PROCESO, RUTAS


def log(msg=""):
    print(msg, flush=True)


def _cargar_crudo():
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


def detectar_paradas(df, col_ton, umbral, min_parada_min, max_parada_min=None):
    """
    Episodios de parada: bloques contiguos con tonelaje <= umbral.

    `max_parada_min` separa el corte breve aguas arriba (cortocircuito de
    ciclón, parada puntual de un equipo) de una parada de planta completa
    (mantenimiento programado, días sin producir): la dinámica de
    recuperación de una y otra no es comparable, y mezclarlas diluye
    cualquier patrón. Por defecto no filtra (None); pásalo desde `analizar`.
    """
    parado = (df[col_ton] <= umbral).fillna(False)
    bloque = parado.ne(parado.shift()).cumsum()
    episodios = []
    for _, g in df.groupby(bloque):
        if not parado.loc[g.index[0]]:
            continue
        duracion_min = (g.index[-1] - g.index[0]).total_seconds() / 60.0 + 1
        if duracion_min < min_parada_min:
            continue
        if max_parada_min is not None and duracion_min > max_parada_min:
            continue
        pos = df.index.get_loc(g.index[-1])
        if pos + 1 >= len(df):
            continue
        episodios.append({
            "inicio_parada": g.index[0], "fin_parada": g.index[-1],
            "duracion_parada_min": round(duracion_min, 1),
            "inicio_recuperacion": df.index[pos + 1],
        })
    return pd.DataFrame(episodios)


def perfil_recuperacion(df, episodios, cols, ventana_min, bin_min):
    """Mediana de cada columna por bin de minutos-desde-la-recuperación."""
    filas = []
    for _, ep in episodios.iterrows():
        t0 = ep["inicio_recuperacion"]
        ventana = df.loc[t0: t0 + pd.Timedelta(minutes=ventana_min)]
        if ventana.empty:
            continue
        minutos = (ventana.index - t0).total_seconds() / 60.0
        for col in cols:
            if col not in ventana.columns:
                continue
            for m, v in zip(minutos, ventana[col].values):
                filas.append({"variable": col, "minuto": m, "valor": v})
    E = pd.DataFrame(filas)
    if E.empty:
        return pd.DataFrame(), 0
    E["bin"] = (E["minuto"] // bin_min * bin_min).astype(int)
    n_puntos_por_bin = E.groupby("bin").size().min()
    perfil = E.groupby(["bin", "variable"])["valor"].median().unstack("variable")
    return perfil, int(n_puntos_por_bin)


def baseline_estable(df, col_ton, umbral, cols, horas_lejos=4):
    """Mediana de cada columna lejos (>= horas_lejos) de cualquier parada."""
    parado = (df[col_ton] <= umbral).fillna(False)
    cerca_de_parada = parado.rolling(f"{horas_lejos}h", min_periods=1).max().astype(bool)
    estable = df.loc[~cerca_de_parada]
    return {c: round(float(estable[c].median()), 2) for c in cols if c in estable.columns}


def analizar(espesador="TH-001", ventana_min=180, bin_min=15, min_parada_min=10,
             max_parada_min=240):
    cfg = ESPESADORES[espesador]
    log(f"Cargando dataset crudo: {RUTAS['entrada']}")
    df = _cargar_crudo()
    log(f"  {len(df):,} filas, {df.index.min()} -> {df.index.max()}")

    col_ton = GLOBALES["alim_total_molino"]
    umbral = PROCESO["tonelaje_min_produccion"]
    particion = cfg["flujo_alim"] + "_particion"
    flujos = [f for f in cfg["flujos_todos"] if f in df.columns]
    if len(flujos) == 3:
        df[particion] = 100.0 * df[cfg["flujo_alim"]] / df[flujos].sum(axis=1).replace(0, float("nan"))

    log(f"\nDetectando paradas de molienda ({col_ton} <= {umbral} t/h, "
        f"entre {min_parada_min} y {max_parada_min} min seguidos -- excluye paradas "
        f"de planta completas, que tienen otra dinamica de recuperacion)...")
    todas = detectar_paradas(df, col_ton, umbral, min_parada_min, max_parada_min=None)
    episodios = detectar_paradas(df, col_ton, umbral, min_parada_min, max_parada_min)
    log(f"  {len(todas)} episodios de parada en total ({len(todas)-len(episodios)} "
        f"excluidos por durar mas de {max_parada_min} min)")
    log(f"  {len(episodios)} episodios breves usados para el perfil de recuperacion")
    if episodios.empty:
        log("  Sin episodios: no se puede continuar el analisis.")
        return None

    log(f"  duracion de parada (breves): mediana={episodios.duracion_parada_min.median():.0f} min  "
        f"p90={episodios.duracion_parada_min.quantile(.9):.0f} min  "
        f"max={episodios.duracion_parada_min.max():.0f} min")

    cols = [c for c in (cfg["flujo_alim"], particion, cfg["valvula_alim"], col_ton) if c in df.columns]
    log(f"\nPerfil de recuperacion: {ventana_min} min tras el reinicio, bins de {bin_min} min")
    perfil, n_min_por_bin = perfil_recuperacion(df, episodios, cols, ventana_min, bin_min)
    if perfil.empty:
        log("  Sin datos suficientes en la ventana de recuperacion.")
        return None
    log(f"  (cada bin promedia al menos {n_min_por_bin} puntos de dato, de {len(episodios)} episodios)")

    base = baseline_estable(df, col_ton, umbral, cols)
    log("\n  Valor de referencia (periodo estable, >=4h lejos de cualquier parada):")
    for c in cols:
        log(f"    {c:28s} {base.get(c, float('nan'))}")

    log("")
    log(f"  {'minuto':>7s}" + "".join(f"{c:>20s}" for c in cols))
    for m, row in perfil.iterrows():
        log(f"  {m:7d}" + "".join(f"{row.get(c, float('nan')):20.2f}" for c in cols))

    carpeta = os.path.join("data", "01_interim")
    os.makedirs(carpeta, exist_ok=True)
    base_nombre = f"atoro_alimentacion_{espesador.replace('-', '')}"
    ruta_perfil = os.path.join(carpeta, base_nombre + "_perfil.csv")
    ruta_episodios = os.path.join(carpeta, base_nombre + "_episodios.csv")
    perfil.to_csv(ruta_perfil)
    episodios.to_csv(ruta_episodios, index=False)
    log(f"\n[OK] perfil     -> {ruta_perfil}")
    log(f"[OK] episodios  -> {ruta_episodios}")

    return {"perfil": perfil, "episodios": episodios, "base": base,
            "n_min_por_bin": n_min_por_bin, "cols": cols, "particion_col": particion}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--espesador", default="TH-001", choices=list(ESPESADORES.keys()))
    ap.add_argument("--ventana-min", type=int, default=180)
    ap.add_argument("--bin-min", type=int, default=15)
    ap.add_argument("--min-parada-min", type=int, default=10)
    ap.add_argument("--max-parada-min", type=int, default=240)
    args = ap.parse_args()
    analizar(args.espesador, args.ventana_min, args.bin_min, args.min_parada_min,
             args.max_parada_min)


if __name__ == "__main__":
    main()
