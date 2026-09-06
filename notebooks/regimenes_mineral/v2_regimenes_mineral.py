"""
regimenes_v2.py — detección de regímenes de mineral, hecha bien.

QUÉ ESTABA MAL EN v1 (KMeans sobre índices reológicos):

  FEATURES ENDÓGENAS. Los cuatro índices (y3/y1, x8/solidos, (rho-1)/y1, y2/y1)
  son razones entre variables que el OPERADOR manipula. Clusterizarlas agrupa
  la política del operador, no el material. Ningún algoritmo arregla eso.

  ALGORITMO SIN TIEMPO. KMeans asume i.i.d.: tira el orden temporal. Pero la
  autocorrelación del régimen vive 4 días (0.22 a 96 h). La estructura temporal
  ERA la señal.

  ASIGNACIÓN DURA. En la frontera la etiqueta parpadea minuto a minuto ->
  mediana de corrida 1.2 h contra media de 9.9 h. Artefacto, no proceso.

  CRITERIO GEOMÉTRICO. La silueta pregunta "¿son compactos y separados?".
  La pregunta correcta es "¿explican el objetivo, y persisten días?".

LO QUE HACE v2:

  1. ÍNDICE RESIDUAL DE SEDIMENTABILIDAD (exógeno por construcción)
     La dificultad del mineral = la parte del resultado que el operador NO pudo
     controlar. Se modela rho ~ f(BedMass, floc, feed, velocidad) dentro de cada
     (segmento x línea) y se toma el residuo.

     Cota inferior: si el operador sube BedMass cuando el mineral es duro, parte
     del efecto del mineral se absorbe en ese coeficiente. Si AUN ASÍ aparece
     estructura temporal, el mineral está ahí sin discusión.

     TEST DE VALIDEZ INTEGRADO:
       residuo con persistencia de días + ritmo semanal -> ES MINERAL
       residuo ~ ruido blanco                           -> era error de modelo

  2. HMM sobre el residuo. Modela la persistencia explícitamente; la matriz de
     transición da el dwell time; el parpadeo desaparece por diseño.

  3. CHANGE-POINT (PELT) como contraste. Supuestos distintos. Si coincide con el
     HMM, la evidencia es fuerte.

  4. EVALUACIÓN CORRECTA: ¿el régimen añade poder explicativo sobre agua_por_t
     por encima de las manipuladas? ¿Y persiste días?

Dependencias:
    pixi add scikit-learn statsmodels
    pixi add hmmlearn ruptures      # opcionales; el script degrada sin ellas
"""

import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

SPEED_ON = 5.0
RHO_MIN, RHO_MAX = 1.30, 1.90
RHO_SOLIDO = 2.75
CW_FEED = 0.2993
CORTE = "2025-05-31"          # deriva de DIT-144

# La causa opera en escala de días. Agrupar minutos es agrupar a la escala
# equivocada: se agrega a bloques antes de modelar.
FREQ = "15min"

MANIPULADAS = ["y1", "x8", "x6", "vel_uf", "y2"]


# ----------------------------------------------------------------------------

def preparar(path):
    from io_espesador import cargar_datos
    df, _ = cargar_datos(path)

    a, b = df["x1"] > SPEED_ON, df["x4"] > SPEED_ON
    d = df.copy()
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
    d["agua_por_t"] = (1 - cw) / cw

    d["segmento"] = np.where(d.index < pd.Timestamp(CORTE), "S1", "S2")
    d["celda"] = d["segmento"] + "-" + d["linea"]

    ok = (
        (d["x6"] > 400) & (d["x5"] > 20) & (d["y3"] > 15) & (d["y1"] > 30)
        & (d["x8"] > 0.05) & d["rho_uf"].notna() & d["linea"].isin(["A", "B"])
    )
    return d.loc[ok]


def agregar(d):
    """A bloques de 15 min. Reduce el ruido de transmisor y lleva el problema a
    una escala más cercana a la del fenómeno.
    """
    num = ["rho_uf", "vel_uf", "y1", "y2", "y3", "x5", "x6", "x8",
           "solidos_tph", "agua_por_t"]
    g = d.resample(FREQ)
    r = g[num].mean()
    r["celda"] = g["celda"].agg(lambda x: x.mode().iat[0] if len(x) else np.nan)
    return r.dropna(subset=["rho_uf", "celda"])


# ----------------------------------------------------------------------------
# 1. ÍNDICE RESIDUAL DE SEDIMENTABILIDAD
# ----------------------------------------------------------------------------

def indice_sedimentabilidad(d, span_h=4):
    """residuo = rho_observado - rho_predicho_por_las_acciones_del_operador

    Positivo -> el material espesó MEJOR de lo que las acciones explican
                = mineral fácil
    Negativo -> peor = mineral difícil

    Se ajusta DENTRO de cada (segmento x línea): así el offset de DIT-144 se
    absorbe en el intercepto y no contamina el residuo.
    """
    from sklearn.linear_model import HuberRegressor  # robusto a outliers
    from sklearn.preprocessing import StandardScaler, SplineTransformer
    from sklearn.pipeline import make_pipeline

    d = d.copy()
    d["resid"] = np.nan
    r2 = {}

    for celda, sub in d.groupby("celda"):
        if len(sub) < 500:
            continue
        X = sub[MANIPULADAS].to_numpy()
        y = sub["rho_uf"].to_numpy()

        # splines: la relación BedMass->densidad es no lineal (tiene codo)
        mod = make_pipeline(
            StandardScaler(),
            SplineTransformer(n_knots=5, degree=3),
            HuberRegressor(max_iter=500),
        ).fit(X, y)

        pred = mod.predict(X)
        d.loc[sub.index, "resid"] = y - pred
        ss_res = np.sum((y - pred) ** 2)
        ss_tot = np.sum((y - y.mean()) ** 2)
        r2[celda] = round(1 - ss_res / ss_tot, 3)

    # el mineral cambia en horas/días, no en minutos: suavizar
    span = int(span_h * 60 / int(pd.Timedelta(FREQ).total_seconds() / 60))
    d["idx_mineral"] = d["resid"].ewm(span=span, adjust=False).mean()
    return d.dropna(subset=["idx_mineral"]), r2


def validar_residuo(d):
    """EL TEST QUE DECIDE SI HAY ALGO QUE BUSCAR.

    Si el residuo es ruido blanco, era error de modelo y no hay mineral que
    detectar. Si tiene memoria de días y ritmo semanal, es una perturbación
    exógena lenta -> mineral.
    """
    s = d["idx_mineral"].resample("1h").mean()
    ac = {f"{h}h": round(s.autocorr(lag=h), 3) for h in [1, 6, 24, 48, 72, 96, 168]}

    sem = d.groupby(d.index.dayofweek)["idx_mineral"].mean()
    sem.index = ["Lun", "Mar", "Mie", "Jue", "Vie", "Sab", "Dom"]

    hora = d.groupby(d.index.hour)["idx_mineral"].mean()

    return {
        "autocorr": ac,
        "amplitud_semanal": round(float(sem.max() - sem.min()), 5),
        "amplitud_horaria": round(float(hora.max() - hora.min()), 5),
        "perfil_semanal": sem.round(5),
        "es_exogeno": ac["72h"] > 0.20,
    }


# ----------------------------------------------------------------------------
# 2. HMM — persistencia modelada explícitamente
# ----------------------------------------------------------------------------

def hmm_regimenes(d, n_estados=3, semilla=42):
    """A diferencia de KMeans, el HMM tiene matriz de transición: cambiar de
    estado CUESTA. El parpadeo desaparece por diseño, y el dwell time esperado
    sale directo de la diagonal:  E[duracion] = 1 / (1 - p_ii)
    """
    try:
        from hmmlearn.hmm import GaussianHMM
    except ImportError:
        print("  hmmlearn no instalado:  pixi add hmmlearn")
        return None, None

    X = d[["idx_mineral"]].to_numpy()
    X = (X - X.mean()) / X.std()

    mod = GaussianHMM(
        n_components=n_estados, covariance_type="diag",
        n_iter=200, random_state=semilla,
    ).fit(X)

    d = d.copy()
    d["hmm"] = [f"M{s+1}" for s in mod.predict(X)]

    paso_h = pd.Timedelta(FREQ).total_seconds() / 3600
    diag = np.diag(mod.transmat_)
    dwell = pd.DataFrame({
        "estado": [f"M{i+1}" for i in range(n_estados)],
        "media_idx": mod.means_.ravel().round(3),
        "p_permanencia": diag.round(4),
        "dwell_esperado_h": (paso_h / (1 - diag)).round(1),
        "pct_tiempo": [round(100 * (d["hmm"] == f"M{i+1}").mean(), 1)
                       for i in range(n_estados)],
    }).sort_values("media_idx")

    return d, dwell


def seleccionar_n_estados(d, rango=(2, 6), semilla=42):
    """BIC. Y además: un estado con dwell < 6 h no es un mineral, sea cual sea
    su BIC. Se reporta para poder descartarlo.
    """
    try:
        from hmmlearn.hmm import GaussianHMM
    except ImportError:
        return None

    X = d[["idx_mineral"]].to_numpy()
    X = (X - X.mean()) / X.std()
    paso_h = pd.Timedelta(FREQ).total_seconds() / 3600

    filas = []
    for k in range(*rango):
        m = GaussianHMM(n_components=k, covariance_type="diag",
                        n_iter=200, random_state=semilla).fit(X)
        diag = np.diag(m.transmat_)
        filas.append({
            "n_estados": k,
            "BIC": round(m.bic(X)),
            "dwell_min_h": round(float((paso_h / (1 - diag)).min()), 1),
        })
    return pd.DataFrame(filas)


# ----------------------------------------------------------------------------
# 3. CHANGE-POINT — contraste con supuestos distintos
# ----------------------------------------------------------------------------

def changepoints(d, pen=None):
    """PELT segmenta la SERIE, no la nube de puntos. Si sus fronteras coinciden
    con las transiciones del HMM, dos métodos con supuestos opuestos están de
    acuerdo, y eso es evidencia fuerte.
    """
    try:
        import ruptures as rpt
    except ImportError:
        print("  ruptures no instalado:  pixi add ruptures")
        return None

    s = d["idx_mineral"].resample("6h").mean().dropna()
    y = ((s - s.mean()) / s.std()).to_numpy().reshape(-1, 1)

    algo = rpt.Pelt(model="rbf", min_size=4).fit(y)   # min 24 h por segmento
    bkps = algo.predict(pen=pen or 3 * np.log(len(y)))

    fechas = [s.index[b - 1] for b in bkps[:-1]]
    dur = np.diff([0] + bkps) * 6                      # horas
    return {
        "n_segmentos": len(bkps),
        "duracion_mediana_h": round(float(np.median(dur)), 1),
        "duracion_media_h": round(float(np.mean(dur)), 1),
        "primeras_fechas": [str(f.date()) for f in fechas[:12]],
    }


# ----------------------------------------------------------------------------
# 4. EVALUACIÓN — el criterio correcto
# ----------------------------------------------------------------------------

def evaluar(d, etiqueta="hmm"):
    """La silueta es un criterio GEOMÉTRICO: pregunta si los clusters son
    compactos. Pregunta equivocada.

    Las dos preguntas correctas:
      (a) ¿el régimen añade poder explicativo sobre agua_por_t POR ENCIMA de lo
          que ya explican las manipuladas?   -> R2 incremental
      (b) ¿persiste en escala de días?       -> si no, no es un mineral
    """
    from sklearn.linear_model import LinearRegression

    s = d.dropna(subset=["agua_por_t", etiqueta])
    y = s["agua_por_t"].to_numpy()

    X0 = pd.get_dummies(s["celda"], drop_first=True)
    X0 = pd.concat([s[MANIPULADAS], X0], axis=1).to_numpy(dtype=float)
    r2_base = LinearRegression().fit(X0, y).score(X0, y)

    X1 = np.hstack([X0, pd.get_dummies(s[etiqueta], drop_first=True).to_numpy(dtype=float)])
    r2_full = LinearRegression().fit(X1, y).score(X1, y)

    # persistencia real de las etiquetas
    lab = s[etiqueta]
    hueco = s.index.to_series().diff() > pd.Timedelta(FREQ) * 2
    grupo = ((lab != lab.shift()) | hueco).cumsum()
    paso_h = pd.Timedelta(FREQ).total_seconds() / 3600
    dur = lab.groupby(grupo).size() * paso_h

    return {
        "R2_solo_manipuladas": round(r2_base, 4),
        "R2_con_regimen": round(r2_full, 4),
        "ganancia_incremental": round(r2_full - r2_base, 4),
        "duracion_mediana_h": round(float(dur.median()), 1),
        "duracion_p90_h": round(float(dur.quantile(0.90)), 1),
    }


# ----------------------------------------------------------------------------

def sec(t):
    print("\n" + "=" * 72 + f"\n{t}\n" + "=" * 72)


def main(path="Data_Esp1_20260714_0921.csv"):
    d = agregar(preparar(path))
    print(f"\n  bloques de {FREQ}: {len(d):,}")

    sec("1. INDICE RESIDUAL DE SEDIMENTABILIDAD")
    print("  residuo = rho observado - rho explicado por las acciones del operador")
    d, r2 = indice_sedimentabilidad(d)
    print(f"\n  R2 del modelo de acciones, por celda: {r2}")
    print("  (R2 alto = las acciones explican casi todo -> poco residuo que analizar)")

    sec("   TEST: ¿el residuo es mineral, o es error de modelo?")
    v = validar_residuo(d)
    print("  Autocorrelacion del indice:")
    for k, val in v["autocorr"].items():
        print(f"    {k:>5}: {val:+.3f}")
    print(f"\n  amplitud semanal : {v['amplitud_semanal']}")
    print(f"  amplitud horaria : {v['amplitud_horaria']}")
    print("\n  Perfil semanal:")
    print(v["perfil_semanal"].to_string())

    if v["es_exogeno"]:
        print("\n  -> MEMORIA DE DIAS. El residuo NO es ruido de modelo.")
        print("     Hay una perturbacion exogena lenta. Compatible con MINERAL.")
        if v["amplitud_semanal"] > 2 * v["amplitud_horaria"]:
            print("     Y el ritmo SEMANAL domina al horario -> plan de mina,")
            print("     no rol de turnos.")
    else:
        print("\n  -> El residuo se parece a ruido blanco.")
        print("     Era error de modelo. No hay señal de mineral que rescatar")
        print("     con estos tags. Se necesita P80 / Courier.")
        return d

    sec("2. HMM — cuantos regimenes, y cuanto duran")
    sel = seleccionar_n_estados(d)
    if sel is not None:
        print(sel.to_string(index=False))
        print("\n  Un estado con dwell < 6 h NO es un mineral, tenga el BIC que tenga.")

    d, dwell = hmm_regimenes(d, n_estados=3)
    if dwell is not None:
        print()
        print(dwell.to_string(index=False))
        print("\n  dwell = 1/(1-p_ii). KMeans no puede darte esto: no tiene")
        print("  matriz de transicion, y por eso producia el parpadeo.")

    sec("3. CHANGE-POINT (PELT) — contraste con supuestos distintos")
    cp = changepoints(d)
    if cp:
        for k, val in cp.items():
            print(f"  {k}: {val}")
        print("\n  Si la duracion mediana de PELT coincide con el dwell del HMM,")
        print("  dos metodos con supuestos opuestos concuerdan. Evidencia fuerte.")

    if "hmm" in d.columns:
        sec("4. EVALUACION — el criterio correcto (no la silueta)")
        for k, val in evaluar(d).items():
            print(f"  {k}: {val}")
        print("\n  ganancia_incremental > 0.02  -> el regimen aporta informacion")
        print("                                   que las manipuladas no tienen")
        print("  duracion_mediana_h    > 12   -> persiste como un mineral, no")
        print("                                   como una decision de turno")

        sec("VENTANA OPTIMA POR REGIMEN DE MINERAL (segmento S2, linea A)")
        s = d[d["celda"] == "S2-A"].copy()
        s["bin_bm"] = pd.cut(s["y1"], [40, 48, 52, 56, 60, 64, 70])
        t = s.pivot_table(index="bin_bm", columns="hmm", values="agua_por_t",
                          aggfunc=["median", "size"], observed=True)
        print(t.round(4).to_string())
        print("\n  (menor = mejor). Si el BedMass optimo DIFIERE entre regimenes,")
        print("  el setpoint debe moverse con el mineral.")

    d.to_csv("dataset_regimenes_v2.csv")
    print("\n  -> dataset_regimenes_v2.csv")
    return d


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "Data_Esp1_20260714_0921.csv")
