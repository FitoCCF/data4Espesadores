# -*- coding: utf-8 -*-
"""
piscina_episodios.py
================================================================================
Análisis por episodios de PISCINA BAJA: qué hace el operador con la bomba de
descarga (y la válvula / el flujo de alimentación) de cada espesador cuando
el nivel de la piscina de recuperación de agua cae bajo el mínimo de R1.

HIPÓTESIS DEL USUARIO (2026-09-16): si la piscina está baja, se BAJA la
velocidad de la bomba de descarga a propósito — que el espesador no
descargue, para favorecer el rebose (que es lo que alimenta la piscina).

La comparación agregada por terciles de nivel (E10) dio lo contrario en los
tres espesadores. Pero un tercil "bajo" incluye mucho nivel que no es
crítico; la regla operativa habla de un umbral concreto (75%, R1). Aquí se
prueba por episodio: bloques de al menos `episodio_minimo_reportable_min`
minutos con el nivel bajo el umbral, alineados en t=0 = primer minuto bajo
el umbral, y se sigue vel_descarga en los minutos siguientes contra un
período de referencia con la piscina sana (>= nivel de cierre de guardia).

Corre sobre el dataset crudo: reconstruye el nivel con la misma regla de
`dominio/piscinas.py` y la señal activa de descarga con la misma regla de
E04 (primer tren con bomba > umbral_bomba_on).

Uso:
    python -m espesadores.dominio.piscina_episodios --espesador TH-001
"""
import argparse
import os

import numpy as np
import pandas as pd

from espesadores.config import ESPESADORES, PROCESO, REGLAS_PISCINAS
from espesadores.dominio.piscinas import derivar_nivel
from espesadores.dominio.atoro_alimentacion import (
    cargar_crudo, detectar_episodios, perfil_desde_t0, log)


def senal_descarga_activa(df, cfg):
    """vel_descarga del primer tren en servicio, misma regla que E04."""
    umbral = PROCESO["umbral_bomba_on"]
    vel = pd.Series(np.nan, index=df.index)
    asignado = pd.Series(False, index=df.index)
    for tren in cfg["trenes"]:
        if tren["descarga"] not in df.columns:
            continue
        activo = (df[tren["descarga"]] > umbral) & ~asignado
        vel[activo] = df.loc[activo, tren["descarga"]]
        asignado |= activo
    return vel


def analizar(espesador="TH-001", ventana_min=120, bin_min=10, umbral_pct=None,
             min_episodio_min=None, max_episodio_min=720):
    cfg = ESPESADORES[espesador]
    umbral_pct = umbral_pct or REGLAS_PISCINAS["nivel_minimo_pct"]
    sano_pct = REGLAS_PISCINAS["nivel_cierre_guardia_pct"]
    min_episodio_min = min_episodio_min or REGLAS_PISCINAS["episodio_minimo_reportable_min"]

    log("Cargando dataset crudo...")
    df = cargar_crudo()
    df["nivel_piscina"] = derivar_nivel(df)["nivel_piscina"]
    df["vel_descarga"] = senal_descarga_activa(df, cfg)
    cols = [c for c in ("vel_descarga", cfg["valvula_alim"], cfg["flujo_alim"], "nivel_piscina")
            if c in df.columns]

    log(f"  nivel de piscina: mediana={df.nivel_piscina.median():.1f}%  "
        f"p10={df.nivel_piscina.quantile(.1):.1f}%  "
        f"tiempo bajo {umbral_pct}% = {100*(df.nivel_piscina < umbral_pct).mean():.2f}%")

    baja = df["nivel_piscina"] < umbral_pct
    sana = df["nivel_piscina"] >= sano_pct
    base = {c: round(float(df.loc[sana, c].median()), 2) for c in cols}
    durante = {c: round(float(df.loc[baja, c].median()), 2) for c in cols}

    log("")
    log("=" * 78)
    log(f"PISCINA BAJA (< {umbral_pct}%) vs SANA (>= {sano_pct}%): mediana de cada variable")
    log("=" * 78)
    log(f"  {'variable':22s} {'piscina sana':>14s} {'piscina baja':>14s} {'diferencia':>12s}")
    for c in cols:
        log(f"  {c:22s} {base[c]:14.2f} {durante[c]:14.2f} {durante[c]-base[c]:+12.2f}")

    todos = detectar_episodios(baja, min_episodio_min, None)
    eps = detectar_episodios(baja, min_episodio_min, max_episodio_min)
    log("")
    log(f"  Episodios de piscina < {umbral_pct}% durante >= {min_episodio_min} min: "
        f"{len(todos)} en total, {len(todos)-len(eps)} excluidos por durar mas de "
        f"{max_episodio_min} min -> {len(eps)} usados")
    if eps.empty:
        log("  Sin episodios: no hay perfil.")
        return None
    log(f"  duracion: mediana={eps.duracion_min.median():.0f} min  "
        f"p90={eps.duracion_min.quantile(.9):.0f}  max={eps.duracion_min.max():.0f}")

    # t0 = primer minuto bajo el umbral (inicio del episodio), no el fin:
    # la pregunta es que hace el operador CUANDO la piscina se pone baja.
    perfil, n_min = perfil_desde_t0(df, eps["inicio"], cols, ventana_min, bin_min)
    log(f"\n  Perfil desde que la piscina cruza bajo {umbral_pct}% (t=0), "
        f"{ventana_min} min, bins de {bin_min} min (>= {n_min} puntos por bin):")
    log(f"  {'minuto':>7s}" + "".join(f"{c[-18:]:>20s}" for c in cols))
    log(f"  {'sana':>7s}" + "".join(f"{base[c]:20.2f}" for c in cols))
    for m, row in perfil.iterrows():
        log(f"  {m:7d}" + "".join(f"{row.get(c, float('nan')):20.2f}" for c in cols))

    carpeta = os.path.join("data", "01_interim")
    os.makedirs(carpeta, exist_ok=True)
    base_nombre = f"piscina_baja_{espesador.replace('-', '')}"
    perfil.to_csv(os.path.join(carpeta, base_nombre + "_perfil.csv"))
    eps.to_csv(os.path.join(carpeta, base_nombre + "_episodios.csv"), index=False)
    pd.DataFrame({"sana": base, "baja": durante}).to_csv(os.path.join(carpeta, base_nombre + "_base.csv"))
    log(f"\n  [OK] {carpeta}/{base_nombre}_perfil.csv / _episodios.csv / _base.csv")
    return {"perfil": perfil, "episodios": eps, "base": base, "durante": durante}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--espesador", default="TH-001", choices=list(ESPESADORES.keys()))
    ap.add_argument("--ventana-min", type=int, default=120)
    ap.add_argument("--bin-min", type=int, default=10)
    ap.add_argument("--umbral-pct", type=float, default=None,
                    help="por defecto reglas_operativas.yaml::piscinas.nivel_minimo_pct")
    ap.add_argument("--min-episodio-min", type=int, default=None)
    ap.add_argument("--max-episodio-min", type=int, default=720)
    args = ap.parse_args()
    analizar(args.espesador, args.ventana_min, args.bin_min, args.umbral_pct,
             args.min_episodio_min, args.max_episodio_min)


if __name__ == "__main__":
    main()
