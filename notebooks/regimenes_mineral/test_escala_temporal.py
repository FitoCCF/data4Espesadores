"""
test_escala_temporal.py

PREGUNTA:
    El clustering separó dos regímenes (R1 = cama moderada + floculante bajo,
    R2 = cama alta + floculante alto). ¿Qué los dispara?

      - MINERAL   -> las campañas de mezcla duran DÍAS. El mineral no sabe
                     qué hora es: no habrá periodicidad de 12 h ni de 24 h.
      - OPERADOR  -> el turno dura 12 h y el rol rota cada N días. Dejará
                     firma horaria y periodicidad en el ciclo del rol.

    Las implicaciones son opuestas:
      - Si es MINERAL: R2 es compensación legítima. El setpoint debe adaptarse.
      - Si es OPERADOR: R2 es sobre-floculación autoinfligida. Hay que
        estandarizar la práctica, y ahí están los ~50 m3/h.

CUATRO PRUEBAS:
    1. Duración de las corridas
    2. Decaimiento de la autocorrelación
    3. Perfil por hora del día      <- la prueba decisiva
    4. Periodicidad en el ciclo del rol
"""

import sys
import numpy as np
import pandas as pd

GAP_MAX = pd.Timedelta("10min")   # el dataset tiene huecos (filtro de operación)


def cargar(path="dataset_con_regimen.csv"):
    d = pd.read_csv(path, index_col=0, parse_dates=True).sort_index()
    if "regimen" not in d.columns:
        raise KeyError("Falta la columna 'regimen'. Corre regimenes_mineral.py primero.")
    return d


# ----------------------------------------------------------------------------
# 1. Duración de las corridas
# ----------------------------------------------------------------------------

def corridas(d):
    """Una corrida = tramo continuo con el mismo régimen.

    OJO: el dataset tiene huecos (las paradas fueron filtradas). Dos filas
    contiguas NO son dos minutos contiguos. Hay que cortar la corrida también
    donde hay un salto temporal, o se pegan tramos que no son vecinos.
    """
    r = d["regimen"]
    hueco = d.index.to_series().diff() > GAP_MAX
    grupo = ((r != r.shift()) | hueco).cumsum()

    g = d.groupby(grupo)
    runs = pd.DataFrame({
        "regimen": g["regimen"].first(),
        "minutos": g.size(),
        "inicio": g.apply(lambda x: x.index[0]),
    })
    runs["horas"] = runs["minutos"] / 60
    return runs


# ----------------------------------------------------------------------------
# 2. Autocorrelación
# ----------------------------------------------------------------------------

def autocorrelacion(d, lags_h=(1, 3, 6, 12, 24, 48, 72, 96, 168, 336)):
    """Se resamplea a rejilla horaria regular: la autocorrelación sobre una
    serie con huecos no significa nada.

    Lectura:
      - viva a 24-72 h  -> el disparador cambia en escala de DÍAS = mineral
      - muerta a 12 h   -> cambia dentro del turno = operador
    """
    b = (d["regimen"] == "R2").astype(float).resample("1h").mean()
    filas = []
    for h in lags_h:
        filas.append({"lag_h": h, "autocorr": round(b.autocorr(lag=h), 3)})
    return pd.DataFrame(filas), b


# ----------------------------------------------------------------------------
# 3. Perfil horario  <-- LA PRUEBA DECISIVA
# ----------------------------------------------------------------------------

def perfil_horario(d):
    """El mineral no sabe qué hora es. Si la probabilidad de estar en R2 depende
    de la hora del día, el disparador es humano. Punto.
    """
    p = (d["regimen"] == "R2").groupby(d.index.hour).mean()
    p.index.name = "hora"

    # Test chi-cuadrado: ¿la hora del día es independiente del régimen?
    from scipy import stats
    tabla = pd.crosstab(d.index.hour, d["regimen"])
    chi2, pval, _, _ = stats.chi2_contingency(tabla)

    # amplitud: cuánto varía entre la hora más y menos R2
    amp = p.max() - p.min()
    return p.round(3), {"chi2": round(chi2, 1), "p": f"{pval:.2e}", "amplitud": round(amp, 3)}


def perfil_dia_semana(d):
    p = (d["regimen"] == "R2").groupby(d.index.dayofweek).mean()
    p.index = ["Lun", "Mar", "Mie", "Jue", "Vie", "Sab", "Dom"]
    return p.round(3)


# ----------------------------------------------------------------------------
# 4. Periodicidad (busca la firma del rol de turnos)
# ----------------------------------------------------------------------------

def periodicidad(b, periodos_h=(8, 12, 24, 48, 72, 96, 120, 168, 192)):
    """Compara la autocorrelación en cada período candidato contra sus vecinos.
    Un pico local en 12 h o 24 h = firma de turno.
    Un pico en 96 h (4 d) o 168 h (7 d) = firma del ciclo de rol.
    """
    filas = []
    for p in periodos_h:
        centro = b.autocorr(lag=p)
        vecinos = np.nanmean([b.autocorr(lag=p - 2), b.autocorr(lag=p + 2)])
        filas.append({
            "periodo_h": p,
            "autocorr": round(centro, 3),
            "vs_vecinos": round(centro - vecinos, 3),
            "pico": "SI" if (centro - vecinos) > 0.02 else "",
        })
    return pd.DataFrame(filas)


# ----------------------------------------------------------------------------

def sec(t):
    print("\n" + "=" * 72 + f"\n{t}\n" + "=" * 72)


def main(path="dataset_con_regimen.csv"):
    d = cargar(path)
    print(f"  muestras: {len(d):,}   rango: {d.index.min()} -> {d.index.max()}")

    # --- 1 ---
    sec("1. DURACION DE LAS CORRIDAS (horas)")
    runs = corridas(d)
    desc = runs.groupby("regimen")["horas"].describe(
        percentiles=[.25, .5, .75, .9, .95]
    ).round(1)
    print(desc.to_string())
    print(f"\n  corridas totales: {len(runs)}")
    med_r2 = runs.loc[runs["regimen"] == "R2", "horas"].median()
    print(f"\n  mediana de corrida R2: {med_r2:.1f} h")
    if med_r2 > 24:
        print("    -> ESCALA DE DIAS. Compatible con campanas de mineral.")
    elif med_r2 < 12:
        print("    -> ESCALA SUB-TURNO. Compatible con decision de operador.")
    else:
        print("    -> ESCALA DE TURNO (~12h). Sospechoso: parece el relevo.")

    # --- 2 ---
    sec("2. AUTOCORRELACION DEL REGIMEN")
    ac, b = autocorrelacion(d)
    print(ac.to_string(index=False))
    a24, a72 = b.autocorr(24), b.autocorr(72)
    print(f"\n  a 24 h: {a24:+.3f}   a 72 h: {a72:+.3f}")
    if a72 > 0.3:
        print("    -> MEMORIA LARGA. El disparador persiste dias = mineral.")
    elif a24 < 0.2:
        print("    -> MEMORIA CORTA. Se olvida en un dia = operador.")

    # --- 3 ---
    sec("3. PERFIL POR HORA DEL DIA   <-- LA PRUEBA DECISIVA")
    print("  (fraccion del tiempo en R2, por hora)")
    p, stats_h = perfil_horario(d)
    print()
    print(p.to_string())
    print(f"\n  amplitud (max - min) : {stats_h['amplitud']}")
    print(f"  chi2                 : {stats_h['chi2']}   p = {stats_h['p']}")
    print("\n  El mineral NO sabe que hora es. Si el regimen depende de la hora,")
    print("  el disparador es humano.")
    if stats_h["amplitud"] > 0.10:
        print(f"    -> FIRMA HORARIA FUERTE ({stats_h['amplitud']:.1%} de amplitud).")
        print("       El OPERADOR dicta el regimen.")
    elif stats_h["amplitud"] < 0.04:
        print("    -> SIN firma horaria. El disparador es EXOGENO (mineral).")
    else:
        print("    -> Firma horaria debil. Probablemente ambos contribuyen.")

    sec("   Perfil por dia de la semana")
    print(perfil_dia_semana(d).to_string())

    # --- 4 ---
    sec("4. PERIODICIDAD (firma del rol de turnos)")
    print(periodicidad(b).to_string(index=False))
    print("\n  pico en 12h / 24h   -> turno")
    print("  pico en 96h (4x4) / 168h (7x7) -> ciclo de rol")
    print("  sin picos           -> el disparador no sigue el calendario laboral")

    # --- veredicto ---
    sec("VEREDICTO")
    votos_mineral = 0
    votos_operador = 0
    if med_r2 > 24:
        votos_mineral += 1
    elif med_r2 < 12:
        votos_operador += 1
    if a72 > 0.3:
        votos_mineral += 1
    elif a24 < 0.2:
        votos_operador += 1
    if stats_h["amplitud"] > 0.10:
        votos_operador += 2      # la prueba horaria pesa doble
    elif stats_h["amplitud"] < 0.04:
        votos_mineral += 2

    print(f"  evidencia MINERAL : {votos_mineral}")
    print(f"  evidencia OPERADOR: {votos_operador}")
    if votos_operador > votos_mineral:
        print("\n  -> R2 lo dicta el OPERADOR.")
        print("     R2 gasta 57% mas floculante y 28% mas torque para llegar a un")
        print("     lugar PEOR que R1 a igual masa de cama. Es sobre-floculacion")
        print("     autoinfligida. Estandarizar la practica en R1: ahi estan los m3/h.")
    elif votos_mineral > votos_operador:
        print("\n  -> R2 lo dicta el MINERAL.")
        print("     Es compensacion legitima a una alimentacion que no ves. El")
        print("     setpoint debe ADAPTARSE, y necesitas medir el mineral (P80,")
        print("     Courier) para cerrar el lazo.")
    else:
        print("\n  -> AMBIGUO. Cruzar con P80 / plan de mezcla para desempatar.")

    return d, runs


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "dataset_con_regimen.csv")
