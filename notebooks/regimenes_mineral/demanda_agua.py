"""
demanda_agua.py — el análisis que faltaba.

PREMISA QUE NUNCA SE VERIFICÓ:
    Todo el trabajo asumió que recuperar más agua siempre vale. Pero el operador
    opera contra el NIVEL DEL TANQUE de agua recuperada (y7/y8), no contra la
    densidad. Y si el tanque está lleno, el agua recuperada de más NO TIENE
    DÓNDE IR: su valor marginal es CERO.

    Además: los TRES espesadores descargan al MISMO tanque. Están acoplados.
    Optimizar TH-001 en aislamiento puede no producir agua adicional -- solo
    desplazar carga entre equipos.

LAS CUATRO PREGUNTAS:
    1. ¿Cuánto tiempo el sistema está saturado de agua? (= ganancia sin valor)
    2. ¿El operador realmente responde al nivel del tanque? (= su función objetivo)
    3. ¿La ganancia de BedMass sobrevive cuando SÍ hay demanda?
    4. ¿Cuál es la ganancia REAL, ponderada por el valor del agua?

CADENA DEL SISTEMA:
    Espesadores (rebose) -> DB-001 -> TK-001/002 (y7,y8) -> bombas -> Piscinas
    (x9,x10) -> planta.  El buffer total es tanques + piscinas.
"""

import sys
import numpy as np
import pandas as pd
import statsmodels.api as sm

RHO_SOLIDO, CW_FEED = 2.75, 0.2993


def cargar(path="dataset_regimenes_v2.csv", raw="Data_Esp1_20260714_0921.csv"):
    """El dataset de regímenes perdió y7/y8/x9/x10: hay que reponerlos."""
    d = pd.read_csv(path, index_col=0, parse_dates=True)
    from io_espesador import cargar_datos
    r, _ = cargar_datos(raw, verbose=False)
    niveles = r[["y7", "y8", "x9", "x10", "y6"]].resample("15min").mean()
    return d.join(niveles, how="left").dropna(subset=["y7", "y8"])


def sec(t):
    print("\n" + "=" * 72 + f"\n{t}\n" + "=" * 72)


# ----------------------------------------------------------------------------
# 1. ¿Cuánto tiempo el agua NO vale nada?
# ----------------------------------------------------------------------------

def saturacion(d):
    """Si tanques y piscinas están altos, el sistema está saturado: el agua
    recuperada adicional no tiene destino. Su valor marginal es cero.
    """
    d = d.copy()
    d["tanque"] = d[["y7", "y8"]].mean(axis=1)

    # x9 estuvo muerto (negativo) en tramos: usar x10 si x9 no es fiable
    x9_ok = d["x9"].between(0, 100)
    d["piscina"] = np.where(x9_ok, d[["x9", "x10"]].mean(axis=1), d["x10"])

    q = d["tanque"].quantile([.10, .25, .50, .75, .90]).round(1)
    print("  Nivel de tanque (y7,y8) — percentiles:")
    print(q.to_string())
    print(f"\n  Piscinas — mediana: {d['piscina'].median():.1f} %  "
          f"p90: {d['piscina'].quantile(.90):.1f} %")

    d["demanda"] = pd.cut(
        d["tanque"], [0, 45, 55, 65, 100],
        labels=["ESCASEZ", "NORMAL", "HOLGADO", "SATURADO"],
    )
    t = d.groupby("demanda", observed=True).agg(
        pct_tiempo=("tanque", lambda x: round(100 * len(x) / len(d), 1)),
        tanque=("tanque", "mean"),
        piscina=("piscina", "mean"),
        bedmass=("y1", "mean"),
        torque=("y3", "mean"),
        agua_por_t=("agua_por_t", "mean"),
        floc=("x8", "mean"),
        flujo_piscinas=("y6", "mean"),
    ).round(3)
    return d, t


# ----------------------------------------------------------------------------
# 2. ¿El operador responde al nivel del tanque?
# ----------------------------------------------------------------------------

def responde_al_tanque(d):
    """Si la velocidad de la bomba U/F sigue al nivel del tanque con retardo,
    esa es su función objetivo -- y explica por qué las correlaciones directas
    salían con el signo invertido: estaba optimizando OTRA COSA.
    """
    r = d[["tanque", "vel_uf", "y1", "x8", "agua_por_t"]].resample("1h").mean().dropna()
    dr = r.diff().dropna()

    print("  d(nivel tanque)[t-lag]  ->  d(accion)[t]")
    print("  lag_h    vel_uf    BedMass    floc")
    for lag in [0, 1, 2, 3, 6, 12, 24]:
        print(f"  {lag:5d}   {dr['tanque'].shift(lag).corr(dr['vel_uf']):+.3f}    "
              f"{dr['tanque'].shift(lag).corr(dr['y1']):+.3f}     "
              f"{dr['tanque'].shift(lag).corr(dr['x8']):+.3f}")

    print("\n  Signo esperado si opera contra el tanque:")
    print("    tanque SUBE -> no necesita agua -> ACELERA bomba (vel_uf +),")
    print("    baja cama (BedMass -). Es decir: corr(tanque, vel_uf) POSITIVA.")


# ----------------------------------------------------------------------------
# 3. ¿La ganancia sobrevive cuando SÍ hay demanda?
# ----------------------------------------------------------------------------

def ganancia_por_demanda(d):
    """Estimador within (efecto fijo por ventana de 12 h) DENTRO de cada estado
    de demanda. Si el coeficiente de BedMass solo es fuerte en ESCASEZ, la
    ganancia es real pero solo cobrable en ese estado.
    """
    s = d[d["celda"] == "S2-A"].copy()
    s["win"] = s.index.floor("12h")
    s = s.groupby("win").filter(lambda g: len(g) >= 24 and g["y1"].std() > 1.0)

    for c in ["agua_por_t", "y1", "x8", "x6", "vel_uf", "y3"]:
        s[c + "_w"] = s[c] - s.groupby("win")[c].transform("mean")

    print("  estado_demanda | d(agua)/d(cama) |    z   |    n  | ventanas")
    out = {}
    for est, g in s.groupby("demanda", observed=True):
        if len(g) < 400:
            continue
        X = sm.add_constant(g[["y1_w", "x8_w", "x6_w", "vel_uf_w"]])
        m = sm.OLS(g["agua_por_t_w"], X).fit(
            cov_type="cluster", cov_kwds={"groups": g["win"]}
        )
        b, z = m.params["y1_w"], m.tvalues["y1_w"]
        out[est] = b
        print(f"  {str(est):>14} | {b:+15.5f} | {z:+6.1f} | {len(g):5d} | "
              f"{g['win'].nunique():5d}")
    return out, s


# ----------------------------------------------------------------------------
# 4. Ganancia REAL, ponderada por el valor del agua
# ----------------------------------------------------------------------------

def ganancia_ponderada(d, coefs, n_espesadores=1):
    """El agua solo vale cuando el sistema NO está saturado.

    OJO: n_espesadores=1 por defecto. Solo analizamos TH-001. Multiplicar por 3
    supone que los otros dos están en el mismo estado mecánico, con los mismos
    instrumentos y el mismo margen -- NADA de eso está verificado. Y los tres
    descargan al MISMO tanque: si el tanque ya se llena, mejorar TH-001 no
    produce agua adicional.
    """
    sol = d["solidos_tph"].mean()
    print(f"  solidos medios TH-001: {sol:.0f} t/h")

    total = 0.0
    print("\n  estado      | %tiempo | beta_cama  | vale? | m3/h ponderado")
    for est in ["ESCASEZ", "NORMAL", "HOLGADO", "SATURADO"]:
        sub = d[d["demanda"] == est]
        if sub.empty:
            continue
        pct = len(sub) / len(d)
        b = coefs.get(est)
        # el agua saturada no vale: valor marginal cero
        vale = est in ("ESCASEZ", "NORMAL")
        if b is None or not vale:
            print(f"  {est:<11} | {100*pct:6.1f}% | "
                  f"{'n/d' if b is None else f'{b:+.5f}':>10} | "
                  f"{'SI' if vale else 'NO':>5} | 0.0")
            continue
        # subir 3.5 puntos de cama (de piso 50.5 a 54), tope conservador
        g = -b * 3.5 * sol * n_espesadores
        total += g * pct
        print(f"  {est:<11} | {100*pct:6.1f}% | {b:+10.5f} | {'SI':>5} | {g*pct:8.1f}")

    print(f"\n  GANANCIA REAL (TH-001, ponderada por valor): {total:.1f} m3/h")
    print(f"                                               {total*8760/1000:.0f} miles m3/año")
    print(f"\n  Sin ponderar por demanda habria dado ~{total*2.5:.0f} m3/h.")
    print("  La diferencia es agua que no tiene donde ir.")


# ----------------------------------------------------------------------------

def main(path="dataset_regimenes_v2.csv"):
    d = cargar(path)
    print(f"  bloques: {len(d):,}")

    sec("1. ¿CUANTO TIEMPO EL AGUA NO VALE NADA?")
    d, t = saturacion(d)
    print()
    print(t.to_string())
    sat = 100 * (d["demanda"] == "SATURADO").mean()
    print(f"\n  SATURADO: {sat:.1f} % del tiempo.")
    if sat > 25:
        print("  -> El cuello de botella NO es el espesador: es el ALMACENAMIENTO")
        print("     o el consumo de la planta. Optimizar densidad no produce agua")
        print("     util en ese estado.")

    sec("2. ¿EL OPERADOR OPERA CONTRA EL TANQUE?")
    responde_al_tanque(d)

    sec("3. ¿LA GANANCIA SOBREVIVE CUANDO HAY DEMANDA?")
    coefs, s = ganancia_por_demanda(d)
    print("\n  Si beta solo es fuerte en ESCASEZ/NORMAL, la ganancia es real pero")
    print("  solo cobrable ahi. Si es fuerte en SATURADO tambien, el operador")
    print("  esta dejando agua sobre la mesa incluso cuando no la necesita")
    print("  (= no hay perdida real, solo esta relajado, y hace bien).")

    sec("4. GANANCIA REAL, PONDERADA POR EL VALOR DEL AGUA")
    ganancia_ponderada(d, coefs)

    sec("LO QUE ESTE ANALISIS NO PUEDE VER")
    print("  - TH-002 y TH-003: no estan en el dataset. Los tres alimentan el")
    print("    MISMO tanque -> estan acoplados. Ningun x3 es defendible.")
    print("  - Consumo de agua de planta: sin el, no se sabe si la demanda es")
    print("    la restriccion real.")
    print("  - Rebose de piscinas / agua fresca de reposicion: si hay make-up,")
    print("    ESE es el costo que la recuperacion evita, y es el numero que")
    print("    de verdad importa para el caso de negocio.")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "dataset_regimenes_v2.csv")
