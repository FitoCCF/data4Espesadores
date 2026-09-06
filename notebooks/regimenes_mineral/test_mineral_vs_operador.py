#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
TEST: ¿EL TIPO DE MINERAL INFLUYE EN LOS PARAMETROS QUE FIJA EL OPERADOR?
================================================================================
Hipotesis nula (lo que sospechamos): los setpoints del operador son
INDEPENDIENTES del mineral (los cambia por criterio/guardia, no por la ley).

Cuatro pruebas convergentes:
  1. Clustering del espacio de OPERACION con varios algoritmos + validacion.
  2. Concordancia entre clusters de MINERAL y clusters de OPERACION
     (Adjusted Rand Index, NMI, Cramer's V). ~0 => independientes.
  3. Predictibilidad supervisada: RandomForest mineral -> setpoint,
     con CV por dia (sin fuga temporal) vs baseline. Bajo => independientes.
  4. Descomposicion de varianza del floculante: eta^2 por mineral vs por dia.

Salida: solo metricas resumidas (pegables). No vuelca filas.

Uso:   python test_mineral_vs_operador.py
Requiere: pandas numpy scikit-learn scipy pyarrow
(hdbscan es opcional; si no esta, se omite)
================================================================================
"""
import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans, AgglomerativeClustering, DBSCAN
from sklearn.mixture import GaussianMixture
from sklearn.metrics import (silhouette_score, davies_bouldin_score,
    calinski_harabasz_score, adjusted_rand_score, normalized_mutual_info_score,
    balanced_accuracy_score, r2_score)
from sklearn.ensemble import RandomForestRegressor, RandomForestClassifier
from sklearn.model_selection import GroupKFold, cross_val_score
from scipy.stats import chi2_contingency

# ----------------------- CONFIG -----------------------
INPUT   = "datos.parquet"     # o "Data_Esp1_20260724_1545.csv"
SUBSAMP = 30000               # muestra para clustering/validacion (velocidad)
SEED    = 0
rng = np.random.default_rng(SEED)

# Variables MANIPULADAS por el operador (espacio de OPERACION)
OPER = ['PP_007A_Speed','PP_008A_Speed','PP_001A_U_Speed','PP_002A_U_Speed',
        'FIT_104','FV_1001','TH001_PLC_LVL']
# Variables EXOGENAS de mineral/alimentacion (espacio de MINERAL)
ORE  = ['ALIM_RO_PROM_SC','Ratio_Con_Cu','Alim_Total_PB01']

# ----------------------- CARGA + LIMPIEZA LIGERA -----------------------
def load(path):
    return pd.read_parquet(path) if path.endswith('.parquet') else pd.read_csv(path)

print("="*70); print("CARGA Y PREPARACION"); print("="*70)
df = load(INPUT)
if 'timestamp' in df.columns:
    df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
    df = df.sort_values('timestamp').reset_index(drop=True)

# rango fisico basico
RANGES = {'Alim_Total_PB01':(0,2500),'ALIM_RO_PROM_SC':(0,80),'Ratio_Con_Cu':(0,200),
          'FIT_104':(0,50),'FV_1001':(0,100),'TH001_PLC_LVL':(0,10),
          'PP_007A_Speed':(0,100),'PP_008A_Speed':(0,100),
          'PP_001A_U_Speed':(0,100),'PP_002A_U_Speed':(0,100)}
for c,(lo,hi) in RANGES.items():
    if c in df: df.loc[(df[c]<lo)|(df[c]>hi), c] = np.nan
df = df[df['Alim_Total_PB01'] > 100].copy()           # planta produciendo
# ley 0 = sin medicion valida -> NaN
df['ALIM_RO_PROM_SC'] = df['ALIM_RO_PROM_SC'].replace(0, np.nan)
df['Ratio_Con_Cu']    = df['Ratio_Con_Cu'].replace(0, np.nan)

# suavizado a 2h del estado (para comparar "condiciones", no ruido de minuto)
if 'timestamp' in df.columns:
    df = df.set_index('timestamp')
    for c in OPER+ORE:
        df[c] = df[c].rolling('2h', min_periods=20).median()
    df['fecha'] = df.index.date
    df = df.reset_index()
else:
    df['fecha'] = (np.arange(len(df))//720)   # ~medio dia si 1min

base = df.dropna(subset=OPER+ORE).copy()
print(f"Filas utilizables: {len(base):,}")

# subsample para clustering pesado
idx = rng.choice(len(base), min(SUBSAMP, len(base)), replace=False)
S = base.iloc[idx].reset_index(drop=True)
Zop  = StandardScaler().fit_transform(S[OPER])
Zore = StandardScaler().fit_transform(S[ORE])

# ----------------------- 1. CLUSTERING MULTI-ALGORITMO -----------------------
print("\n"+"="*70)
print("1. VALIDACION DE CLUSTERING DEL ESPACIO DE OPERACION")
print("="*70)
print(f"  (muestra n={len(S):,})")
print(f"  {'algoritmo':16s} {'k':>3s} {'silhouette':>11s} {'davies-b':>9s} {'calinski':>9s}")

def report_clust(name, labels, Z):
    m = labels >= 0                     # DBSCAN marca ruido con -1
    if len(set(labels[m])) < 2:
        print(f"  {name:16s}  ---  (no formo >=2 clusters)"); return None
    sil = silhouette_score(Z[m], labels[m])
    db  = davies_bouldin_score(Z[m], labels[m])
    ch  = calinski_harabasz_score(Z[m], labels[m])
    print(f"  {name:16s} {len(set(labels[m])):3d} {sil:11.3f} {db:9.3f} {ch:9.0f}")
    return labels

oper_labels = {}
# KMeans y GMM: barrido de k
for k in [2,3,4]:
    oper_labels[f'KMeans_k{k}'] = report_clust(f'KMeans k={k}',
        KMeans(k, n_init=10, random_state=SEED).fit_predict(Zop), Zop)
for k in [2,3,4]:
    oper_labels[f'GMM_k{k}'] = report_clust(f'GMM k={k}',
        GaussianMixture(k, n_init=5, random_state=SEED).fit_predict(Zop), Zop)
# Aglomerativo (Ward) k=3
oper_labels['Agg_k3'] = report_clust('Aglomerativo k3',
    AgglomerativeClustering(3).fit_predict(Zop), Zop)
# DBSCAN (densidad, elige k solo)
oper_labels['DBSCAN'] = report_clust('DBSCAN',
    DBSCAN(eps=1.2, min_samples=50).fit_predict(Zop), Zop)
# HDBSCAN opcional
try:
    import hdbscan
    oper_labels['HDBSCAN'] = report_clust('HDBSCAN',
        hdbscan.HDBSCAN(min_cluster_size=200).fit_predict(Zop), Zop)
except Exception:
    print("  HDBSCAN         ---  (no instalado, omitido)")

# ----------------------- 2. CONCORDANCIA MINERAL vs OPERACION -----------------------
print("\n"+"="*70)
print("2. CONCORDANCIA entre clusters de MINERAL y de OPERACION")
print("="*70)
print("  (ARI/NMI ~0 y Cramer V bajo => el mineral NO define el modo de operacion)")

def cramers_v(a, b):
    ct = pd.crosstab(a, b)
    chi2 = chi2_contingency(ct)[0]
    n = ct.values.sum(); r,k = ct.shape
    return np.sqrt((chi2/n) / max(min(r-1,k-1),1))

print(f"  {'k':>3s} {'ARI':>8s} {'NMI':>8s} {'CramerV':>9s}")
for k in [2,3,4]:
    lab_op  = KMeans(k, n_init=10, random_state=SEED).fit_predict(Zop)
    lab_ore = KMeans(k, n_init=10, random_state=SEED).fit_predict(Zore)
    ari = adjusted_rand_score(lab_ore, lab_op)
    nmi = normalized_mutual_info_score(lab_ore, lab_op)
    cv  = cramers_v(lab_ore, lab_op)
    print(f"  {k:3d} {ari:8.3f} {nmi:8.3f} {cv:9.3f}")

# ----------------------- 3. PREDICTIBILIDAD SUPERVISADA -----------------------
print("\n"+"="*70)
print("3. ¿PUEDE EL MINERAL PREDECIR LOS SETPOINTS DEL OPERADOR?")
print("="*70)
print("  CV por DIA (GroupKFold) evita fuga por autocorrelacion.")
print("  Score ~ baseline => el mineral NO informa el setpoint.\n")

# usar TODA la data utilizable (no solo subsample) para el supervisado
G = base.copy()
groups = pd.factorize(G['fecha'])[0]
gkf = GroupKFold(n_splits=5)
Xore = G[ORE].values

# 3a. Regresion: mineral -> floculante (continuo)
y = G['FIT_104'].values
rf = RandomForestRegressor(n_estimators=120, max_depth=12, n_jobs=-1, random_state=SEED)
r2 = cross_val_score(rf, Xore, y, groups=groups, cv=gkf, scoring='r2', n_jobs=-1)
print(f"  Predecir FLOCULANTE desde mineral:")
print(f"    R2 (CV por dia) = {r2.mean():+.3f} +/- {r2.std():.3f}   (baseline media = 0.000)")

# 3b. Clasificacion: mineral -> LINEA de bomba activa (modo dominante)
G['linea'] = np.where(G['PP_007A_Speed']>5,1,np.where(G['PP_008A_Speed']>5,0,-1))
Gc = G[G['linea']>=0]
if Gc['linea'].nunique() > 1:
    grp2 = pd.factorize(Gc['fecha'])[0]
    clf = RandomForestClassifier(n_estimators=120, max_depth=12, n_jobs=-1,
                                 random_state=SEED, class_weight='balanced')
    ba = cross_val_score(clf, Gc[ORE].values, Gc['linea'].values, groups=grp2,
                         cv=gkf, scoring='balanced_accuracy', n_jobs=-1)
    print(f"  Predecir LINEA de bomba desde mineral:")
    print(f"    Balanced accuracy (CV por dia) = {ba.mean():.3f} +/- {ba.std():.3f}"
          f"   (azar = 0.500)")

# ----------------------- 4. DESCOMPOSICION DE VARIANZA (eta^2) -----------------------
print("\n"+"="*70)
print("4. DESCOMPOSICION DE VARIANZA DEL FLOCULANTE")
print("="*70)
print("  eta^2 = fraccion de varianza explicada por cada factor.")

def eta2(dfx, value, factor):
    g = dfx.dropna(subset=[value, factor])
    grand = g[value].mean()
    ss_tot = ((g[value]-grand)**2).sum()
    ss_bet = g.groupby(factor)[value].apply(lambda s: len(s)*(s.mean()-grand)**2).sum()
    return ss_bet/ss_tot if ss_tot>0 else np.nan

G['ore_bin'] = pd.qcut(G['ALIM_RO_PROM_SC'], 6, duplicates='drop')
e_ore = eta2(G, 'FIT_104', 'ore_bin')
e_day = eta2(G, 'FIT_104', 'fecha')
print(f"  eta^2 floculante | MINERAL (ley en 6 bins) = {e_ore:.3f}")
print(f"  eta^2 floculante | DIA de operacion        = {e_day:.3f}")
if not np.isnan(e_ore) and not np.isnan(e_day):
    print(f"  Ratio dia/mineral = {e_day/max(e_ore,1e-6):.1f}x"
          f"   ({'DIA/guardia domina' if e_day>e_ore else 'MINERAL domina'})")

# ----------------------- VEREDICTO -----------------------
print("\n"+"="*70)
print("VEREDICTO (interpretacion automatica)")
print("="*70)
print("  Si en 1-4 se observa: silhouette de operacion moderado-alto PERO")
print("  ARI/NMI~0, R2 supervisado bajo (<0.2), y eta^2(dia)>>eta^2(mineral),")
print("  entonces el mineral NO explica los cambios del operador (hipotesis")
print("  confirmada: la variacion la manda la guardia/criterio, no la ley).")
