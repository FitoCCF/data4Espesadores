# -*- coding: utf-8 -*-
"""
guardias.py (ex `rol_guardias.py`)
================================================================================
Parsea los roles de operaciones C2 (2024-2026) y construye una tabla de turnos
unible al dataset del historiador, para poder atribuir cada registro de proceso
a la dotación que estaba en sala.

ESTRUCTURA VERIFICADA DEL ROL
  - 7 guardias, ciclo base AAAADDDBBBBDDD (14 días).
  - Cada día hay exactamente 2 guardias en turno A, 2 en B y 3 en descanso.
    No hay una sola excepción en los 1096 días de los tres archivos.
  - Solo existen 14 firmas diarias distintas y se repiten con período exacto
    de 14 días. La dotación es una función determinista de la fecha.
  - Los pares en turno A forman un anillo de 7 combinaciones:
    G1+G3, G3+G5, G5+G7, G2+G7, G2+G4, G4+G6, G1+G6.
    Cada par coincide 2 días seguidos y reaparece 12 días después.

POR QUÉ IMPORTA
  Un análisis previo descartó la guardia como driver de régimen probando
  autocorrelación a 12 h, 96 h y 168 h. Ninguno de esos lags corresponde al
  ciclo real: el rol se repite cada 14 días, o sea 336 h. La prueba anterior
  no falsificó la hipótesis de guardia; buscó en el período equivocado.

ADVERTENCIA DE IDENTIFICACIÓN
  Como la dotación es determinista en la fecha, cualquier otro fenómeno con
  período de exactamente 14 días (mantenimiento quincenal, calibración de
  laboratorio, rotación de supervisión) es indistinguible de un efecto de
  guardia. Un resultado positivo aquí es una hipótesis a contrastar contra el
  programa de mantenimiento, no una conclusión.
  Las campañas de mineral (persistencia de 4 días) no son un confusor porque
  no están sincronizadas con el ciclo de 14 días y se promedian.

ALCANCE CONFIRMADO
  C2 = Concentradora 2, que engloba el área 4100. El rol aplica directamente a
  los operadores de los espesadores de relaves; no hace falta un rol aparte.
  Turnos y horas de cambio: `conf/base/reglas_operativas.yaml::turnos`.

Migración 2026-09-06: los horarios de turno (antes `MINUTO_INICIO_A/B`
hardcodeados aquí, duplicando `config_espesadores.py::TURNOS`) y la lista de
variables del diagnóstico (`VARS_INTERES`) ahora salen de la configuración
declarativa — mismos valores, fuente única.

Uso:
    python -m espesadores.dominio.guardias --rol-dir data/00_raw/rol_operaciones \
        --parquet data/00_raw/espesadores_XXXX.parquet
    python -m espesadores.dominio.guardias --rol-dir data/00_raw/rol_operaciones  # solo calendario
"""

import argparse
import os
import re
from datetime import date, datetime

import numpy as np
import pandas as pd

from espesadores.config import TURNOS, VARIABLES_INTERES_GUARDIAS, CICLO_GUARDIA_DIAS, RUTAS

MESES = {'ENERO': 1, 'FEBRERO': 2, 'MARZO': 3, 'ABRIL': 4, 'MAYO': 5, 'JUNIO': 6,
         'JULIO': 7, 'AGOSTO': 8, 'SETIEMBRE': 9, 'SEPTIEMBRE': 9, 'OCTUBRE': 10,
         'NOVIEMBRE': 11, 'DICIEMBRE': 12}
DOW = {'L': 0, 'M': 1, 'MI': 2, 'J': 3, 'V': 4, 'S': 5, 'D': 6}

# Se trabaja en minutos del día porque el cambio de turno NO cae en hora
# exacta; usar solo la hora desplazaría media hora de cada turno a la
# dotación equivocada.
MINUTO_INICIO_A = round(TURNOS["inicio_dia_h"] * 60)
MINUTO_INICIO_B = MINUTO_INICIO_A + round(TURNOS["duracion_h"] * 60)

VARS_INTERES = VARIABLES_INTERES_GUARDIAS


def log(msg):
    print('[{}] {}'.format(datetime.now().strftime('%H:%M:%S'), msg), flush=True)


# =========================================================================== #
# 1. PARSEO
# =========================================================================== #
def parsear_rol(path):
    txt = open(path, encoding='utf-8').read()
    filas = []
    for bloque in re.split(r'^##\s+', txt, flags=re.M)[1:]:
        cab = bloque.split('\n')[0].strip().upper()
        m = re.match(r'([A-ZÁÉÍÓÚ]+)\s+(\d{4})', cab)
        if not m or m.group(1) not in MESES:
            continue
        mes, anio = MESES[m.group(1)], int(m.group(2))
        lineas = [l for l in bloque.split('\n') if l.strip().startswith('|')]
        if len(lineas) < 3:
            continue
        dias = [int(c.strip()) for c in lineas[0].strip('|').split('|')[1:]]
        dow = [c.strip() for c in lineas[1].strip('|').split('|')[1:]]
        for linea in lineas[2:]:
            celdas = [c.strip() for c in linea.strip('|').split('|')]
            guardia = celdas[0].replace('*', '').strip()
            for d, dw, estado in zip(dias, dow, celdas[1:]):
                filas.append({'fecha': date(anio, mes, d), 'dow_doc': dw,
                              'guardia': guardia, 'estado': estado})
    return pd.DataFrame(filas)


def cargar_roles(directorio):
    archivos = sorted(f for f in os.listdir(directorio)
                      if re.match(r'Rol_Operaciones_\d{4}\.md$', f))
    if not archivos:
        raise SystemExit('No se encontraron archivos Rol_Operaciones_YYYY.md en {}'.format(directorio))
    df = pd.concat([parsear_rol(os.path.join(directorio, f)) for f in archivos],
                   ignore_index=True)
    df['fecha'] = pd.to_datetime(df['fecha'])

    mal = df[df['fecha'].dt.dayofweek != df['dow_doc'].map(DOW)]
    if len(mal):
        raise SystemExit('El rol tiene {} celdas cuyo día de semana no coincide '
                         'con el calendario. Revisar los archivos.'.format(len(mal)))
    log('Rol cargado: {} archivos, {} -> {}'.format(
        len(archivos), df['fecha'].min().date(), df['fecha'].max().date()))
    return df


def validar_estructura(piv):
    conteo = pd.DataFrame({s: (piv == s).sum(axis=1) for s in ('A', 'B', 'D')})
    combos = conteo.value_counts()
    log('Dotación diaria (A/B/D): {}'.format(
        {tuple(k): int(v) for k, v in combos.items()}))
    if len(combos) > 1:
        log('  AVISO: la dotación no es constante todos los días.')

    firma = piv.apply(lambda r: ''.join(r.values), axis=1)
    log('Firmas diarias distintas: {} sobre {} días'.format(firma.nunique(), len(firma)))
    idx = firma[firma == firma.iloc[0]].index
    periodos = np.unique(np.diff(idx.values).astype('timedelta64[D]').astype(int))
    log('Período de repetición del patrón: {} días (esperado: {})'.format(
        periodos, CICLO_GUARDIA_DIAS))
    return firma


# =========================================================================== #
# 2. CALENDARIO A NIVEL DE MINUTO
# =========================================================================== #
def construir_calendario(df_rol, inicio, fin, freq='1min'):
    """Índice temporal -> turno y dotación en sala.

    El turno B de la fecha F abarca de HORA_INICIO_B del día F hasta
    HORA_INICIO_A del día F+1. Por eso las horas de madrugada se atribuyen a
    la dotación nocturna del día ANTERIOR, no a la del día calendario.
    """
    piv = df_rol.pivot_table(index='fecha', columns='guardia',
                             values='estado', aggfunc='first')
    firma = validar_estructura(piv)

    corto = {c: c.replace('Guardia ', 'G') for c in piv.columns}
    par_A = piv.apply(lambda r: '+'.join(sorted(corto[c] for c in piv.columns if r[c] == 'A')), axis=1)
    par_B = piv.apply(lambda r: '+'.join(sorted(corto[c] for c in piv.columns if r[c] == 'B')), axis=1)
    log('Pares distintos en A: {} | en B: {}'.format(par_A.nunique(), par_B.nunique()))

    idx = pd.date_range(inicio, fin, freq=freq, inclusive='left')
    cal = pd.DataFrame(index=idx)

    minuto = idx.hour * 60 + idx.minute
    es_dia = (minuto >= MINUTO_INICIO_A) & (minuto < MINUTO_INICIO_B)
    fecha_op = pd.Series(idx.normalize(), index=idx)
    fecha_op[minuto < MINUTO_INICIO_A] -= pd.Timedelta(days=1)

    cal['fecha_operativa'] = fecha_op.values
    cal['turno'] = np.where(es_dia, 'A', 'B')
    cal['dotacion'] = np.where(
        es_dia,
        fecha_op.map(par_A).values,
        fecha_op.map(par_B).values)
    cal['dia_ciclo'] = ((fecha_op - fecha_op.min()).dt.days % CICLO_GUARDIA_DIAS).values
    cal['firma_dia'] = fecha_op.map(firma).values

    sin_rol = cal['dotacion'].isna().sum()
    if sin_rol:
        log('AVISO: {} minutos sin cobertura del rol ({:.2f}%)'.format(
            sin_rol, 100 * sin_rol / len(cal)))
    return cal


# =========================================================================== #
# 3. DIAGNÓSTICO
# =========================================================================== #
def diagnosticar(df, cal):
    comunes = [c for c in VARS_INTERES if c in df.columns]
    log('')
    log('Variables analizadas: {}'.format(comunes))

    d = df[comunes].join(cal[['turno', 'dotacion', 'dia_ciclo']], how='inner')
    log('Registros unidos: {}'.format(len(d)))

    log('')
    log('=== AUTOCORRELACIÓN, INCLUYENDO EL CICLO REAL DE 336 h ===')
    log('  (12 h y 24 h = turno; 336 h = ciclo completo del rol)')
    lags = [12, 24, 72, 96, 168, 336, 672]
    hora = d[comunes].resample('1h').mean()
    filas = []
    for c in comunes:
        s = (hora[c] - hora[c].mean()).dropna()
        if len(s) < max(lags) * 2:
            continue
        fila = {'variable': c}
        for L in lags:
            fila['lag_{}h'.format(L)] = round(s.autocorr(L), 3)
        filas.append(fila)
    if filas:
        print(pd.DataFrame(filas).to_string(index=False))
    log('  Un valor en lag_336h claramente mayor que en 168h y 672h apunta a')
    log('  que el ciclo de rol deja huella. Si 336h no destaca, la hipótesis')
    log('  de guardia queda descartada con la prueba correcta.')

    log('')
    log('=== DIFERENCIAS ENTRE DOTACIONES ===')
    log('  Se compara cada par contra el resto, dentro del mismo turno, para')
    log('  no confundir efecto de dotación con efecto día/noche.')
    for c in comunes:
        sub = d[[c, 'turno', 'dotacion']].dropna()
        if len(sub) < 10000:
            continue
        sub = sub.copy()
        sub['centrado'] = sub[c] - sub.groupby('turno')[c].transform('mean')
        g = sub.groupby('dotacion')['centrado'].agg(['mean', 'std', 'count'])
        g = g[g['count'] > 1000]
        if len(g) < 2:
            continue
        turnos_equiv = g['count'] / (12 * 60)
        g['ee'] = g['std'] / np.sqrt(turnos_equiv.clip(lower=1))
        rango = g['mean'].max() - g['mean'].min()
        sd_global = sub[c].std()
        log('  {:<24} rango entre pares = {:+.3f} ({:.1f}% de 1 sd)'.format(
            c, rango, 100 * rango / sd_global if sd_global else np.nan))
        top = g['mean'].sort_values()
        log('      menor: {} ({:+.3f} ± {:.3f})   mayor: {} ({:+.3f} ± {:.3f})'.format(
            top.index[0], top.iloc[0], g.loc[top.index[0], 'ee'],
            top.index[-1], top.iloc[-1], g.loc[top.index[-1], 'ee']))

    log('')
    log('  RECORDATORIO: la dotación es función determinista de la fecha. Un')
    log('  efecto aquí puede ser de la guardia o de cualquier otra rutina')
    log('  quincenal. Contrastar contra el programa de mantenimiento antes')
    log('  de atribuirlo a las personas.')


# =========================================================================== #
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--rol-dir', default=os.path.dirname(RUTAS["roles_guardia"][0]))
    ap.add_argument('--parquet', default=None)
    ap.add_argument('--salida', default=os.path.join('data', '01_interim', 'calendario_guardias.parquet'))
    args = ap.parse_args()

    df_rol = cargar_roles(args.rol_dir)
    ruta = args.parquet or RUTAS["entrada"]

    if ruta:
        log('Leyendo proceso: {}'.format(ruta))
        df = pd.read_parquet(ruta) if ruta.endswith('.parquet') else pd.read_pickle(ruta)
        inicio, fin = df.index.min(), df.index.max() + pd.Timedelta(minutes=1)
    else:
        log('Sin dataset de proceso: solo se construye el calendario.')
        df = None
        inicio = df_rol['fecha'].min()
        fin = df_rol['fecha'].max() + pd.Timedelta(days=1)

    cal = construir_calendario(df_rol, inicio, fin)
    try:
        cal.to_parquet(args.salida)
        ruta_cal = args.salida
    except Exception as e:
        ruta_cal = os.path.splitext(args.salida)[0] + '.pkl'
        log('Parquet falló ({}); guardando pickle.'.format(type(e).__name__))
        cal.to_pickle(ruta_cal)
    log('Calendario guardado: {} ({} filas)'.format(ruta_cal, len(cal)))

    if df is not None:
        diagnosticar(df, cal)


if __name__ == '__main__':
    main()
