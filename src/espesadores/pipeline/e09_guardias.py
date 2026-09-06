# -*- coding: utf-8 -*-
"""E09 - Efecto de las guardias."""
import os
import re

import numpy as np
import pandas as pd

from espesadores.config import RUTAS, TURNOS
from .comun import log, titulo, guardar, eta2


def e09_guardias(df, cfg, ctx):
    """
    Mide si la identidad de la guardia explica los setpoints, comparándola
    contra el tipo de mineral en igualdad de condiciones.

    SUSTENTO METODOLOGICO: comparar el efecto de "día calendario" contra el
    de "mineral" es tramposo, porque un factor con cientos de niveles
    explica mucha varianza por puro número de grados de libertad, y además
    los días son bloques contiguos, así que capturan la autocorrelación de
    las señales. En TH-001 se comprobó que trocear la línea de tiempo en
    bloques ARBITRARIOS del mismo largo explicaba lo mismo que los días
    reales (0.756 vs 0.762).

    Por eso aquí se usa el ROL REAL de guardias y un nulo por
    DESPLAZAMIENTO CIRCULAR: se corre el rol k posiciones, lo que preserva
    la rotación y la autocorrelación del proceso pero rompe la alineación
    verdadera. Si el efecto real no supera a ese nulo, no hay huella de
    guardia.
    """
    titulo("E09 - EFECTO DE LAS GUARDIAS")

    MESES = {"ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4, "MAYO": 5, "JUNIO": 6,
             "JULIO": 7, "AGOSTO": 8, "SETIEMBRE": 9, "SEPTIEMBRE": 9, "OCTUBRE": 10,
             "NOVIEMBRE": 11, "DICIEMBRE": 12}
    registros = []
    for archivo in RUTAS["roles_guardia"]:
        if not os.path.exists(archivo):
            continue
        mes = anio = None
        for linea in open(archivo, encoding="utf-8").read().split("\n"):
            m = re.match(r"##\s+([A-ZÑ]+)\s+(\d{4})", linea.strip())
            if m and m.group(1) in MESES:
                mes, anio = MESES[m.group(1)], int(m.group(2))
                continue
            g = re.match(r"\|\s*\*\*Guardia\s+(\d+)\*\*\s*\|(.+)", linea.strip())
            if g and mes:
                num = int(g.group(1))
                codigos = [c.strip() for c in g.group(2).split("|") if c.strip()]
                for dia, cod in enumerate(codigos, start=1):
                    if cod in (TURNOS["codigo_dia"], TURNOS["codigo_noche"],
                               TURNOS["codigo_descanso"]):
                        try:
                            registros.append((pd.Timestamp(anio, mes, dia), num, cod))
                        except ValueError:
                            pass
    if not registros:
        log("  No se encontro el rol de guardias: se omite esta etapa.")
        ctx["guardias_ok"] = False
        return df

    R = pd.DataFrame(registros, columns=["fecha", "guardia", "cod"]).drop_duplicates()
    log(f"  Rol leido: {len(R):,} registros, {R.guardia.nunique()} guardias, "
        f"{R.fecha.min().date()} a {R.fecha.max().date()}")

    hora_dec = df.index.hour + df.index.minute / 60
    ini = TURNOS["inicio_dia_h"]
    fin = ini + TURNOS["duracion_h"]
    es_dia = (hora_dec >= ini) & (hora_dec < fin)
    fecha_turno = pd.Series(df.index.normalize(), index=df.index)
    fecha_turno[hora_dec < ini] = df.index[hora_dec < ini].normalize() - pd.Timedelta(days=1)
    df["cod_turno"] = np.where(es_dia, TURNOS["codigo_dia"], TURNOS["codigo_noche"])
    df["bloque"] = fecha_turno.dt.strftime("%Y-%m-%d") + "_" + df["cod_turno"]

    activas = R[R.cod != TURNOS["codigo_descanso"]]
    par = (activas.groupby(["fecha", "cod"])["guardia"]
           .apply(lambda s: "+".join(map(str, sorted(s)))).rename("par").reset_index())
    par["bloque"] = par["fecha"].dt.strftime("%Y-%m-%d") + "_" + par["cod"]
    df["par_guardia"] = df["bloque"].map(dict(zip(par.bloque, par.par)))
    log(f"  Bloques de turno cruzados: {df['par_guardia'].notna().sum():,} filas")

    setpoints = [cfg["floculante"], cfg["valvula_alim"], cfg["nivel_interfaz"],
                 "vel_descarga", "vel_cizalle"]
    setpoints = [c for c in setpoints if c in df.columns]
    B = (df.dropna(subset=["par_guardia"])
           .groupby("bloque")
           .agg({**{c: "median" for c in setpoints},
                 "wt_activo": "median", "recuperacion": "median",
                 "par_guardia": "first", "mineral": lambda s: s.mode().iloc[0]
                 if len(s.mode()) else -1})
           .dropna(subset=["par_guardia"]))
    log(f"  Bloques agregados: {len(B):,}")

    log("")
    log(f"  {'setpoint':20s} {'efecto real':>12s} {'nulo medio':>11s} {'p-valor':>9s}")
    rng = np.random.default_rng(0)
    filas = []
    for col in setpoints:
        real = eta2(B, col, "par_guardia")
        nulos = []
        for _ in range(200):
            Bn = B.copy()
            k = int(rng.integers(20, max(21, len(B) - 20)))
            Bn["par_guardia"] = np.roll(B["par_guardia"].values, k)
            nulos.append(eta2(Bn, col, "par_guardia"))
        nulos = np.array([x for x in nulos if not np.isnan(x)])
        p = float((nulos >= real).mean()) if len(nulos) else np.nan
        sig = "SI" if p < 0.05 else "no"
        filas.append({"setpoint": col, "eta2_real": round(real, 4),
                      "eta2_nulo": round(float(nulos.mean()), 4),
                      "p_valor": round(p, 3), "significativo": sig})
        log(f"  {col:20s} {real:12.4f} {nulos.mean():11.4f} {p:9.3f}  {sig}")

    log("")
    log("  Comparacion sobre los mismos bloques (guardia vs mineral):")
    log(f"  {'setpoint':20s} {'guardia':>10s} {'mineral':>10s} {'quien pesa mas':>16s}")
    comp = []
    Bm = B[B["mineral"] >= 0]
    for col in setpoints:
        eg = eta2(Bm, col, "par_guardia")
        em = eta2(Bm, col, "mineral")
        quien = ("mineral" if em > eg * 1.5 else "guardia" if eg > em * 1.5 else "similar")
        comp.append({"setpoint": col, "eta2_guardia": round(eg, 4),
                     "eta2_mineral": round(em, 4), "domina": quien})
        log(f"  {col:20s} {eg:10.4f} {em:10.4f} {quien:>16s}")

    guardar(pd.DataFrame(filas).set_index("setpoint"), "E09a_guardias_vs_nulo.csv", ctx["salidas"])
    guardar(pd.DataFrame(comp).set_index("setpoint"), "E09b_guardia_vs_mineral.csv", ctx["salidas"])

    desemp = (B.groupby("par_guardia")
                .agg(bloques=("wt_activo", "size"), wt=("wt_activo", "mean"),
                     recuperacion=("recuperacion", "mean"))
                .sort_values("wt", ascending=False).round(3))
    guardar(desemp, "E09c_desempeno_por_guardia.csv", ctx["salidas"])
    ctx["guardias_ok"] = True
    ctx["rango_guardias"] = float(desemp.wt.max() - desemp.wt.min())
    log(f"  Rango entre guardias: {ctx['rango_guardias']:.2f} puntos de %solidos "
        f"({ctx['sensibilidad']*ctx['rango_guardias']:.0f} m3/h)")
    return df
