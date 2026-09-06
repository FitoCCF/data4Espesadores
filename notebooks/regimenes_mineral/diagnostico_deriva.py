"""
diagnostico_deriva.py  v2 — PASO 2 del pipeline.

ENTRADA : el CSV (o su caché)
SALIDA  : segmentos.json   <- lo consume analisis_espesador_v3.py

QUÉ CAMBIÓ RESPECTO A v1 (los tres errores que la corrida de 2 años expuso):

  1. EL CUSUM IBA SOBRE LA SERIE EQUIVOCADA.
     v1 buscaba cambios de nivel en el SESGO (A-B), que solo es calculable en
     los pocos meses donde ambas líneas tienen muestra. Con 25 meses, eso dio
     3 puntos válidos: inútil.
     v2 corre el CUSUM sobre rho_A y rho_B POR SEPARADO, que tienen 20+ puntos
     cada una. Ahí es donde se ve el escalón.

  2. EL SESGO SE MEDÍA POR MES CALENDARIO.
     Las líneas rotan mensualmente: casi todos los meses son 100% A o 100% B.
     Comparar dentro de un mes casi nunca tiene ambas.
     v2 identifica CAMPAÑAS (corridas continuas de una línea) y compara cada
     campaña B contra las campañas A adyacentes (antes y después). Eso controla
     la deriva lenta del proceso y usa toda la muestra.

  3. LA ESTACIONALIDAD SE CALCULABA SOBRE LOS 2 AÑOS AGREGADOS.
     Si hay un escalón de nivel a mitad del período, el perfil "estacional"
     no es más que ese escalón repartido entre meses. v2 la calcula DENTRO de
     cada segmento, y solo si el segmento cubre >= 8 meses.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from io_espesador import cargar_datos

SPEED_ON = 5.0
RHO_MIN, RHO_MAX = 1.30, 1.90

# Condición de referencia: mismo estado físico del cono en ambas líneas.
FEED_REF = (1300, 1700)
BEDMASS_REF = (52, 56)

N_MIN_CAMPANA = 300        # muestras mínimas para que una campaña cuente
HORAS_MIN_CAMPANA = 24     # una campaña de < 1 día no es una campaña
SALIDA_JSON = "segmentos.json"


# ----------------------------------------------------------------------------

def resolver_linea(d):
    a, b = d["x1"] > SPEED_ON, d["x4"] > SPEED_ON
    d = d.copy()
    d["linea"] = np.select([a & ~b, b & ~a], ["A", "B"], default="OTRO")
    d["rho_uf"] = np.select(
        [d["linea"] == "A", d["linea"] == "B"], [d["y4"], d["y5"]], default=np.nan
    )
    d.loc[~d["rho_uf"].between(RHO_MIN, RHO_MAX), "rho_uf"] = np.nan
    return d


def en_referencia(d):
    return (
        d["x6"].between(*FEED_REF)
        & d["y1"].between(*BEDMASS_REF)
        & d["rho_uf"].notna()
        & d["linea"].isin(["A", "B"])
    )


# ----------------------------------------------------------------------------
# 1. Nivel de densidad por línea, mes a mes   <-- aquí se ve el escalón
# ----------------------------------------------------------------------------

def nivel_por_linea(d, freq="ME"):
    base = d[en_referencia(d)]
    g = base.groupby([pd.Grouper(freq=freq), "linea"])["rho_uf"].agg(["median", "size"])
    piv = g.unstack("linea")
    out = pd.DataFrame(index=piv.index)
    for stat, pref in [("median", "rho"), ("size", "n")]:
        for ln in ["A", "B"]:
            out[f"{pref}_{ln}"] = piv[(stat, ln)] if (stat, ln) in piv.columns else np.nan
    out[["n_A", "n_B"]] = out[["n_A", "n_B"]].fillna(0)
    return out.round(4)


def cusum(serie, n_serie=None, n_min=300, k=0.5, h=4.0):
    """CUSUM sobre la mediana mensual. Ignora meses con muestra pobre."""
    s = serie.copy()
    if n_serie is not None:
        s = s.where(n_serie >= n_min)
    s = s.dropna()
    if len(s) < 8:
        return [], s

    mu, sd = s.mean(), s.std()
    if not sd or np.isnan(sd):
        return [], s

    pos = neg = 0.0
    cortes = []
    for t, v in s.items():
        z = (v - mu) / sd
        pos = max(0.0, pos + z - k)
        neg = min(0.0, neg + z + k)
        if pos > h or abs(neg) > h:
            cortes.append(t)
            pos = neg = 0.0
    return cortes, s


# ----------------------------------------------------------------------------
# 2. Sesgo estimado por CAMPAÑAS, no por meses
# ----------------------------------------------------------------------------

def campanas(d):
    """Corridas continuas de una misma línea. Cada cambio de línea abre una nueva."""
    ln = d["linea"]
    grupo = (ln != ln.shift()).cumsum()

    filas = []
    for _, sub in d.groupby(grupo):
        linea = sub["linea"].iloc[0]
        if linea not in ("A", "B"):
            continue
        horas = len(sub) / 60
        if horas < HORAS_MIN_CAMPANA:
            continue
        ref = sub[en_referencia(sub)]
        if len(ref) < N_MIN_CAMPANA:
            continue
        filas.append({
            "linea": linea,
            "inicio": sub.index[0],
            "fin": sub.index[-1],
            "centro": sub.index[0] + (sub.index[-1] - sub.index[0]) / 2,
            "horas": round(horas, 1),
            "n_ref": len(ref),
            "rho": round(float(ref["rho_uf"].median()), 4),
        })
    return pd.DataFrame(filas)


def sesgo_por_campana(camp):
    """Cada campaña B se compara contra la interpolación temporal de las campañas
    A que la rodean. Así se descuenta la deriva lenta del proceso y queda solo
    la diferencia entre instrumentos.
    """
    if camp.empty:
        return pd.DataFrame()

    a = camp[camp["linea"] == "A"].sort_values("centro")
    b = camp[camp["linea"] == "B"].sort_values("centro")
    if len(a) < 2 or len(b) < 1:
        return pd.DataFrame()

    ta = a["centro"].astype("int64").to_numpy()
    ra = a["rho"].to_numpy()

    filas = []
    for _, row in b.iterrows():
        tb = pd.Timestamp(row["centro"]).value
        if tb < ta.min() or tb > ta.max():
            continue                       # sin campaña A a ambos lados: no interpolar
        rho_a_interp = float(np.interp(tb, ta, ra))
        filas.append({
            "campana_B": pd.Timestamp(row["inicio"]).date(),
            "horas": row["horas"],
            "n_ref": row["n_ref"],
            "rho_B": row["rho"],
            "rho_A_interp": round(rho_a_interp, 4),
            "sesgo": round(rho_a_interp - row["rho"], 4),
        })
    return pd.DataFrame(filas)


# ----------------------------------------------------------------------------
# 3. Segmentos
# ----------------------------------------------------------------------------

def construir_segmentos(d, cortes, ses_camp):
    bordes = [d.index.min()] + sorted(set(cortes)) + [d.index.max()]
    segs = []
    for i in range(len(bordes) - 1):
        a, b = bordes[i], bordes[i + 1]
        if ses_camp.empty:
            sesgo, n_camp = None, 0
        else:
            m = ses_camp[
                (pd.to_datetime(ses_camp["campana_B"]) >= a)
                & (pd.to_datetime(ses_camp["campana_B"]) <= b)
            ]
            sesgo = None if m.empty else round(float(m["sesgo"].median()), 4)
            n_camp = len(m)

        sub = d.loc[a:b]
        ref = sub[en_referencia(sub)]
        segs.append({
            "id": i + 1,
            "inicio": str(pd.Timestamp(a).date()),
            "fin": str(pd.Timestamp(b).date()),
            "dias": round((b - a).total_seconds() / 86400, 1),
            "sesgo_dit146": sesgo,
            "n_campanas_B": n_camp,
            "rho_A_mediano": None if ref[ref["linea"] == "A"].empty
                             else round(float(ref[ref["linea"] == "A"]["rho_uf"].median()), 4),
            "rho_B_mediano": None if ref[ref["linea"] == "B"].empty
                             else round(float(ref[ref["linea"] == "B"]["rho_uf"].median()), 4),
        })
    return segs


def estacionalidad(d, ini, fin):
    """Solo dentro de un segmento, y solo si cubre >= 8 meses. Si no, lo que
    parece estacionalidad es el escalón de nivel repartido entre meses.
    """
    sub = d.loc[ini:fin]
    meses = (pd.Timestamp(fin) - pd.Timestamp(ini)).days / 30.4
    if meses < 8:
        return None, meses
    base = sub[en_referencia(sub) & (sub["linea"] == "A")].copy()
    if len(base) < 2000:
        return None, meses
    base["mes"] = base.index.month
    return base.groupby("mes")["rho_uf"].agg(["median", "size"]).round(4), meses


# ----------------------------------------------------------------------------

def sec(t):
    print("\n" + "=" * 72 + f"\n{t}\n" + "=" * 72)


def main(path, salida=SALIDA_JSON):
    df, info = cargar_datos(path)
    d = resolver_linea(df)

    sec("COBERTURA (horas por mes y linea)")
    cob = d.groupby([pd.Grouper(freq="ME"), "linea"]).size().unstack(fill_value=0) / 60
    print(cob.round(0).to_string())
    hA = cob.get("A", pd.Series(dtype=float)).sum()
    hB = cob.get("B", pd.Series(dtype=float)).sum()
    print(f"\n  Total: linea A = {hA:.0f} h ({100*hA/(hA+hB):.0f} %), "
          f"linea B = {hB:.0f} h ({100*hB/(hA+hB):.0f} %)")

    sec("NIVEL DE DENSIDAD POR LINEA (condicion fija: feed 1300-1700, BedMass 52-56)")
    niv = nivel_por_linea(d)
    print(niv.to_string())

    cortes_A, sA = cusum(niv["rho_A"], niv["n_A"])
    cortes_B, sB = cusum(niv["rho_B"], niv["n_B"])
    cortes = sorted(set(cortes_A) | set(cortes_B))

    print(f"\n  linea A: {len(sA)} meses validos, "
          f"rango {sA.min():.4f}..{sA.max():.4f}, desv {sA.std():.4f}")
    if len(sB):
        print(f"  linea B: {len(sB)} meses validos, "
              f"rango {sB.min():.4f}..{sB.max():.4f}, desv {sB.std():.4f}")

    if cortes:
        print(f"\n  *** CAMBIO(S) DE NIVEL DETECTADO(S): "
              f"{[str(pd.Timestamp(c).date()) for c in cortes]}")
        print("      A CONDICION FISICA IDENTICA. Causas posibles:")
        print("        - recalibracion del densimetro  -> las escalas no son comparables")
        print("        - cambio de mineral / floculante / mecanismo")
        print("        - cambio de filosofia de control")
        print("      REVISAR BITACORAS DE ESAS FECHAS antes de seguir.")
    else:
        print("\n  Sin cambios de nivel. La serie es homogenea.")

    sec("SESGO DIT-144 vs DIT-146, POR CAMPANA")
    print("  (cada campana B contra la interpolacion de las campanas A vecinas)")
    camp = campanas(d)
    print(f"\n  campanas validas: {len(camp)} "
          f"(A={sum(camp['linea']=='A') if len(camp) else 0}, "
          f"B={sum(camp['linea']=='B') if len(camp) else 0})")

    ses = sesgo_por_campana(camp)
    if ses.empty:
        print("  Insuficiente para estimar el sesgo. Se requiere muestreo fisico.")
    else:
        print()
        print(ses.to_string(index=False))
        s = ses["sesgo"]
        print(f"\n  sesgo mediano : {s.median():+.4f} t/m3   (n={len(s)} campanas)")
        print(f"  desv. est.    : {s.std():.4f}")
        if s.std() < 0.008:
            print("  -> CONSISTENTE. Es calibracion. Corregir DIT-146.")
        else:
            print("  -> INCONSISTENTE entre campanas. No es un offset fijo.")
            print("     Puede ser deriva del transmisor, o diferencia real de proceso.")
            print("     Resolver con muestreo fisico (balanza Marcy) en ambas lineas.")

    segs = construir_segmentos(d, cortes, ses)

    sec("SEGMENTOS")
    for sg in segs:
        print(f"  [{sg['id']}] {sg['inicio']} -> {sg['fin']}  ({sg['dias']:.0f} d)")
        print(f"      rho_A={sg['rho_A_mediano']}  rho_B={sg['rho_B_mediano']}  "
              f"sesgo={sg['sesgo_dit146']}  (n={sg['n_campanas_B']} campanas B)")

    sec("ESTACIONALIDAD (solo dentro de segmento, y solo si cubre >= 8 meses)")
    for sg in segs:
        est, meses = estacionalidad(d, sg["inicio"], sg["fin"])
        if est is None:
            print(f"  Segmento {sg['id']}: {meses:.1f} meses -> insuficiente, se omite")
        else:
            rango = est["median"].max() - est["median"].min()
            print(f"\n  Segmento {sg['id']} (linea A):")
            print(est.to_string())
            print(f"  rango estacional: {rango:.4f} t/m3", end="  ")
            print("-> SIGNIFICATIVO" if rango > 0.010 else "-> despreciable")

    doc = {
        "archivo": Path(path).name,
        "generado": datetime.now().isoformat(timespec="seconds"),
        "paso_min": info["paso_min"],
        "rango": info["rango"],
        "cortes_detectados": [str(pd.Timestamp(c).date()) for c in cortes],
        "condicion_referencia": {"feed": list(FEED_REF), "bedmass": list(BEDMASS_REF)},
        "segmentos": segs,
    }
    Path(salida).write_text(json.dumps(doc, indent=2, ensure_ascii=False))

    sec("SALIDA")
    print(f"  -> {salida} ({len(segs)} segmento(s))")
    if cortes:
        print("\n  NO agregues a traves de los cortes hasta saber que los causo.")

    return doc


if __name__ == "__main__":
    en_nb = "ipykernel" in sys.modules
    p = ("Data_Esp1_20260714_0921.csv"
         if en_nb or len(sys.argv) < 2 or sys.argv[1].startswith("-")
         else sys.argv[1])
    main(p)
