# -*- coding: utf-8 -*-
"""
piscinas.py (ex `nivel_piscinas.py`)
================================================================================
Deriva el nivel real de la piscina de recuperación de agua a partir de los dos
transmisores de `conf/base/tags.yaml::piscinas`, y evalúa el cumplimiento de
las dos reglas operativas de `conf/base/reglas_operativas.yaml::piscinas`.

REGLA FÍSICA (confirmada por el usuario, 2026-09-06)
  Las dos piscinas son un vaso comunicante: los niveles deben ser iguales. Si
  ambos transmisores dan valores parecidos, el valor es válido tal cual. Si
  divergen más de lo normal, eso NO es información sobre el proceso, es una
  falla de instrumento — se toma el MAYOR, porque la falla típica (toma
  tapada, incrustación, deriva) sesga hacia abajo.

  Pero un transmisor también puede fallar HACIA ARRIBA: pegarse en fondo de
  escala o quedar congelado en un valor alto. En ese caso `max()` elegiría
  justamente el sensor malo. Por eso aquí max() se aplica solo después de
  descartar canales saturados o congelados, y toda decisión queda registrada
  en una columna de origen auditable.

REGLAS OPERATIVAS (conf/base/reglas_operativas.yaml::piscinas)
  R1. El nivel nunca debe bajar de `nivel_minimo_pct` (75%).
  R2. Al cierre de cada guardia debe quedar en `nivel_cierre_guardia_pct`
      (90%) o más. Horarios de cambio de guardia: `horas_cambio_guardia`
      (07:30 y 19:30, confirmados con planta — coinciden con
      conf/base/reglas_operativas.yaml::turnos).

Migración 2026-09-06: `COL_A`/`COL_B` y los umbrales estaban hardcodeados en
el script original (`nivel_piscinas.py`); ahora salen de la configuración
declarativa, sin cambiar el comportamiento (mismos valores).

Uso:
    python -m espesadores.dominio.piscinas --parquet data/00_raw/espesadores_XXXX.parquet
"""

import argparse
import os
from datetime import datetime

import numpy as np
import pandas as pd

from espesadores.config import PISCINAS_TAGS, REGLAS_PISCINAS, RUTAS

COL_A = PISCINAS_TAGS["transmisor_a"]   # Nivel piscina 1
COL_B = PISCINAS_TAGS["transmisor_b"]   # Nivel piscina 2

UMBRAL_MINIMO = REGLAS_PISCINAS["nivel_minimo_pct"]          # R1: nunca por debajo
UMBRAL_GUARDIA = REGLAS_PISCINAS["nivel_cierre_guardia_pct"]  # R2: al cierre de guardia
DIVERGENCIA_ALERTA = REGLAS_PISCINAS["umbral_diferencia_grande_pp"]
SATURACION_ALTA = REGLAS_PISCINAS["saturacion_alta_pct"]
SATURACION_BAJA = REGLAS_PISCINAS["saturacion_baja_pct"]
MIN_CONGELADO = REGLAS_PISCINAS["minutos_para_congelado"]

# Cierres de guardia (momento en que aplica R2), a partir de las horas
# confirmadas en reglas_operativas.yaml (07:30 y 19:30).
CIERRES_GUARDIA = tuple(
    tuple(int(x) for x in h.split(":")) for h in REGLAS_PISCINAS["horas_cambio_guardia"]
)


def log(msg):
    print('[{}] {}'.format(datetime.now().strftime('%H:%M:%S'), msg), flush=True)


def marcar_congelado(s, ventana):
    """True donde la señal lleva `ventana` minutos sin cambiar."""
    sin_cambio = (s.diff() == 0)
    return sin_cambio.rolling(ventana, min_periods=ventana).sum() == ventana


def derivar_nivel(df):
    """Devuelve nivel derivado + columnas de auditoría.

    origen indica de dónde salió cada valor:
      'coincide'      ambos sensores de acuerdo (dentro de la tolerancia)
      'max_divergen'  divergen; se tomó el mayor entre canales sanos
      'unico_A'/'B'   solo un canal disponible o sano
      'sin_dato'      ninguno utilizable
    """
    a, b = df[COL_A], df[COL_B]

    mal_a = (a >= SATURACION_ALTA) | (a <= SATURACION_BAJA) | marcar_congelado(a, MIN_CONGELADO)
    mal_b = (b >= SATURACION_ALTA) | (b <= SATURACION_BAJA) | marcar_congelado(b, MIN_CONGELADO)

    ok_a = a.notna() & ~mal_a.fillna(False)
    ok_b = b.notna() & ~mal_b.fillna(False)

    divergencia = (a - b).abs()
    nivel = pd.Series(np.nan, index=df.index)
    origen = pd.Series('sin_dato', index=df.index)

    ambos = ok_a & ok_b
    coincide = ambos & (divergencia <= DIVERGENCIA_ALERTA)
    difieren = ambos & (divergencia > DIVERGENCIA_ALERTA)

    nivel[coincide] = np.maximum(a[coincide], b[coincide])
    origen[coincide] = 'coincide'
    nivel[difieren] = np.maximum(a[difieren], b[difieren])
    origen[difieren] = 'max_divergen'

    solo_a = ok_a & ~ok_b
    solo_b = ok_b & ~ok_a
    nivel[solo_a] = a[solo_a]
    origen[solo_a] = 'unico_A'
    nivel[solo_b] = b[solo_b]
    origen[solo_b] = 'unico_B'

    # Respaldo: si ambos canales fueron descartados pero hay lectura cruda,
    # se conserva el máximo marcado como sospechoso, para no perder el tramo.
    resto = nivel.isna() & (a.notna() | b.notna())
    nivel[resto] = pd.concat([a[resto], b[resto]], axis=1).max(axis=1)
    origen[resto] = 'sospechoso'

    return pd.DataFrame({
        'nivel_piscina': nivel,
        'origen': origen,
        'divergencia': divergencia,
        'canal_A_sano': ok_a,
        'canal_B_sano': ok_b,
    })


def evaluar(df, der):
    n = len(der)
    log('')
    log('=== CALIDAD DE LA DERIVACIÓN ===')
    for k, v in der['origen'].value_counts().items():
        log('  {:<14} {:>9} muestras  ({:.2f}%)'.format(k, v, 100 * v / n))

    div = der['divergencia'].dropna()
    log('  divergencia entre transmisores: p50={:.2f} p95={:.2f} max={:.2f} pp'.format(
        div.median(), div.quantile(0.95), div.max()))
    log('  tiempo con divergencia > {} pp: {:.2f}%'.format(
        DIVERGENCIA_ALERTA, 100 * (div > DIVERGENCIA_ALERTA).mean()))
    log('  NOTA: si la divergencia es alta y persistente, un transmisor está')
    log('        descalibrado. Vale contrastarlo contra la orden de trabajo.')

    niv = der['nivel_piscina']
    log('')
    log('=== R1: nivel nunca por debajo de {:.0f}% ==='.format(UMBRAL_MINIMO))
    valido = niv.dropna()
    bajo = valido < UMBRAL_MINIMO
    log('  tiempo bajo umbral: {:.2f}%  ({} minutos)'.format(
        100 * bajo.mean(), int(bajo.sum())))
    if bajo.any():
        m = bajo.values
        cambios = np.diff(np.concatenate(([0], m.view(np.int8), [0])))
        ini = np.where(cambios == 1)[0]
        fin = np.where(cambios == -1)[0]
        dur = pd.Series(fin - ini)
        log('  episodios: {} | duración p50={:.0f} min, max={:.0f} min'.format(
            len(dur), dur.median(), dur.max()))
        umbral_reportable = REGLAS_PISCINAS["episodio_minimo_reportable_min"]
        reportables = dur[dur >= umbral_reportable]
        log('  episodios reportables a operaciones (>= {} min): {}'.format(
            umbral_reportable, len(reportables)))
        peores = valido[bajo].nsmallest(5)
        log('  mínimos alcanzados:')
        for ts, v in peores.items():
            log('    {}  {:.1f}%'.format(ts, v))

    log('')
    log('=== R2: cierre de guardia en {:.0f}% o más ==='.format(UMBRAL_GUARDIA))
    log('  cierres evaluados a las {}'.format(
        ', '.join('{:02d}:{:02d}'.format(h, m) for h, m in CIERRES_GUARDIA)))
    hm = list(zip(niv.index.hour, niv.index.minute))
    es_cierre = pd.Series([t in CIERRES_GUARDIA for t in hm], index=niv.index)
    cierres = niv[es_cierre].dropna()
    if len(cierres):
        cumple = cierres >= UMBRAL_GUARDIA
        log('  cierres evaluados: {}'.format(len(cierres)))
        log('  cumplimiento     : {:.1f}%'.format(100 * cumple.mean()))
        log('  nivel al cierre  : p10={:.1f} p50={:.1f} p90={:.1f}'.format(
            cierres.quantile(0.1), cierres.median(), cierres.quantile(0.9)))
        hora_cierre_b = CIERRES_GUARDIA[0][0]  # primer cierre del día = entrega de B
        por_turno = cierres.groupby(cierres.index.hour).agg(['mean', 'median', 'count'])
        log('  por turno que entrega:')
        for h, r in por_turno.iterrows():
            etiqueta = 'B (noche)' if h == hora_cierre_b else 'A (día)'
            log('    entrega {:<10} a las {:02d}:30  media {:.1f}%  mediana {:.1f}%  n={}'.format(
                etiqueta, h, r['mean'], r['median'], int(r['count'])))

    # Si R2 se cumple de verdad, el nivel debe tener una firma de 12 h que los
    # parámetros del espesador no tienen. Es una prueba de que la regla se
    # ejecuta, independiente de lo que digan los reportes de guardia.
    log('')
    log('=== FIRMA DE 12 HORAS (la regla R2 debería producirla) ===')
    h = niv.resample('1h').mean()
    h = (h - h.mean()).dropna()
    for lag in (6, 12, 24, 72, 168):
        if len(h) > lag:
            log('  autocorrelación a {:>3} h: {:+.3f}'.format(lag, h.autocorr(lag)))
    log('  Un pico en 12 h y 24 h indica que el ciclo de guardia realmente')
    log('  gobierna el nivel. Su ausencia sugiere que la regla no se ejecuta')
    log('  o que el consumo de planta domina sobre la acción del operador.')

    return der


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--parquet', default=None)
    ap.add_argument('--salida', default=os.path.join('data', '01_interim', 'nivel_piscinas_derivado.parquet'))
    args = ap.parse_args()

    ruta = args.parquet or RUTAS["entrada"]
    log('Leyendo {}'.format(ruta))

    df = pd.read_parquet(ruta) if ruta.endswith('.parquet') else pd.read_pickle(ruta)
    faltan = [c for c in (COL_A, COL_B) if c not in df.columns]
    if faltan:
        raise SystemExit('Faltan columnas en el dataset: {}'.format(faltan))

    log('Cobertura {}: {:.2f}%  |  {}: {:.2f}%'.format(
        COL_A, 100 * df[COL_A].notna().mean(),
        COL_B, 100 * df[COL_B].notna().mean()))

    der = derivar_nivel(df)
    evaluar(df, der)

    der.to_parquet(args.salida)
    log('')
    log('Guardado: {}'.format(args.salida))
    log('Columna nivel_piscina lista para incorporar al pipeline. Conservar')
    log('también la columna origen: sin ella el nivel no es auditable.')


if __name__ == '__main__':
    main()
