# -*- coding: utf-8 -*-
"""E10 - Ventanas operativas óptimas."""
import numpy as np
import pandas as pd

from espesadores.config import PISCINAS_TAGS
from espesadores.dominio.piscinas import derivar_nivel
from .comun import log, titulo, guardar, prueba_diferencia


def e10_ventanas(df, cfg, ctx):
    """
    Calcula la ventana operativa que maximiza la recuperación, y verifica si
    esa ventana cambia según el tipo de mineral.

    MÉTODO: dentro de cada tipo de mineral (para no confundir mineral con
    operación) se parte la operación en tercios según recuperación y se
    describe el tercio SUPERIOR con percentiles 10-90 de cada parámetro.
    Esa es la ventana: el rango en que vive la planta cuando recupera más
    agua.

    La clasificación objetivo/bomba/sin_efecto de la válvula de alimentación
    y del floculante YA NO es una suposición fija: se prueba con
    `prueba_diferencia` (mediana del tercio ALTA vs BAJA + p-valor por
    permutación) y solo se promueve a "objetivo" si la diferencia es
    estadísticamente significativa. La presión de cama, ya clasificada como
    objetivo, se valida con la misma prueba para que el one-pager muestre la
    evidencia, no solo la etiqueta.
    """
    titulo("E10 - VENTANAS OPERATIVAS OPTIMAS")

    objetivo = [cfg["presion_cama"], cfg["torque"], cfg["nivel_interfaz"],
                cfg["flujo_alim"], "wt_activo"]
    bombas = ["vel_descarga", "vel_cizalle"]
    sin_efecto = [cfg["floculante"], cfg["valvula_alim"]]
    todos = [c for c in objetivo + bombas + sin_efecto if c in df.columns]

    ventanas_por_mineral = {}
    resumen = []
    partes_alta, partes_baja = [], []
    tipos = sorted([t for t in df["mineral"].unique() if t >= 0]) if ctx.get("mineral_ok") else [0]
    if not ctx.get("mineral_ok"):
        df = df.assign(mineral=0)

    for tipo in tipos:
        g = df[df["mineral"] == tipo].copy()
        if len(g) < 500:
            continue
        g["nivel_rec"] = pd.qcut(g["recuperacion"], 3,
                                 labels=["BAJA", "MEDIA", "ALTA"], duplicates="drop")
        alta = g[g["nivel_rec"] == "ALTA"]
        baja = g[g["nivel_rec"] == "BAJA"]
        partes_alta.append(alta)
        partes_baja.append(baja)
        brecha_rec = 100 * (alta.recuperacion.mean() - baja.recuperacion.mean())
        # El rebose ABSOLUTO escala con el tonelaje (corr +0.98): la ganancia
        # se calcula A TONELAJE CONSTANTE (brecha de recuperacion x agua de
        # alimentacion de referencia), no restando promedios de tercios con
        # distinto tonelaje.
        agua_ref = g.agua_alim.median()
        brecha_reb = (alta.recuperacion.mean() - baja.recuperacion.mean()) * agua_ref
        log(f"  --- Tipo de mineral {tipo}: n={len(g):,} "
            f"({100*len(g)/len(df):.0f}% del tiempo) ---")
        log(f"      recuperacion ALTA={100*alta.recuperacion.mean():.1f}%  "
            f"BAJA={100*baja.recuperacion.mean():.1f}%  brecha={brecha_rec:.1f} puntos")
        log(f"      tonelaje ALTA={alta.ton_espesador.mean():.0f}  "
            f"BAJA={baja.ton_espesador.mean():.0f} t/h  "
            f"(si difieren, el rebose absoluto NO es comparable)")
        log(f"      ganancia a tonelaje constante: {brecha_reb:+.0f} m3/h "
            f"(agua alim ref = {agua_ref:.0f} m3/h)")
        v = {}
        for col in todos:
            s = alta[col].dropna()
            if len(s) < 50:
                continue
            v[col] = {"min": round(float(s.quantile(.10)), 2),
                      "max": round(float(s.quantile(.90)), 2),
                      "objetivo": round(float(s.median()), 2),
                      "actual": round(float(g[col].median()), 2)}
        ventanas_por_mineral[tipo] = v
        resumen.append({"mineral": tipo, "n": len(g),
                        "rec_alta": round(100*alta.recuperacion.mean(), 1),
                        "rec_baja": round(100*baja.recuperacion.mean(), 1),
                        "brecha_pts": round(brecha_rec, 1),
                        "brecha_m3h": round(brecha_reb, 0)})

    guardar(pd.DataFrame(resumen).set_index("mineral"),
            "E10a_brecha_por_mineral.csv", ctx["salidas"])

    log("")
    log("  ¿Cambia la ventana optima segun el mineral?")
    log(f"  {'parametro':22s}" + "".join(f"{'Tipo '+str(t):>10s}" for t in ventanas_por_mineral)
        + f"{'rango':>9s}")
    difs = []
    for col in todos:
        vals = [ventanas_por_mineral[t][col]["objetivo"]
                for t in ventanas_por_mineral if col in ventanas_por_mineral[t]]
        if len(vals) < len(ventanas_por_mineral):
            continue
        rango = max(vals) - min(vals)
        difs.append({"parametro": col, "rango_entre_minerales": round(rango, 2),
                     "objetivo_medio": round(float(np.mean(vals)), 2)})
        log(f"  {col:22s}" + "".join(f"{x:10.2f}" for x in vals) + f"{rango:9.2f}")
    D = pd.DataFrame(difs)
    guardar(D.set_index("parametro"), "E10b_regimenes_por_mineral.csv", ctx["salidas"])

    # --- ¿La válvula de alimentación y el floculante SÍ son variables
    # objetivo? Antes se asumía que no (sin_efecto hardcodeado). Se prueba
    # con la diferencia de medianas ALTA vs BAJA (agrupado dentro de cada
    # tipo de mineral, luego junto para la prueba) + p-valor por
    # permutación. Se valida también la presión de cama (ya objetivo) para
    # mostrar la evidencia, no solo la etiqueta. ---
    ALTA = pd.concat(partes_alta) if partes_alta else df.iloc[0:0]
    BAJA = pd.concat(partes_baja) if partes_baja else df.iloc[0:0]

    candidatos = {cfg["valvula_alim"]: "sin_efecto", cfg["floculante"]: "sin_efecto",
                  cfg["presion_cama"]: "objetivo"}
    candidatos = {c: clase0 for c, clase0 in candidatos.items() if c in df.columns}

    log("")
    log("  ¿La valvula de alimentacion es realmente una variable objetivo?")
    log("  (mediana del tercio ALTA vs BAJA de recuperacion, prueba por permutacion)")
    log(f"  {'variable':22s} {'mediana ALTA':>13s} {'mediana BAJA':>13s} {'p-valor':>9s} {'veredicto':>12s}")
    prueba_candidatos = {}
    promovidos = set()
    for col, clase0 in candidatos.items():
        r = prueba_diferencia(ALTA[col], BAJA[col])
        r["clase_previa"] = clase0
        # La promocion exige relevante (significativo Y magnitud >= 3% del
        # rango operativo), no solo p<0.05: con ~450k filas hasta el ruido
        # es "significativo" por puro tamaño de muestra.
        if clase0 == "sin_efecto" and r["relevante"]:
            r["clase_nueva"] = "objetivo"
            promovidos.add(col)
        else:
            r["clase_nueva"] = clase0
        prueba_candidatos[col] = r
        veredicto = ("PROMOVIDA a objetivo" if col in promovidos
                     else "confirma objetivo" if clase0 == "objetivo" and r["relevante"]
                     else "sin efecto (confirmado)" if clase0 == "sin_efecto"
                     else "diferencia significativa pero no relevante" if r["significativo"]
                     else "sin diferencia significativa")
        log(f"  {col:22s} {r['mediana_a']:13} {r['mediana_b']:13} {r['p_valor']:9} {veredicto:>12s}")
    guardar(pd.DataFrame(prueba_candidatos).T, "E10d_prueba_variables_candidatas.csv", ctx["salidas"])

    # --- Métricas secundarias de recuperación de agua: nivel de piscina
    # (LIT_106/LIT_107, `dominio/piscinas.py`) y FIT_114 (flujo hacia
    # piscinas desde los tanques temporales). Ambas son PLANTA, no del
    # espesador individual: reciben el rebose de los TRES espesadores más
    # agua externa (FIT_123/FIT_601, ver tags.yaml). La comparación es sobre
    # los mismos timestamps que el tercio ALTA/BAJA de ESTE espesador, así
    # que un resultado positivo es corroborativo, no una atribución
    # exclusiva a este equipo. ---
    log("")
    log("  Metricas secundarias de recuperacion (nivel de piscina y FIT_114)")
    log("  AVISO: la piscina y FIT_114 son de planta, compartidos por los 3 espesadores.")
    metricas_secundarias = {}
    tags_pi = [t for t in (PISCINAS_TAGS["transmisor_a"], PISCINAS_TAGS["transmisor_b"])
               if t in df.columns]
    if len(tags_pi) == 2:
        nivel = derivar_nivel(df)["nivel_piscina"]
        r = prueba_diferencia(nivel.reindex(ALTA.index), nivel.reindex(BAJA.index))
        metricas_secundarias["nivel_piscina"] = r
        log(f"  {'nivel_piscina (LIT_106/107)':28s} ALTA={r['mediana_a']}%  "
            f"BAJA={r['mediana_b']}%  p={r['p_valor']}  relevante={r['relevante']}")
    if "FIT_114" in df.columns:
        r = prueba_diferencia(df["FIT_114"].reindex(ALTA.index), df["FIT_114"].reindex(BAJA.index))
        metricas_secundarias["FIT_114"] = r
        log(f"  {'FIT_114 (flujo hacia piscinas)':28s} ALTA={r['mediana_a']}  "
            f"BAJA={r['mediana_b']}  p={r['p_valor']}  relevante={r['relevante']}")
    if metricas_secundarias:
        guardar(pd.DataFrame(metricas_secundarias).T,
                "E10e_metricas_secundarias_recuperacion.csv", ctx["salidas"])
    ctx["metricas_secundarias"] = metricas_secundarias

    consolidada = {}
    for col in todos:
        mins = [ventanas_por_mineral[t][col]["min"] for t in ventanas_por_mineral
                if col in ventanas_por_mineral[t]]
        maxs = [ventanas_por_mineral[t][col]["max"] for t in ventanas_por_mineral
                if col in ventanas_por_mineral[t]]
        objs = [ventanas_por_mineral[t][col]["objetivo"] for t in ventanas_por_mineral
                if col in ventanas_por_mineral[t]]
        if not mins:
            continue
        consolidada[col] = {
            "min": round(float(np.median(mins)), 2),
            "max": round(float(np.median(maxs)), 2),
            "objetivo": round(float(np.median(objs)), 2),
            "actual": round(float(df[col].median()), 2),
            "escala_min": round(float(df[col].quantile(.01)), 2),
            "escala_max": round(float(df[col].quantile(.99)), 2),
            "clase": ("objetivo" if (col in objetivo or col in promovidos) else
                      "bomba" if col in bombas else "sin_efecto"),
        }
    C = pd.DataFrame(consolidada).T
    guardar(C, "E10c_ventana_consolidada.csv", ctx["salidas"])
    log("")
    log("  VENTANA CONSOLIDADA (aplicable a todo tipo de mineral):")
    log(f"  {'parametro':22s} {'min':>8s} {'objetivo':>9s} {'max':>8s} {'actual':>8s} {'clase':>10s}")
    for col, r in consolidada.items():
        log(f"  {col:22s} {r['min']:8.2f} {r['objetivo']:9.2f} {r['max']:8.2f} "
            f"{r['actual']:8.2f} {r['clase']:>10s}")

    ctx["ventanas"] = consolidada
    ctx["ventanas_por_mineral"] = ventanas_por_mineral
    ctx["brecha"] = pd.DataFrame(resumen)
    ctx["prueba_candidatos"] = prueba_candidatos
    ctx["candidatos_promovidos"] = promovidos
    return df
