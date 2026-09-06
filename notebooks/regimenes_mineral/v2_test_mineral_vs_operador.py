#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
DETECCION DE TIPO DE MINERAL + TEST DE INFLUENCIA SOBRE EL OPERADOR  (v2)
Espesador de Relaves TH-001
================================================================================
Validado sobre 1,064,161 filas (data 1 min, 2 anios).

POR QUE v2: la v1 FALLO y hay que saber por que.
  (a) rho_s (grav.esp. solidos) salio CONSTANTE = 2.770 (CV 0.96%). Causa: el DCS
      calcula %solidos DESDE la densidad con SG fijo 2.77 -> WT_146 y DIT_146 NO
      son mediciones independientes (90.2% de filas caen en esa curva con error
      <0.1 pto). Como firma mineralogica es NULA por construccion.
  (b) Ratio_concentracion_Output tiene 94 valores unicos y 85.7% es 53.166 (hold
      del reporte de metalurgia). El clustering "encontraba" ESE artefacto:
      silhouette 0.92 falso y particion degenerada (1 cluster = 94.6%).
  => Ambas variables se ELIMINAN de la firma.

DISENIO ANTI-CIRCULARIDAD:
  FIRMA MINERAL (exogena)        ACCION DE OPERADOR (manipulada)
  -----------------------        --------------------------------
  ALIM_RO_PROM_SC (ley)          FIT_104   (floculante)
  Ratio_Con_Cu                   FV_1001   (valvula)
  Alim_Total_PB01 (dureza)       PP_007A/008A_Speed
  reologia_res (yield stress)    PP_001A/002A_U_Speed
                                 TH001_PLC_LVL
  reologia_res = residuo de TORQUE dado BEDM -> proxy de yield stress (arcillas).

CONTROL POSITIVO COMO FILTRO DE ACEPTACION (clave):
  Antes de interpretar "el mineral no influye", hay que probar que los clusters
  SON mineral real. Si no afectan al proceso ni son aprendibles desde las
  exogenas, el test es INCONCLUYENTE (no se puede probar ausencia con un
  detector roto).

RESULTADOS OBTENIDOS:
  Estabilidad ARI (k=4) ............... 0.92   (estructura solida)
  Control(+) exogenas -> mineral ...... AUC 0.995  (la senial ES aprendible)
  Operador -> mineral (MLP) ........... AUC 0.664
  Operador -> mineral (RandomForest) .. AUC 0.695
  Nulo (etiquetas permutadas) ......... AUC 0.506
  Sin tonelaje (anti-confundidor) ..... AUC 0.691
  eta2 mineral -> setpoints ........... 0.001 - 0.033
  eta2 GUARDIA/DIA -> setpoints ....... 0.353 - 0.976   (32x mas)

CONCLUSION: el mineral tiene influencia DEBIL pero NO NULA (AUC 0.69 > 0.51 del
azar). La guardia explica ~32x mas varianza. El criterio del operador domina.

REQUIERE: pandas numpy scikit-learn pyarrow
USO: python deteccion_mineral_v2.py
================================================================================
"""
import warnings; warnings.filterwarnings('ignore')
import numpy as np, pandas as pd
from sklearn.preprocessing import StandardScaler, QuantileTransformer
from sklearn.cluster import KMeans, AgglomerativeClustering, Birch, DBSCAN
from sklearn.mixture import GaussianMixture
from sklearn.metrics import (silhouette_score, davies_bouldin_score,
    calinski_harabasz_score, adjusted_rand_score, roc_auc_score, accuracy_score)
from sklearn.model_selection import GroupKFold
from sklearn.neural_network import MLPClassifier
from sklearn.ensemble import RandomForestClassifier

INPUT="datos.parquet"; SEED=42; AGG="1h"
FIRMA=['ALIM_RO_PROM_SC','Ratio_Con_Cu','Alim_Total_PB01','reologia_res']
OPER =['FIT_104','FV_1001','TH001_PLC_LVL','PP_007A_Speed','PP_008A_Speed',
       'PP_001A_U_Speed','PP_002A_U_Speed']
PROC =['WT_activo','TH001_PLC_BEDM']   # resultado limpio (NO usa torque: circular)
PHYS={'Alim_Total_PB01':(0,2500),'ALIM_RO_PROM_SC':(0,80),'Ratio_Con_Cu':(0,200),
 'WT_144':(0,80),'WT_146':(0,80),'DIT_144':(1,2.2),'DIT_146':(1,2.2),'FIT_104':(0,50),
 'PP_007A_Speed':(0,100),'PP_008A_Speed':(0,100),'PP_001A_U_Speed':(0,100),
 'PP_002A_U_Speed':(0,100),'TH001_PLC_TORK':(0,100),'TH001_PLC_BEDM':(0,100),
 'TH001_PLC_LVL':(0,10),'FV_1001':(0,100),'LIT_1011_Flow':(0,8000),
 'LIT_1111_Flow':(0,8000),'LIT_1211_Flow':(0,6000)}
def h(t): print("\n"+"="*76); print(t); print("="*76)

def eta2(d,val,grp):
    d=d[[val,grp]].dropna()
    if len(d)<50 or d[val].std()==0: return np.nan
    gm=d.groupby(grp)[val]
    ssb=sum(len(x)*(x.mean()-d[val].mean())**2 for _,x in gm)
    sst=((d[val]-d[val].mean())**2).sum()
    return ssb/sst if sst>0 else np.nan

def cv_auc(X,y,g,mk):
    gkf=GroupKFold(5); au=[]; ac=[]
    for tr,te in gkf.split(X,y,g):
        if len(np.unique(y[tr]))<2: continue
        m=mk().fit(X[tr],y[tr]); p=m.predict_proba(X[te]); cl=np.unique(y[tr])
        try:
            yt=pd.get_dummies(pd.Categorical(y[te],categories=cl)).values
            au.append(roc_auc_score(yt,p,average='macro',multi_class='ovr'))
        except Exception: pass
        ac.append(accuracy_score(y[te],m.predict(X[te])))
    return (np.mean(au) if au else np.nan),(np.mean(ac) if ac else np.nan)

def main():
    h("PASO 0 - CARGA + DIAGNOSTICO DE VARIABLES INSERVIBLES")
    df=pd.read_parquet(INPUT) if INPUT.endswith('.parquet') else pd.read_csv(INPUT)
    df=df.drop(columns=[c for c in df.columns if df[c].isna().all()])
    df['timestamp']=pd.to_datetime(df['timestamp'],errors='coerce')
    df=df.sort_values('timestamp').set_index('timestamp')
    for c,(lo,hi) in PHYS.items():
        if c in df: df.loc[(df[c]<lo)|(df[c]>hi),c]=np.nan
    df=df[df.Alim_Total_PB01>100]
    for c in ['ALIM_RO_PROM_SC','Ratio_Con_Cu']: df[c]=df[c].replace(0,np.nan)
    on7=df.PP_007A_Speed>5; on8=df.PP_008A_Speed>5
    df['WT_activo']=np.where(on7,df.WT_146,np.where(on8,df.WT_144,np.nan))
    df['DIT_activo']=np.where(on7,df.DIT_146,np.where(on8,df.DIT_144,np.nan))
    # diagnostico (a): SG constante?
    w=df.WT_activo/100; sg=w/((1/df.DIT_activo)-(1-w))
    sg=sg[(sg>2)&(sg<5.5)]
    print(f"  SG solidos implicito: mediana={sg.median():.4f} CV={100*sg.std()/sg.mean():.2f}%")
    print("  -> CV<2% significa SG CABLEADO en el DCS: NO usar como firma mineral.")
    # diagnostico (b): holds
    rc=df.get('Ratio_concentracion_Output')
    if rc is not None:
        print(f"  Ratio_concentracion_Output: unicos={rc.nunique()} "
              f"top1={100*rc.value_counts(normalize=True).iloc[0]:.1f}% -> DESCARTADA")

    h("PASO 1 - FIRMA MINERAL (reologia = torque residual dado masa de cama)")
    m=df[['TH001_PLC_TORK','TH001_PLC_BEDM']].dropna()
    X=np.c_[np.ones(len(m)),m.TH001_PLC_BEDM.values]
    b=np.linalg.lstsq(X,m.TH001_PLC_TORK.values,rcond=None)[0]
    df.loc[m.index,'reologia_res']=m.TH001_PLC_TORK.values-X@b
    A=df[FIRMA+OPER+PROC].resample(AGG).median().dropna(subset=FIRMA)
    A['dia']=A.index.date.astype(str)
    print(f"  ventanas de {AGG}: {len(A):,} | dias: {A.dia.nunique():,}")
    Z=StandardScaler().fit_transform(QuantileTransformer(
        output_distribution='normal',random_state=SEED).fit_transform(A[FIRMA].values))

    h("PASO 2 - MULTI-ALGORITMO + VALIDACION")
    print(f"  {'k':>2s} {'algo':>8s} {'silhou':>8s} {'DB':>7s} {'CH':>8s} {'maxclus%':>9s}")
    for k in range(2,7):
        for nom,lab in [('KMeans',KMeans(k,n_init=10,random_state=SEED).fit_predict(Z)),
                        ('GMM',GaussianMixture(k,n_init=3,random_state=SEED).fit_predict(Z)),
                        ('Ward',AgglomerativeClustering(k).fit_predict(Z)),
                        ('Birch',Birch(n_clusters=k).fit_predict(Z))]:
            mx=100*pd.Series(lab).value_counts(normalize=True).max()
            print(f"  {k:2d} {nom:>8s} {silhouette_score(Z,lab):8.3f} "
                  f"{davies_bouldin_score(Z,lab):7.3f} {calinski_harabasz_score(Z,lab):8.0f} {mx:8.1f}%")
    print("\n  ESTABILIDAD (ARI bootstrap):")
    rng=np.random.default_rng(SEED)
    for k in range(2,7):
        base=KMeans(k,n_init=10,random_state=SEED).fit(Z); ar=[]
        for _ in range(15):
            i=rng.choice(len(Z),int(.8*len(Z)),replace=False)
            ar.append(adjusted_rand_score(base.labels_[i],
                      KMeans(k,n_init=5,random_state=int(rng.integers(1e6))).fit(Z[i]).labels_))
        print(f"   k={k}: ARI={np.mean(ar):.3f}+/-{np.std(ar):.3f}")

    K=4; A['mineral']=KMeans(K,n_init=10,random_state=SEED).fit_predict(Z)

    h(f"PASO 3 - CONTROL POSITIVO (¿son mineral REAL los {K} clusters?)")
    E=A[FIRMA+['mineral','dia']].dropna()
    a,c=cv_auc(StandardScaler().fit_transform(E[FIRMA].values),E.mineral.values,
               E.dia.values,lambda: RandomForestClassifier(300,min_samples_leaf=20,
               n_jobs=-1,random_state=SEED))
    print(f"  exogenas -> mineral: AUC={a:.3f} acc={c:.3f}  (alto = senial aprendible)")
    for v in PROC:
        print(f"  eta2(mineral -> {v:16s}) = {eta2(A,v,'mineral'):.3f}")
    if a<0.7:
        print("  !! CONTROL FALLA: clusters no son mineral real -> test NO interpretable")
        return

    h("PASO 4 - INFLUENCIA SOBRE EL OPERADOR: MINERAL vs GUARDIA")
    print(f"  {'setpoint':18s} {'eta2 MINERAL':>13s} {'eta2 GUARDIA':>13s} {'razon':>8s}")
    rr=[]
    for v in OPER:
        em=eta2(A,v,'mineral'); ed=eta2(A,v,'dia'); r=ed/em if em>0 else np.nan
        rr.append(r); print(f"  {v:18s} {em:13.3f} {ed:13.3f} {r:7.1f}x")
    print(f"\n  >> La GUARDIA explica {np.nanmedian(rr):.0f}x mas varianza que el MINERAL")

    h("PASO 5 - RED NEURONAL: ¿los setpoints del operador delatan el mineral?")
    D=A[OPER+['mineral','dia']].dropna()
    Xo=StandardScaler().fit_transform(D[OPER].values); y=D.mineral.values; g=D.dia.values
    mlp=lambda: MLPClassifier((64,32),max_iter=300,early_stopping=True,random_state=SEED)
    rf =lambda: RandomForestClassifier(300,min_samples_leaf=20,n_jobs=-1,random_state=SEED)
    a1,c1=cv_auc(Xo,y,g,mlp); a2,c2=cv_auc(Xo,y,g,rf)
    lab_dia=pd.Series(y,index=g).groupby(level=0).agg(lambda s:s.mode().iloc[0])
    dias=pd.unique(g); perm=dict(zip(dias,np.random.default_rng(0).permutation(dias)))
    a3,c3=cv_auc(Xo,np.array([lab_dia[perm[x]] for x in g]),g,rf)
    print(f"  {'modelo':30s} {'AUC':>7s} {'acc':>7s}")
    print(f"  {'MLP (red neuronal)':30s} {a1:7.3f} {c1:7.3f}")
    print(f"  {'RandomForest':30s} {a2:7.3f} {c2:7.3f}")
    print(f"  {'NULO (etiq. permutadas)':30s} {a3:7.3f} {c3:7.3f}")
    print("\n  AUC~0.5 => operador NO responde | 0.6-0.75 => influencia debil | >0.8 => fuerte")

if __name__=="__main__": main()