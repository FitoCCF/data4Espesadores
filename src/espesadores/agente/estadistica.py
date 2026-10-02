# -*- coding: utf-8 -*-
"""
estadistica.py — detección estadística determinística del agente.

Todo lo de aquí produce dicts/listas serializables (sin DataFrames) para
que sirva igual a la CLI, al informe y como resultado de herramienta para
el LLM. Reutiliza pipeline/comun.py (Hampel, prueba de diferencia,
correlación parcial) en vez de reimplementar.

Variables: se trabaja por ROL (columnas ya enriquecidas por datos.enriquecer).
"""
import numpy as np
import pandas as pd

from espesadores.config import PROCESO
from espesadores.pipeline.comun import corr_parcial, filtro_hampel, prueba_diferencia

# Roles que interesan por defecto en resúmenes y anomalías. Los de planta se
# reportan una sola vez aunque se pidan para un espesador.
ROLES_PROCESO = ["flujo_alim", "valvula_alim", "presion_cama", "torque", "nivel_interfaz",
                 "nivel_cajon", "floculante", "agua_dilucion", "vel_descarga", "vel_cizalle",
                 "wt_activo", "dit_activo"]
ROLES_PLANTA = ["nivel_piscina", "flujo_piscinas", "tk001", "tk002", "molino_1", "molino_2",
                "molienda_total", "ley_rougher", "ratio_cu", "agua_fresca", "agua_qh"]
# Señales tipo escalón (consigna del operador, conteos): que no cambien en
# horas es lo normal, no un instrumento pegado.
ROLES_ESCALON = {"valvula_alim", "trenes_activos"}
# Unidades por rol (de los comentarios de calidad.yaml y tags.yaml); se
# adjuntan a los resultados para que el LLM no las invente.
UNIDADES = {"flujo_alim": "m3/h", "valvula_alim": "% apertura", "presion_cama": "%", "torque": "%",
            "nivel_interfaz": "m", "nivel_cajon": "%", "floculante": "m3/h", "agua_dilucion": "l/s",
            "vel_descarga": "% velocidad", "vel_cizalle": "% velocidad", "wt_activo": "% solidos",
            "dit_activo": "t/m3", "nivel_piscina": "%", "flujo_piscinas": "m3/h", "tk001": "%", "tk002": "%",
            "molino_1": "t/h", "molino_2": "t/h", "molienda_total": "t/h", "ley_rougher": "%",
            "ratio_cu": "adim", "agua_fresca": "m3/h", "agua_qh": "m3/h", "trenes_activos": "n"}


def _roles(df, espesador):
    roles = list(ROLES_PLANTA)
    if espesador and espesador != "planta":
        roles = ROLES_PROCESO + roles
    return [r for r in roles if r in df.columns]


def _f(x, nd=2):
    """float redondeado o None (JSON no admite NaN)."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(v) else round(v, nd)


# ============================================================================
# Resumen
# ============================================================================
def resumen(df, espesador=None, roles=None):
    """p10/p50/p90, cobertura y tendencia (primer vs último cuarto) por rol."""
    roles = roles or _roles(df, espesador)
    n = len(df)
    q = max(n // 4, 1)
    out = {}
    for r in roles:
        s = df[r]
        if s.notna().sum() == 0:
            out[r] = {"cobertura_pct": 0.0}
            continue
        out[r] = {
            "unidad": UNIDADES.get(r, ""),
            "cobertura_pct": _f(100 * s.notna().mean(), 1),
            "p10": _f(s.quantile(0.10)), "p50": _f(s.median()), "p90": _f(s.quantile(0.90)),
            "min": _f(s.min()), "max": _f(s.max()),
            "inicio_p50": _f(s.iloc[:q].median()), "fin_p50": _f(s.iloc[-q:].median()),
            "ultimo": _f(s.dropna().iloc[-1]) if s.notna().any() else None,
        }
    produciendo = df["molienda_total"] > PROCESO["tonelaje_min_produccion"] if "molienda_total" in df else None
    return {
        "espesador": espesador or "planta",
        "desde": df.index[0].isoformat(), "hasta": df.index[-1].isoformat(), "minutos": n,
        "planta_produciendo_pct": _f(100 * produciendo.mean(), 1) if produciendo is not None else None,
        "trenes_activos_moda": int(df["trenes_activos"].mode().iloc[0]) if "trenes_activos" in df and df["trenes_activos"].notna().any() else None,
        "variables": out,
    }


# ============================================================================
# Anomalías
# ============================================================================
def congelados(df, roles, minutos=60):
    """Tramos donde una señal no cambió durante >= `minutos` (stuck-at)."""
    out = []
    for r in roles:
        if r in ROLES_ESCALON:
            continue
        s = df[r]
        if s.notna().sum() < minutos:
            continue
        pegado = (s.diff() == 0)
        grupo = pegado.ne(pegado.shift(fill_value=False)).cumsum()
        for _, g in pegado[pegado].groupby(grupo[pegado]):
            # N diferencias nulas = N+1 valores iguales; el tramo empieza un
            # minuto antes del primer diff == 0.
            if len(g) + 1 >= minutos:
                t0 = g.index[0] - pd.Timedelta(minutes=1)
                out.append({"variable": r, "inicio": t0.isoformat(),
                            "minutos": int(len(g) + 1), "valor": _f(s.loc[g.index[0]])})
    return out


def atipicos(df, roles, ventana=21, n_sigma=4.0):
    """Puntos que el filtro de Hampel (mediana/MAD móvil) marca como atípicos."""
    out = []
    for r in roles:
        s = df[r]
        if s.notna().sum() < ventana * 2:
            continue
        _limpio, n = filtro_hampel(s, ventana, n_sigma)
        if n:
            mediana = s.rolling(ventana, center=True, min_periods=1).median()
            desv = (s - mediana).abs()
            mad = desv.rolling(ventana, center=True, min_periods=1).median()
            marca = desv > n_sigma * 1.4826 * mad
            peor = desv[marca].idxmax()
            out.append({"variable": r, "n_atipicos": int(n), "pct": _f(100 * n / s.notna().sum(), 2),
                        "peor_instante": peor.isoformat(), "peor_valor": _f(s.loc[peor]),
                        "mediana_local": _f(mediana.loc[peor])})
    return out


def cambios_de_regimen(df, roles, ventana_min=120, umbral_sigma=3.0, min_sep_min=240,
                       piso_relevancia=0.15):
    """Cambio de nivel: la mediana de la ventana posterior difiere de la
    anterior más de `umbral_sigma` MAD **y** más de `piso_relevancia` del
    rango p10-p90 de la señal (mismo criterio de relevancia que E10: con
    señales suaves la MAD es diminuta y todo sale "significativo"). Es un
    detector simple de escalón para señalar dónde mirar; no es un CUSUM."""
    out = []
    w = ventana_min
    for r in roles:
        s = df[r].astype(float)
        if s.notna().sum() < 3 * w:
            continue
        amplitud = float(s.quantile(0.9) - s.quantile(0.1))
        if not amplitud > 0:
            continue
        antes = s.rolling(w, min_periods=w // 2).median()
        despues = s[::-1].rolling(w, min_periods=w // 2).median()[::-1].shift(-1)
        mad = (s - antes).abs().rolling(w, min_periods=w // 2).median() * 1.4826
        escala = mad.replace(0, np.nan).fillna(mad[mad > 0].median() if (mad > 0).any() else np.nan)
        z = (despues - antes) / escala
        z = z.dropna()
        if z.empty:
            continue
        salto = (despues - antes).abs().reindex(z.index)
        candidatos = z[(z.abs() > umbral_sigma) & (salto >= piso_relevancia * amplitud)]
        ultimo = None
        for t, v in candidatos.items():
            if ultimo is not None and (t - ultimo) < pd.Timedelta(minutes=min_sep_min):
                continue
            # dentro de un bloque de candidatos, quedarse con el |z| máximo
            bloque = candidatos[(candidatos.index >= t) & (candidatos.index < t + pd.Timedelta(minutes=min_sep_min))]
            t_max = bloque.abs().idxmax()
            out.append({"variable": r, "instante": t_max.isoformat(),
                        "antes_p50": _f(antes.loc[t_max]), "despues_p50": _f(despues.loc[t_max]),
                        "z": _f(z.loc[t_max], 1)})
            ultimo = t_max
    return out


def anomalias(df, espesador=None, roles=None, minutos_congelado=60):
    roles = roles or _roles(df, espesador)
    return {
        "espesador": espesador or "planta",
        "desde": df.index[0].isoformat(), "hasta": df.index[-1].isoformat(),
        "congelados": congelados(df, roles, minutos_congelado),
        "atipicos": atipicos(df, roles),
        "cambios_de_regimen": cambios_de_regimen(df, roles),
    }


# ============================================================================
# Comparaciones
# ============================================================================
def comparar(df_a, df_b, espesador=None, roles=None, etiqueta_a="A", etiqueta_b="B"):
    """Mediana A vs B por rol con p-valor por permutación y piso de
    relevancia (misma prueba que E10: significativo Y relevante)."""
    roles = roles or _roles(df_a, espesador)
    out = {}
    for r in roles:
        if r not in df_a or r not in df_b:
            continue
        res = prueba_diferencia(df_a[r].values, df_b[r].values, n_permutaciones=200)
        ma, mb = res["mediana_a"], res["mediana_b"]
        if np.isnan(ma) or np.isnan(mb):
            lectura = "sin datos suficientes"
        elif mb == ma:
            lectura = f"{etiqueta_b} igual que {etiqueta_a}"
        else:
            pct = f" ({100 * (mb - ma) / abs(ma):+.1f} %)" if ma else ""
            lectura = (f"{etiqueta_b} {'mayor' if mb > ma else 'menor'} que {etiqueta_a} en "
                       f"{abs(mb - ma):.2f} {UNIDADES.get(r, '')}{pct}"
                       + ("" if res["relevante"] else "; diferencia NO relevante"))
        out[r] = {"unidad": UNIDADES.get(r, ""),
                  f"p50_{etiqueta_a}": _f(ma), f"p50_{etiqueta_b}": _f(mb),
                  "diferencia_B_menos_A": _f(mb - ma) if not (np.isnan(ma) or np.isnan(mb)) else None,
                  "mayor": (etiqueta_b if mb > ma else etiqueta_a) if not (np.isnan(ma) or np.isnan(mb) or mb == ma) else None,
                  "lectura": lectura, "p_valor": _f(res["p_valor"], 3),
                  "relevante": bool(res["relevante"]), "n_a": res["n_a"], "n_b": res["n_b"]}
    relevantes = sorted([r for r, v in out.items() if v["relevante"]],
                        key=lambda r: -abs(out[r]["diferencia_B_menos_A"] or 0))
    return {"espesador": espesador or "planta", "etiquetas": [etiqueta_a, etiqueta_b],
            "variables": out, "relevantes_ordenadas": relevantes}


def relaciones(df, objetivo, espesador=None, roles=None, controles=("molienda_total",)):
    """Correlación simple y parcial (controlando tonelaje) de `objetivo`
    contra cada rol, solo con planta produciendo."""
    roles = [r for r in (roles or _roles(df, espesador)) if r != objetivo]
    prod = df["molienda_total"] > PROCESO["tonelaje_min_produccion"] if "molienda_total" in df else pd.Series(True, index=df.index)
    d = df[prod]
    out = {}
    ctrl = [c for c in controles if c in d.columns and c != objetivo]
    for r in roles:
        par = d[[objetivo, r] + ctrl].dropna()
        if len(par) < 60:
            continue
        simple = par[objetivo].corr(par[r])
        parcial = corr_parcial(par, r, objetivo, ctrl) if ctrl else simple
        # corr_parcial puede devolver dict o float según versión de comun.py
        if isinstance(parcial, dict):
            parcial = parcial.get("r_parcial", parcial.get("r"))
        out[r] = {"r": _f(simple, 3), "r_parcial": _f(parcial, 3), "n": int(len(par))}
    orden = sorted(out, key=lambda r: -abs(out[r]["r_parcial"] or 0))
    return {"objetivo": objetivo, "controles": ctrl, "n_produciendo": int(prod.sum()),
            "variables": out, "orden_por_parcial": orden}


def tendencia(df, rol, ventana="1h"):
    """Serie reducida (mediana por ventana) para que el LLM 'vea' la forma
    sin recibir 1440 puntos: como máximo ~200 valores."""
    s = df[rol]
    n_obj = 200
    if len(s) / (pd.Timedelta(ventana) / pd.Timedelta(minutes=1)) > n_obj:
        ventana = pd.Timedelta(minutes=int(np.ceil(len(s) / n_obj)))
    agg = s.resample(ventana).median()
    return {"variable": rol, "ventana": str(ventana),
            "puntos": [[t.strftime("%Y-%m-%d %H:%M"), _f(v)] for t, v in agg.items()]}
