"""
regimenes_mineral.py — sensor latente de tipo de mineral.

EL PROBLEMA:
    El tipo de mineral es el disparador principal de los cambios de parámetros
    (dato del operador), y NO está en el historian. Eso significa que:
      - la "ventana óptima única" es un promedio sobre minerales distintos;
      - el operador actúa como sensor de mineral, reaccionando a algo invisible
        para los datos -> por eso las correlaciones salen con el signo cambiado.

LA SOLUCIÓN:
    El mineral cambia la REOLOGÍA de la cama, y eso deja firma en los tags que
    sí existen. Cuatro razones lo capturan:

      idx_reologia   = y3 / y1        torque por unidad de masa de cama
                                      -> yield stress. Alto = arcillas.
      demanda_floc   = x8 / t_solidos dosis específica
                                      -> superficie específica. Alto = finos.
      compactacion   = (rho-1) / y1   densidad ganada por unidad de cama
                                      -> sedimentabilidad.
      esponjosidad   = y2 / y1        altura por unidad de masa
                                      -> qué tan suelta queda la cama.

    Clustering sobre estas cuatro -> regímenes de mineral latentes.
    Después: una ventana operativa POR RÉGIMEN, no una sola.

SESGO DE INSTRUMENTO:
    DIT-144 (línea A) derivó ~+0.030 t/m3 desde may-2025 y los densímetros no se
    recalibran seguido. `compactacion` depende de rho, así que las features se
    ESTANDARIZAN DENTRO de (segmento x línea) antes de agrupar. Eso neutraliza
    cualquier offset constante del transmisor: el cluster captura la forma del
    proceso, no el cero del instrumento.
"""

import sys
import numpy as np
import pandas as pd

from io_espesador import cargar_datos

SPEED_ON = 5.0
RHO_MIN, RHO_MAX = 1.30, 1.90
RHO_SOLIDO = 2.75
CW_FEED = 0.2993
CORTE = "2025-05-31"          # deriva de DIT-144

FEATURES = ["idx_reologia", "demanda_floc", "compactacion", "esponjosidad"]


# ----------------------------------------------------------------------------

def preparar(d):
    a, b = d["x1"] > SPEED_ON, d["x4"] > SPEED_ON
    d = d.copy()
    d["linea"] = np.select([a & ~b, b & ~a], ["A", "B"], default="OTRO")
    d["rho_uf"] = np.select(
        [d["linea"] == "A", d["linea"] == "B"], [d["y4"], d["y5"]], default=np.nan
    )
    d["vel_uf"] = np.select(
        [d["linea"] == "A", d["linea"] == "B"], [d["x1"], d["x4"]], default=np.nan
    )
    d.loc[~d["rho_uf"].between(RHO_MIN, RHO_MAX), "rho_uf"] = np.nan

    rho_feed = 1 / (CW_FEED / RHO_SOLIDO + (1 - CW_FEED))
    d["solidos_tph"] = d["x6"] * rho_feed * CW_FEED

    cw = RHO_SOLIDO * (d["rho_uf"] - 1) / (d["rho_uf"] * (RHO_SOLIDO - 1))
    d["agua_por_t"] = (1 - cw) / cw        # objetivo: MINIMIZAR

    d["segmento"] = np.where(d.index < pd.Timestamp(CORTE), "S1", "S2")

    ok = (
        (d["x6"] > 400) & (d["x5"] > 20) & (d["y3"] > 15) & (d["y1"] > 30)
        & (d["x8"] > 0.05) & d["rho_uf"].notna() & d["linea"].isin(["A", "B"])
    )
    return d.loc[ok]


def construir_indices(d, ventana_min=30):
    """Los índices se calculan sobre señales suavizadas: la reología es una
    propiedad del lecho, no del minuto. EWMA (no media móvil) para no meter
    el lag de ventana completa.
    """
    d = d.copy()
    s = lambda c: d[c].ewm(span=ventana_min, adjust=False).mean()

    y1, y2, y3 = s("y1"), s("y2"), s("y3")
    rho, x8, sol = s("rho_uf"), s("x8"), s("solidos_tph")

    d["idx_reologia"] = y3 / y1
    d["demanda_floc"] = x8 / sol.clip(lower=50)
    d["compactacion"] = (rho - 1) / y1
    d["esponjosidad"] = y2 / y1

    return d.replace([np.inf, -np.inf], np.nan).dropna(subset=FEATURES)


def estandarizar_por_celda(d):
    """CRÍTICO: estandarizar dentro de (segmento x línea).

    Sin esto, el cluster separaría por INSTRUMENTO (el offset de DIT-144) en
    lugar de por MINERAL. Con esto, un offset constante del transmisor se
    cancela en la resta de la media y el cluster ve la forma del proceso.
    """
    z = d.copy()
    for f in FEATURES:
        g = z.groupby(["segmento", "linea"])[f]
        z[f + "_z"] = (z[f] - g.transform("mean")) / g.transform("std")
    return z.dropna(subset=[f + "_z" for f in FEATURES])


def agrupar(d, k_range=(2, 7), muestra=60000, semilla=42):
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score

    cols = [f + "_z" for f in FEATURES]
    X = d[cols].to_numpy()

    rng = np.random.default_rng(semilla)
    idx = rng.choice(len(X), size=min(muestra, len(X)), replace=False)
    Xs = X[idx]

    print("  k   silhouette   inercia")
    mejor_k, mejor_s = None, -1
    for k in range(*k_range):
        km = KMeans(n_clusters=k, n_init=10, random_state=semilla).fit(Xs)
        sil = silhouette_score(Xs, km.labels_, sample_size=20000, random_state=semilla)
        print(f"  {k}   {sil:9.3f}   {km.inertia_:10.0f}")
        if sil > mejor_s:
            mejor_k, mejor_s = k, sil

    print(f"\n  k elegido por silueta: {mejor_k}")
    km = KMeans(n_clusters=mejor_k, n_init=10, random_state=semilla).fit(X)
    d = d.copy()
    d["regimen"] = [f"R{c+1}" for c in km.labels_]
    return d, mejor_k


# ----------------------------------------------------------------------------

def perfilar_regimenes(d):
    """Qué distingue físicamente a cada régimen. Aquí es donde reconoces
    (o no) tus tipos de mineral.
    """
    p = d.groupby("regimen").agg(
        horas=("y1", lambda x: len(x) / 60),
        pct=("y1", lambda x: 100 * len(x) / len(d)),
        reologia=("idx_reologia", "median"),
        demanda_floc=("demanda_floc", "median"),
        compactacion=("compactacion", "median"),
        esponjosidad=("esponjosidad", "median"),
        feed=("x6", "median"),
        bedmass=("y1", "median"),
        torque=("y3", "median"),
        floc=("x8", "median"),
        agua_por_t=("agua_por_t", "median"),
    ).round(4)
    return p.sort_values("reologia")


def ventana_por_regimen(d, segmento="S2", linea="A"):
    """LA ENTREGA: la ventana óptima de BedMass para CADA régimen de mineral.

    Se compara dentro de (segmento x línea) para que el sesgo del densímetro no
    contamine. El objetivo es MINIMIZAR agua_por_t.
    """
    s = d[(d["segmento"] == segmento) & (d["linea"] == linea)].copy()
    s["bin_bm"] = pd.cut(s["y1"], [40, 48, 52, 56, 60, 64, 70])

    t = s.pivot_table(
        index="bin_bm", columns="regimen",
        values="agua_por_t", aggfunc=["median", "size"], observed=True,
    )
    return t.round(4)


def optimo_por_regimen(d, segmento="S2", linea="A", n_min=1000):
    s = d[(d["segmento"] == segmento) & (d["linea"] == linea)].copy()
    s["bin_bm"] = pd.cut(s["y1"], [40, 48, 52, 56, 60, 64, 70])

    filas = []
    for reg, sub in s.groupby("regimen"):
        g = sub.groupby("bin_bm", observed=True).agg(
            agua=("agua_por_t", "median"), n=("agua_por_t", "size"),
            torque=("y3", "median"), floc=("x8", "median"),
        )
        g = g[g["n"] >= n_min]
        if g.empty:
            continue
        mejor = g["agua"].idxmin()
        filas.append({
            "regimen": reg,
            "horas": round(len(sub) / 60),
            "BedMass_optimo": str(mejor),
            "agua_en_optimo": round(g.loc[mejor, "agua"], 4),
            "agua_mediana_actual": round(sub["agua_por_t"].median(), 4),
            "torque_en_optimo": round(g.loc[mejor, "torque"], 1),
            "floc_en_optimo": round(g.loc[mejor, "floc"], 3),
            "ganancia_m3_por_t": round(sub["agua_por_t"].median() - g.loc[mejor, "agua"], 4),
        })
    r = pd.DataFrame(filas)
    if not r.empty:
        sol = s["solidos_tph"].mean()
        r["ganancia_m3h_3esp"] = (3 * sol * r["ganancia_m3_por_t"]).round(1)
    return r


# ----------------------------------------------------------------------------

def sec(t):
    print("\n" + "=" * 72 + f"\n{t}\n" + "=" * 72)


def main(path):
    df, _ = cargar_datos(path)
    d = construir_indices(preparar(df))
    d = estandarizar_por_celda(d)

    print(f"\n  muestras utilizables: {len(d):,} ({len(d)/60:.0f} h)")

    sec("SELECCION DE k")
    d, k = agrupar(d)

    sec("PERFIL DE LOS REGIMENES  (ordenados por indice reologico)")
    print(perfilar_regimenes(d).to_string())
    print("\n  reologia alta + demanda_floc alta + compactacion baja")
    print("    => mineral arcilloso / fino: cuesta espesar")
    print("  reologia baja + compactacion alta")
    print("    => mineral limpio: sedimenta solo")
    print("\n  CONTRASTA ESTO CON EL PLAN DE MEZCLA / DOMINIOS GEOMETALURGICOS.")
    print("  Si los clusters coinciden con tipos de mineral reales, el sensor")
    print("  latente esta validado y el resultado es defendible.")

    sec("AGUA POR TONELADA vs BEDMASS, POR REGIMEN  (segmento S2, linea A)")
    print("  (menor = mejor: menos agua arrastrada al underflow)")
    print(ventana_por_regimen(d).to_string())

    sec("VENTANA OPTIMA POR REGIMEN DE MINERAL")
    r = optimo_por_regimen(d)
    if r.empty:
        print("  Muestra insuficiente por celda. Bajar n_min o reducir k.")
    else:
        print(r.to_string(index=False))
        print(f"\n  GANANCIA TOTAL si cada regimen opera en SU optimo:")
        print(f"    {r['ganancia_m3h_3esp'].mean():.1f} m3/h promedio (3 espesadores)")
        print("\n  Si los BedMass optimos DIFIEREN entre regimenes, entonces una")
        print("  ventana fija esta dejando agua sobre la mesa, y el setpoint debe")
        print("  MOVERSE con el mineral. Ese es el controlador adaptativo.")
        print("\n  Si NO difieren, la ventana fija 52-56 es correcta y el mineral")
        print("  no cambia el optimo (solo cambia cuanto cuesta llegar). Tambien")
        print("  es un resultado, y simplifica la implementacion.")

    d.to_csv("dataset_con_regimen.csv")
    print("\n  -> dataset_con_regimen.csv  (para el analisis de guardias)")
    return d


if __name__ == "__main__":
    en_nb = "ipykernel" in sys.modules
    p = ("Data_Esp1_20260714_0921.csv"
         if en_nb or len(sys.argv) < 2 or sys.argv[1].startswith("-")
         else sys.argv[1])
    main(p)
