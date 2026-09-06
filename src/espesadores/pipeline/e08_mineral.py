# -*- coding: utf-8 -*-
"""E08 - Tipos de mineral (no supervisado)."""
import numpy as np
import pandas as pd

from espesadores.config import GLOBALES, VENTANAS_MIN
from .comun import log, titulo, guardar


def e08_mineral(df, cfg, ctx, k=4):
    """
    Agrupa la operación en tipos de mineral usando SOLO variables exógenas.

    SUSTENTO ANTI-CIRCULARIDAD: si se agrupara usando variables que el
    operador manipula (floculante, velocidades, válvula), los grupos
    reflejarían decisiones del operador y luego "descubrir" que el operador
    responde a ellos sería una tautología. Por eso la firma usa únicamente
    propiedades de la alimentación: ley de rougher y ratio de Cu.

    CONTROL POSITIVO: antes de interpretar nada, se verifica que los grupos
    sean aprendibles desde las propias variables exógenas. Si no lo fueran,
    el detector estaría roto y cualquier conclusión sobre influencia del
    mineral sería un falso negativo.
    """
    titulo("E08 - TIPOS DE MINERAL (no supervisado)")
    from sklearn.preprocessing import StandardScaler, QuantileTransformer
    from sklearn.cluster import KMeans, AgglomerativeClustering, Birch
    from sklearn.mixture import GaussianMixture
    from sklearn.metrics import (silhouette_score, davies_bouldin_score,
                                 calinski_harabasz_score, adjusted_rand_score)

    firma = [c for c in (GLOBALES["ley_rougher"], GLOBALES["ratio_cu"])
             if c in df.columns and c not in ctx["descartadas"]]
    if len(firma) < 2:
        log("  Sin variables exogenas suficientes: se omite la deteccion de mineral.")
        df["mineral"] = 0
        ctx["mineral_ok"] = False
        return df
    log(f"  Firma de mineral (exogena): {firma}")

    v_agg = f"{VENTANAS_MIN['agregacion_mineral']}min"
    A = df[firma].resample(v_agg).median().dropna()
    log(f"  Ventanas de {v_agg}: {len(A):,}")

    Z = StandardScaler().fit_transform(
        QuantileTransformer(output_distribution="normal", random_state=42)
        .fit_transform(A.values))

    log("")
    log(f"  {'k':>2s} {'algoritmo':>10s} {'silueta':>9s} {'davies-b':>9s} "
        f"{'calinski':>9s} {'grupo mayor':>12s}")
    filas = []
    for kk in range(2, 7):
        modelos = {
            "KMeans": KMeans(kk, n_init=10, random_state=42).fit_predict(Z),
            "GMM": GaussianMixture(kk, n_init=3, random_state=42).fit_predict(Z),
            "Ward": AgglomerativeClustering(kk).fit_predict(Z),
            "Birch": Birch(n_clusters=kk).fit_predict(Z),
        }
        for nombre, etiquetas in modelos.items():
            mayor = pd.Series(etiquetas).value_counts(normalize=True).iloc[0]
            sil = silhouette_score(Z, etiquetas)
            dbi = davies_bouldin_score(Z, etiquetas)
            chi = calinski_harabasz_score(Z, etiquetas)
            filas.append({"k": kk, "algoritmo": nombre, "silueta": round(sil, 3),
                          "davies_bouldin": round(dbi, 3),
                          "calinski": round(chi, 0), "grupo_mayor_pct": round(100*mayor, 1)})
            log(f"  {kk:2d} {nombre:>10s} {sil:9.3f} {dbi:9.3f} {chi:9.0f} {100*mayor:11.1f}%")
    guardar(pd.DataFrame(filas).set_index(["k", "algoritmo"]),
            "E08a_comparacion_algoritmos.csv", ctx["salidas"])

    log("")
    log("  Estabilidad (indice de Rand ajustado sobre remuestreos; 1.0 = estable)")
    rng = np.random.default_rng(42)
    est = []
    for kk in range(2, 7):
        base = KMeans(kk, n_init=10, random_state=42).fit(Z)
        aris = []
        for _ in range(15):
            idx = rng.choice(len(Z), int(0.8 * len(Z)), replace=False)
            m = KMeans(kk, n_init=5, random_state=int(rng.integers(1e6))).fit(Z[idx])
            aris.append(adjusted_rand_score(base.labels_[idx], m.labels_))
        est.append({"k": kk, "ari_medio": round(np.mean(aris), 3),
                    "ari_desv": round(np.std(aris), 3)})
        log(f"      k={kk}: ARI = {np.mean(aris):.3f} +/- {np.std(aris):.3f}")
    guardar(pd.DataFrame(est).set_index("k"), "E08b_estabilidad.csv", ctx["salidas"])

    etiquetas = KMeans(k, n_init=10, random_state=42).fit_predict(Z)
    A = A.assign(mineral=etiquetas)
    df = df.join(A[["mineral"]].reindex(df.index, method="ffill"))
    df["mineral"] = df["mineral"].fillna(-1).astype(int)

    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import GroupKFold
    from sklearn.metrics import roc_auc_score
    E = df[firma + ["mineral"]].dropna().copy()
    E["dia"] = E.index.date.astype(str)
    X = StandardScaler().fit_transform(E[firma].values)
    y, grupos = E["mineral"].values, E["dia"].values
    aucs = []
    for tr, te in GroupKFold(n_splits=4).split(X, y, grupos):
        if len(np.unique(y[tr])) < 2:
            continue
        m = RandomForestClassifier(150, min_samples_leaf=30, n_jobs=-1,
                                   random_state=42).fit(X[tr], y[tr])
        p = m.predict_proba(X[te])
        clases = np.unique(y[tr])
        yt = pd.get_dummies(pd.Categorical(y[te], categories=clases)).values
        try:
            aucs.append(roc_auc_score(yt, p, average="macro", multi_class="ovr"))
        except Exception:
            pass
    auc = float(np.mean(aucs)) if aucs else np.nan
    log("")
    log(f"  CONTROL POSITIVO (exogenas -> tipo de mineral): AUC = {auc:.3f}")
    ctx["mineral_ok"] = bool(auc > 0.70)
    log(f"  -> {'DETECTOR VALIDO' if ctx['mineral_ok'] else 'DETECTOR NO VALIDO: no interpretar E09/E10 por mineral'}")
    ctx["mineral_auc"] = auc
    ctx["k_mineral"] = k
    return df
