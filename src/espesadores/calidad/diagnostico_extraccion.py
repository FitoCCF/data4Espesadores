# -*- coding: utf-8 -*-
"""
diagnostico_extraccion.py
================================================================================
Diagnóstico posterior a la extracción PI. Responde tres preguntas que el log
de extracción deja abiertas y que afectan decisiones del pipeline.

PARTE A (requiere conexión a PI)
  Los tags de rebose salen 67% NaN. ¿Es porque NO hay dato, o porque hay un
  dato marcado como no bueno que `valor_float()` descarta? La distinción es
  crítica: si el PLC escribe una constante de respaldo con calidad degradada,
  ese número existe y se está tirando. Esta parte inspecciona el AFValue crudo
  sin filtrar por IsGood y clasifica cada muestra por estado.

PARTE B (offline, sobre el parquet)
  B1. ¿Los NaN de rebose de TH1/TH2/TH3/G coinciden en el tiempo? Si sí,
      hay una causa común (un bloque de cálculo del PLC), no tres fallas.
  B2. `frac_congelado` del manifiesto se calcula sobre la serie sin NaN, así
      que en tags con 80% de NaN compara muestras NO adyacentes y sobreestima.
      Aquí se recalcula sobre la grilla completa.
  B3. La cobertura salta 90.5% -> 96.6% (dic-2025) y -> 98.4% (abr-2026).
      ¿Qué tags entraron en línea en cada escalón? Importa porque agrupar
      datos de antes y después mezcla regímenes de instrumentación distintos.

Uso:
    python diagnostico_extraccion.py --parte A
    python diagnostico_extraccion.py --parte B --parquet ruta\al\archivo.parquet
================================================================================
"""

import argparse
import os
import sys
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytz

from espesadores.config import EXTRACCION, TAGS_EXTRACCION_PI, RUTAS

# columna -> tag_pi, derivado de la lista maestra (antes hardcodeado aquí como
# un segundo mapeo suelto, con riesgo de desincronizarse del real).
_COLUMNAS_REBOSE = {'FLUJO_REBOSE_AGUA_TH1', 'FLUJO_REBOSE_AGUA_TH2',
                    'FLUJO_REBOSE_AGUA_TH3', 'FLUJO_REBOSE_AGUA_G',
                    'Ratio_concentracion_Output', 'Sol_Overflow_Output'}
TAGS_REBOSE = {columna: tag_pi for tag_pi, columna, _grupo, _desc in TAGS_EXTRACCION_PI
               if columna in _COLUMNAS_REBOSE}

SERVIDOR_NOMBRE    = EXTRACCION["servidor"]
ZONA_HORARIA_LOCAL = EXTRACCION["zona_horaria"]
VENTANA_INICIO     = '2026-08-01 00:00:00'
VENTANA_DIAS       = 7
INTERVALO          = EXTRACCION["intervalo_muestreo"]


def log(msg):
    print('[{}] {}'.format(datetime.now().strftime('%H:%M:%S'), msg), flush=True)


# =========================================================================== #
# PARTE A - inspección de calidad del AFValue crudo
# =========================================================================== #
def parte_A():
    sys.path.append(EXTRACCION["af_sdk_path"])
    import clr
    clr.AddReference('OSIsoft.AFSDK')
    from OSIsoft.AF.PI import PIServers, PIPoint
    from OSIsoft.AF.Time import AFTime, AFTimeSpan, AFTimeRange

    tz = pytz.timezone(ZONA_HORARIA_LOCAL)
    t0 = tz.localize(datetime.strptime(VENTANA_INICIO, '%Y-%m-%d %H:%M:%S'))
    t1 = t0 + timedelta(days=VENTANA_DIAS)

    server = PIServers()[SERVIDOR_NOMBRE]
    if not server.ConnectionInfo.IsConnected:
        server.Connect()
    log('Conectado. Ventana: {} -> {}'.format(t0, t1))

    intervalo = AFTimeSpan.Parse(INTERVALO)
    rango = AFTimeRange(AFTime(t0.isoformat()), AFTime(t1.isoformat()))

    resumen = []
    for col, tag in TAGS_REBOSE.items():
        try:
            p = PIPoint.FindPIPoint(server, tag)
            vals = p.InterpolatedValues(rango, intervalo, None, False)
        except Exception as e:
            log('{}: no se pudo leer ({})'.format(col, e))
            continue

        n = n_good = n_bad = n_digital = n_numerico_no_good = 0
        estados = {}
        numeros_no_good = []

        for v in vals:
            n += 1
            try:
                es_bueno = bool(v.IsGood)
            except Exception:
                es_bueno = True
            raw = v.Value

            if hasattr(raw, 'Name'):
                # Estado digital: se registra el nombre para identificar la causa
                n_digital += 1
                nombre = str(raw.Name)
                estados[nombre] = estados.get(nombre, 0) + 1
                continue

            if es_bueno:
                n_good += 1
            else:
                n_bad += 1
                # AQUÍ está la pregunta clave: ¿hay un número detrás de un
                # valor marcado como no bueno? Si lo hay, valor_float() lo tira.
                try:
                    numeros_no_good.append(float(raw))
                    n_numerico_no_good += 1
                except Exception:
                    pass

        fila = {
            'columna': col,
            'n_muestras': n,
            'pct_buenos': round(100.0 * n_good / n, 2) if n else np.nan,
            'pct_no_buenos': round(100.0 * n_bad / n, 2) if n else np.nan,
            'pct_estado_digital': round(100.0 * n_digital / n, 2) if n else np.nan,
            'n_numerico_pese_a_no_bueno': n_numerico_no_good,
            'estados_digitales': estados,
        }
        if numeros_no_good:
            arr = np.array(numeros_no_good)
            fila['valor_no_bueno_unicos'] = int(len(np.unique(arr)))
            fila['valor_no_bueno_min'] = float(arr.min())
            fila['valor_no_bueno_max'] = float(arr.max())
        resumen.append(fila)

        log('{:<28} buenos {:.1f}% | no buenos {:.1f}% | digital {:.1f}%'.format(
            col, fila['pct_buenos'], fila['pct_no_buenos'], fila['pct_estado_digital']))
        if estados:
            log('    estados digitales: {}'.format(estados))
        if numeros_no_good:
            log('    OJO: {} muestras traen NÚMERO pese a estar marcadas no buenas '
                '({} valores únicos, rango {:.3f} a {:.3f})'.format(
                    n_numerico_no_good, fila['valor_no_bueno_unicos'],
                    fila['valor_no_bueno_min'], fila['valor_no_bueno_max']))

    server.Disconnect()

    df = pd.DataFrame(resumen)
    carpeta = os.path.join(RUTAS["salidas"], "diagnosticos")
    os.makedirs(carpeta, exist_ok=True)
    ruta = os.path.join(carpeta, 'diagnostico_calidad_rebose.csv')
    df.to_csv(ruta, index=False, encoding='utf-8-sig')
    log('Guardado: {}'.format(ruta))
    log('')
    log('INTERPRETACIÓN:')
    log('  - Si "pct_estado_digital" es alto -> el tag realmente no tiene dato;')
    log('    el "congelamiento" histórico era artefacto del ffill. El nombre del')
    log('    estado digital identifica la causa (I/O Timeout, Calc Failed, etc).')
    log('  - Si "n_numerico_pese_a_no_bueno" es alto -> hay una constante de')
    log('    respaldo real que valor_float() está descartando. En ese caso hay')
    log('    que relajar el filtro IsGood y marcar la calidad en una columna')
    log('    aparte, no perder el número.')
    return df


# =========================================================================== #
# PARTE B - análisis offline del parquet
# =========================================================================== #
def parte_B(ruta_parquet):
    log('Leyendo {}'.format(ruta_parquet))
    df = pd.read_parquet(ruta_parquet)
    log('{} filas x {} columnas'.format(len(df), df.shape[1]))

    # ---- B1: ¿coinciden los huecos de rebose entre espesadores? ---------- #
    cols_reb = [c for c in ('FLUJO_REBOSE_AGUA_TH1', 'FLUJO_REBOSE_AGUA_TH2',
                            'FLUJO_REBOSE_AGUA_TH3', 'FLUJO_REBOSE_AGUA_G')
                if c in df.columns]
    log('')
    log('B1. Coincidencia temporal de los huecos de rebose')
    log('    (Jaccard = 1.0 significa huecos idénticos -> causa común)')
    masks = {c: df[c].isna() for c in cols_reb}
    jac = pd.DataFrame(index=cols_reb, columns=cols_reb, dtype=float)
    for a in cols_reb:
        for b in cols_reb:
            inter = (masks[a] & masks[b]).sum()
            union = (masks[a] | masks[b]).sum()
            jac.loc[a, b] = round(inter / union, 4) if union else np.nan
    print(jac.to_string())

    todos = np.logical_and.reduce([masks[c].values for c in cols_reb])
    alguno = np.logical_or.reduce([masks[c].values for c in cols_reb])
    log('    NaN simultáneo en los {} tags: {:.2f}% de las filas'.format(
        len(cols_reb), 100.0 * todos.mean()))
    log('    NaN en al menos uno        : {:.2f}% de las filas'.format(
        100.0 * alguno.mean()))

    # Duración de los episodios de hueco del tag principal
    if 'FLUJO_REBOSE_AGUA_TH1' in df.columns:
        m = df['FLUJO_REBOSE_AGUA_TH1'].isna().values
        cambios = np.diff(np.concatenate(([0], m.view(np.int8), [0])))
        ini = np.where(cambios == 1)[0]
        fin = np.where(cambios == -1)[0]
        dur = pd.Series(fin - ini)
        log('    Episodios de hueco en TH1: {} episodios'.format(len(dur)))
        log('      duración (min) p50={:.0f} p90={:.0f} max={:.0f}'.format(
            dur.median(), dur.quantile(0.9), dur.max()))
        # Un patrón periódico regular apunta a un ciclo de ejecución del PLC,
        # no a fallas aleatorias de instrumento.
        log('      duraciones más frecuentes: {}'.format(
            dict(dur.value_counts().head(5))))

    # ---- B2: frac_congelado honesto, sobre la grilla completa ------------ #
    log('')
    log('B2. Fracción congelada recalculada sobre la grilla COMPLETA')
    log('    (el manifiesto la calcula tras dropna, lo que en tags con muchos')
    log('     NaN compara muestras no adyacentes y sobreestima)')
    filas = []
    for c in df.columns:
        s = df[c]
        adyacente_igual = (s.diff() == 0) & s.notna() & s.shift().notna()
        denom = (s.notna() & s.shift().notna()).sum()
        filas.append({
            'columna': c,
            'pct_nan': round(100.0 * s.isna().mean(), 2),
            'frac_cong_manifiesto': round(float((s.dropna().diff() == 0).mean()), 4),
            'frac_cong_adyacente': round(float(adyacente_igual.sum() / denom), 4) if denom else np.nan,
            'n_unicos': int(s.nunique()),
        })
    comp = pd.DataFrame(filas)
    comp['sobreestimacion'] = (comp['frac_cong_manifiesto'] - comp['frac_cong_adyacente']).round(4)
    peores = comp.reindex(comp['sobreestimacion'].abs().sort_values(ascending=False).index)
    print(peores.head(12).to_string(index=False))

    # ---- B3: ¿qué tags entraron en línea en cada escalón de cobertura? --- #
    log('')
    log('B3. Cobertura mensual por tag: identificar los escalones')
    cob = df.notna().groupby(pd.Grouper(freq='MS')).mean()
    global_mes = cob.mean(axis=1)
    log('    Cobertura global por mes:')
    for ts, v in global_mes.items():
        log('      {}  {:.1f}%'.format(ts.strftime('%Y-%m'), 100 * v))

    # Tags cuya disponibilidad cambia de forma abrupta
    salto = (cob.diff().abs().max() * 100).sort_values(ascending=False)
    log('    Tags con mayor salto mensual de disponibilidad:')
    for c, v in salto.head(12).items():
        mes = cob[c].diff().abs().idxmax()
        antes = cob[c].shift().loc[mes] * 100
        despues = cob[c].loc[mes] * 100
        log('      {:<28} {:.0f}% -> {:.0f}% en {}'.format(
            c, antes, despues, mes.strftime('%Y-%m')))

    carpeta = os.path.join(RUTAS["salidas"], "diagnosticos")
    os.makedirs(carpeta, exist_ok=True)
    ruta = os.path.join(carpeta, 'diagnostico_cobertura_mensual.csv')
    ruta_congelamiento = os.path.join(carpeta, 'diagnostico_congelamiento.csv')
    (cob * 100).round(2).to_csv(ruta, encoding='utf-8-sig')
    comp.to_csv(ruta_congelamiento, index=False, encoding='utf-8-sig')
    log('')
    log('Guardados: {} y {}'.format(ruta, ruta_congelamiento))
    return comp, cob


# =========================================================================== #
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--parte', choices=['A', 'B'], required=True)
    ap.add_argument('--parquet', default=None,
                    help='Ruta al parquet de la extracción (requerido para la parte B)')
    args = ap.parse_args()

    if args.parte == 'A':
        parte_A()
    else:
        ruta = args.parquet or RUTAS["entrada"]
        if not args.parquet:
            log('Usando el dataset canónico configurado: {}'.format(ruta))
        parte_B(ruta)


if __name__ == '__main__':
    main()