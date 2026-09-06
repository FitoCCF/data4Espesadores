# -*- coding: utf-8 -*-
"""
extraccion_pi_espesadores.py
================================================================================
Extracción de datos históricos desde PI System (AF SDK) para los tres
espesadores de relaves del Área 4100 (TH-001, TH-002, TH-003).

Salida diseñada como INSUMO CRUDO del pipeline `pipeline_espesadores_v2.py`
(etapas E00-E11). Este script NO limpia, NO imputa y NO rellena: entrega la
grilla temporal completa con NaN explícitos donde el historiador no devolvió
dato bueno. La detección de tags congelados, gaps y estado estacionario es
responsabilidad de E00-E02, no de la extracción.

CORRECCIONES RESPECTO DE LA VERSIÓN ORIGINAL
--------------------------------------------------------------------------------
  1. Clave duplicada en `tags_config`: '_293200_Alim_Total_PB01_ABB' aparecía
     dos veces. Python conservaba solo la última, de modo que Alim_Total_PB01
     desaparecía y Alim_Total_PB02 quedaba apuntando al tag del Molino 1.
     Los tags ahora se declaran como LISTA de tuplas y `validar_tags()` aborta
     ante cualquier duplicado. Tag de PB02 confirmado por el usuario.
  2. Se eliminó `df.ffill().bfill()`. Ese relleno enmascaraba justamente el
     hallazgo de tags de rebose congelados ~67% del tiempo por constante de
     respaldo del PLC.
  3. Namespace de PIPagingConfiguration / PIPageType: OSIsoft.AF.PI, no
     OSIsoft.AF.Data (verificado en la instalación destino).
  4. Extracción BULK vía PIPointList en lugar de un round-trip por tag.
  5. Troceado temporal con checkpoint en disco y reanudación: una caída en el
     mes 20 no obliga a re-extraer los 19 anteriores.
  6. Grilla temporal canónica por bloque: índice idéntico en todas las
     columnas, sin outer-join disperso por desalineación de timestamps.
  7. Manifiesto de auditoría por tag y verificación de continuidad temporal.

Requisitos: Python 3.x con pythonnet, pandas, numpy, pytz; PI AF SDK instalado
y permisos de lectura sobre el PI Data Archive.
================================================================================
"""

import os
import sys
import json
import time
import traceback
from datetime import datetime, timedelta

import pytz
import numpy as np
import pandas as pd

# pythonnet 3.x hospeda .NET Core por defecto (clr_loader elige coreclr si no
# se le pide otra cosa). El AF SDK de OSIsoft es .NET Framework clásico: bajo
# coreclr, `clr.AddReference('OSIsoft.AFSDK')` falla con
# System.IO.FileNotFoundException aunque el DLL exista en el path correcto
# (confirmado 2026-09-06: mismo `sys.path.append` + `AddReference` que
# funcionaban en el notebook original, con pythonnet 2.x — ahí sí hablaba con
# .NET Framework por default). Hay que pedir el runtime "netfx" ANTES del
# primer `import clr` del proceso; después de eso queda fijo.
import pythonnet
pythonnet.load('netfx')

import clr
import System

from espesadores.config import EXTRACCION, TAGS_EXTRACCION_PI, TAGS_DIGITALES

# --------------------------------------------------------------------------- #
# 1. CARGA DEL AF SDK
# --------------------------------------------------------------------------- #
# Ruta específica de esta máquina — sale de conf/local/extraccion.local.yaml,
# no del código (antes hardcodeada aquí).
sys.path.append(EXTRACCION["af_sdk_path"])
clr.AddReference('OSIsoft.AFSDK')

from OSIsoft.AF.PI import PIServers, PIPoint, PIPointList, PICommonPointAttributes
from OSIsoft.AF.Time import AFTime, AFTimeSpan, AFTimeRange

# --- Resolución de la API de extracción masiva ----------------------------- #
# PIPagingConfiguration y PIPageType viven en OSIsoft.AF.PI en esta instalación
# (verificado por reflexión). Se prueba también OSIsoft.AF.Data porque algunas
# builds los exponen ahí. Adicionalmente se comprueba que pythonnet exponga
# PIPointList.InterpolatedValues, que en C# es un extension method y no todas
# las versiones de pythonnet lo publican como método de instancia.
# Si algo falta, el script usa la ruta tag-por-tag: más lenta, mismo resultado.
PIPagingConfiguration = None
PIPageType = None
BULK_DISPONIBLE = False
_NS_PAGING = 'no encontrado'

for _ns in ('OSIsoft.AF.PI', 'OSIsoft.AF.Data'):
    try:
        _mod = __import__(_ns, fromlist=['PIPagingConfiguration', 'PIPageType'])
        PIPagingConfiguration = getattr(_mod, 'PIPagingConfiguration')
        PIPageType = getattr(_mod, 'PIPageType')
        BULK_DISPONIBLE = True
        _NS_PAGING = _ns
        break
    except Exception:
        continue

if BULK_DISPONIBLE and not hasattr(PIPointList(), 'InterpolatedValues'):
    BULK_DISPONIBLE = False
    _NS_PAGING = 'tipos hallados pero extension method no expuesto por pythonnet'


# =========================================================================== #
# 2. PARÁMETROS CONFIGURABLES — desde conf/base/extraccion.yaml (antes
#    hardcodeados aquí; ver docs/plan_migracion.md §2).
# =========================================================================== #
SERVIDOR_NOMBRE     = EXTRACCION["servidor"]
ZONA_HORARIA_LOCAL  = EXTRACCION["zona_horaria"]   # UTC-5 fijo desde 1994, sin DST

FECHA_INICIO        = EXTRACCION["rango"]["inicio"]
FECHA_FIN           = EXTRACCION["rango"]["fin"]   # None => ahora

# Prueba de humo: recorta la corrida a pocos días para validar tags, intervalo
# y continuidad antes de lanzar la extracción completa (Principio #8).
MODO_PRUEBA         = EXTRACCION["modo_prueba"]
DIAS_PRUEBA         = EXTRACCION["dias_prueba"]

# En notación PI 'm' = minutos y 'mo' = meses. Usar minúscula.
# El script imprime el TimeSpan parseado para que se verifique antes de correr.
INTERVALO_MUESTREO  = EXTRACCION["intervalo_muestreo"]

TIMEOUT_MS          = EXTRACCION["timeout_ms"]

# Días por bloque de extracción.
#   15 d x 1440 min x 68 tags ~= 1.47 M valores por bloque.
#   Bajar si el servidor devuelve timeouts; subir si va holgado.
CHUNK_DIAS          = EXTRACCION["chunk_dias"]
PAGE_SIZE           = EXTRACCION["page_size"]      # tags por página en la llamada bulk

MAX_REINTENTOS      = EXTRACCION["max_reintentos"]
ESPERA_REINTENTO_S  = EXTRACCION["espera_reintento_s"]

DIR_SALIDA          = EXTRACCION["rutas"]["salida"]
# Los chunks de prueba van a su propia carpeta: no deben mezclarse nunca con
# los de la corrida completa.
DIR_CHUNKS          = os.path.join(EXTRACCION["rutas"]["chunks"], '_chunks_prueba' if MODO_PRUEBA else '_chunks')
REANUDAR            = True             # omitir bloques ya guardados en disco
EXPORTAR_CSV        = EXTRACCION["rutas"]["exportar_csv"]   # el CSV de 1.1M x 68 supera 1 GB
DTYPE_SALIDA        = EXTRACCION["rutas"]["dtype_salida"]   # 'float32' reduce memoria a la mitad


# =========================================================================== #
# 3. DEFINICIÓN DE TAGS — desde conf/base/tags.yaml::extraccion_pi (antes
#    lista de tuplas embebida aquí; ver docs/plan_migracion.md §2 y el
#    hallazgo H-A: la clave duplicada que este cambio de estructura busca
#    hacer imposible de reintroducir sin que `validar_tags()` lo note).
# =========================================================================== #
TAGS = TAGS_EXTRACCION_PI
# TAGS_DIGITALES ya quedó importado de espesadores.config arriba: columnas
# cuyo PIPoint es digital (AFEnumerationValue) — se guarda el CÓDIGO numérico
# del estado en lugar de NaN.


# =========================================================================== #
# 4. UTILIDADES
# =========================================================================== #
def log(msg):
    print('[{}] {}'.format(datetime.now().strftime('%H:%M:%S'), msg), flush=True)


def freq_pandas():
    """'1m' (notación PI) -> '1min' (notación pandas)."""
    return INTERVALO_MUESTREO.replace('m', 'min')


def validar_tags(tags):
    """Aborta si hay tags o columnas repetidas. Previene el bug del dict."""
    problemas = []
    for campo, idx in (('tag PI', 0), ('columna', 1)):
        vistos, dup = set(), set()
        for t in tags:
            if t[idx] in vistos:
                dup.add(t[idx])
            vistos.add(t[idx])
        if dup:
            problemas.append('{} duplicad@s: {}'.format(campo, sorted(dup)))
    if problemas:
        raise ValueError('Configuración de tags inválida -> ' + ' | '.join(problemas))
    log('Validación de tags OK: {} tags únicos.'.format(len(tags)))


def bloques_tiempo(inicio, fin, dias):
    """Bloques semiabiertos [t0, t1) encadenados: sin huecos ni traslapes."""
    t0 = inicio
    while t0 < fin:
        t1 = min(t0 + timedelta(days=dias), fin)
        yield t0, t1
        t0 = t1


def guardar_df(df, ruta_sin_ext):
    """Parquet si hay motor disponible; pickle como respaldo.

    Existe un choque conocido pandas 3.0 / pyarrow 24 al escribir parquet;
    el respaldo evita perder un bloque ya descargado por un problema de I/O.
    """
    try:
        ruta = ruta_sin_ext + '.parquet'
        df.to_parquet(ruta, compression='zstd')
        return ruta
    except Exception as e:
        log('  Parquet falló ({}). Guardando pickle.'.format(type(e).__name__))
        ruta = ruta_sin_ext + '.pkl'
        df.to_pickle(ruta)
        return ruta


def leer_df(ruta):
    return pd.read_parquet(ruta) if ruta.endswith('.parquet') else pd.read_pickle(ruta)


def ruta_chunk_existente(base):
    for ext in ('.parquet', '.pkl'):
        if os.path.exists(base + ext):
            return base + ext
    return None


def valor_float(afvalue, digital=False):
    """AFValue -> float.

    Nulos y valores 'no buenos' -> NaN, siempre.
    Estados digitales -> NaN en tags analógicos; CÓDIGO numérico del estado en
    tags declarados en TAGS_DIGITALES. Sin esto, un punto digital como el
    estado del sistema experto se extraería como una columna 100% NaN.
    """
    try:
        if not afvalue.IsGood:
            return float('nan')
    except Exception:
        pass
    v = afvalue.Value
    if v is None:
        return float('nan')
    if hasattr(v, 'Name'):          # AFEnumerationValue (Digital State)
        if digital:
            try:
                return float(v.Value)
            except Exception:
                return float('nan')
        return float('nan')
    try:
        return float(v)
    except Exception:
        return float('nan')


# =========================================================================== #
# 5. CONEXIÓN Y RESOLUCIÓN DE PUNTOS
# =========================================================================== #
def conectar():
    server = PIServers()[SERVIDOR_NOMBRE]
    ts = System.TimeSpan.FromMilliseconds(TIMEOUT_MS)
    for prop in ('TimeOut', 'OperationTimeOut'):
        try:
            setattr(server.ConnectionInfo, prop, ts)
        except Exception:
            log('  Aviso: no se pudo fijar ConnectionInfo.{}'.format(prop))
    if not server.ConnectionInfo.IsConnected:
        server.Connect()
    log('Conectado a {} (timeout {} ms)'.format(server.Name, TIMEOUT_MS))
    return server


def resolver_puntos(server):
    """Busca cada PIPoint una sola vez. Devuelve (dict col->point, meta)."""
    puntos, meta = {}, []
    for tag_pi, col, grupo, desc in TAGS:
        registro = {'tag_pi': tag_pi, 'columna': col, 'grupo': grupo,
                    'descripcion': desc, 'encontrado': False,
                    'unidades': '', 'descriptor_pi': ''}
        try:
            p = PIPoint.FindPIPoint(server, tag_pi)
            puntos[col] = p
            registro['encontrado'] = True
            try:
                registro['unidades'] = str(
                    p.GetAttribute(PICommonPointAttributes.EngineeringUnits) or '')
                registro['descriptor_pi'] = str(
                    p.GetAttribute(PICommonPointAttributes.Descriptor) or '')
            except Exception:
                pass
        except Exception as e:
            log('  NO ENCONTRADO: {} ({})'.format(tag_pi, type(e).__name__))
        meta.append(registro)

    n_ok = sum(1 for m in meta if m['encontrado'])
    log('Puntos resueltos: {}/{}'.format(n_ok, len(TAGS)))
    if n_ok == 0:
        raise RuntimeError('Ningún tag resuelto. Revisar nombres o permisos.')

    # Tabla código -> nombre de los tags digitales. Sin ella, la columna
    # guardada es un entero sin significado y el pipeline no puede auditarla.
    for col in sorted(TAGS_DIGITALES):
        p = puntos.get(col)
        if p is None:
            continue
        try:
            nombre_set = str(p.GetAttribute(PICommonPointAttributes.DigitalSetName) or '')
            tipo = str(p.PointType)
            if nombre_set:
                estados = server.StateSets[nombre_set]
                mapa = {int(s.Value): str(s.Name) for s in estados}
                log('  DigitalSet de {} ({}): {}'.format(col, nombre_set, mapa))
            else:
                log('  {} es de tipo {} sin DigitalSet: se leerá como numérico.'.format(
                    col, tipo))
        except Exception as e:
            log('  No se pudo leer el DigitalSet de {} ({}). '
                'Verificar los códigos en el manifiesto.'.format(col, type(e).__name__))

    return puntos, meta


# =========================================================================== #
# 6. EXTRACCIÓN
# =========================================================================== #
def _rango_af(t0, t1):
    return AFTimeRange(AFTime(t0.isoformat()), AFTime(t1.isoformat()))


def _afvalues_a_serie(afvalues, grid, digital=False):
    """AFValues -> Series reindexada sobre la grilla canónica del bloque.

    Sin ffill: los huecos quedan como NaN en su posición correcta, de modo que
    la serie nunca se desplaza y un dato ausente sigue siendo distinguible.
    """
    ts, vs = [], []
    for v in afvalues:
        try:
            ts.append(v.Timestamp.LocalTime.ToString('yyyy-MM-dd HH:mm:ss'))
            vs.append(valor_float(v, digital))
        except Exception:
            continue
    if not ts:
        return pd.Series(np.nan, index=grid)
    s = pd.Series(vs, index=pd.to_datetime(ts, format='%Y-%m-%d %H:%M:%S'))
    s = s[~s.index.duplicated(keep='last')]
    return s.reindex(grid)


def extraer_bloque_bulk(puntos, t0, t1, intervalo, grid):
    """Una sola llamada paginada al servidor para todos los tags del bloque."""
    lista = PIPointList()
    inverso = {}
    for col, p in puntos.items():
        lista.Add(p)
        inverso[p.Name] = col

    paging = PIPagingConfiguration(PIPageType.TagCount, PAGE_SIZE)
    resultados = lista.InterpolatedValues(_rango_af(t0, t1), intervalo, None, False, paging)

    datos = {}
    for afvalues in resultados:
        col = inverso.get(afvalues.PIPoint.Name)
        if col is not None:
            datos[col] = _afvalues_a_serie(afvalues, grid, col in TAGS_DIGITALES)
    return pd.DataFrame(datos, index=grid)


def extraer_bloque_por_tag(puntos, t0, t1, intervalo, grid, server=None):
    """Extracción tag por tag. Más round-trips, resultado idéntico al bulk.

    Con reintentos por tag: un corte de red transitorio no debe traducirse en
    una columna de NaN indistinguible de un hueco real del historiador.
    """
    datos, fallidos = {}, []
    for col, p in puntos.items():
        s = None
        for intento in range(1, MAX_REINTENTOS + 1):
            try:
                afvalues = p.InterpolatedValues(_rango_af(t0, t1), intervalo, None, False)
                s = _afvalues_a_serie(afvalues, grid, col in TAGS_DIGITALES)
                break
            except Exception as e:
                if intento < MAX_REINTENTOS:
                    time.sleep(ESPERA_REINTENTO_S)
                    try:
                        if server is not None and not server.ConnectionInfo.IsConnected:
                            server.Connect()
                    except Exception:
                        pass
                else:
                    log('    fallo definitivo en {}: {}: {}'.format(col, type(e).__name__, e))
                    fallidos.append(col)
        datos[col] = s if s is not None else pd.Series(np.nan, index=grid)

    if fallidos:
        log('    ATENCIÓN: {} tag(s) sin dato en este bloque por error de extracción, '
            'no por hueco del historiador: {}'.format(len(fallidos), fallidos))
    return pd.DataFrame(datos, index=grid)


def guarda_esquema(columnas):
    """Impide reutilizar chunks generados con otro conjunto de columnas.

    Sin esta guarda, agregar un tag y relanzar con REANUDAR=True reutilizaría
    los bloques antiguos y el tag nuevo quedaría vacío en toda la historia,
    sin ningún error. Es la misma clase de fallo silencioso que la clave
    duplicada del diccionario original.
    """
    ruta = os.path.join(DIR_CHUNKS, '_esquema.json')
    if os.path.exists(ruta):
        with open(ruta, encoding='utf-8') as f:
            previo = json.load(f)
        if previo != columnas:
            nuevas = [c for c in columnas if c not in previo]
            quitadas = [c for c in previo if c not in columnas]
            raise RuntimeError(
                'El conjunto de tags cambió respecto de los chunks guardados en {}.\n'
                '  columnas nuevas   : {}\n'
                '  columnas quitadas : {}\n'
                'Los chunks existentes NO contienen las columnas nuevas y '
                'reutilizarlos las dejaría vacías en toda la historia.\n'
                'Renombrar o borrar esa carpeta y volver a extraer.'.format(
                    DIR_CHUNKS, nuevas or 'ninguna', quitadas or 'ninguna'))
        log('Esquema de chunks coincide ({} columnas).'.format(len(columnas)))
    else:
        with open(ruta, 'w', encoding='utf-8') as f:
            json.dump(columnas, f, ensure_ascii=False, indent=1)
        log('Esquema de chunks registrado ({} columnas).'.format(len(columnas)))


def extraer(server, puntos, inicio_dt, fin_dt, columnas):
    intervalo = AFTimeSpan.Parse(INTERVALO_MUESTREO)
    log("Intervalo '{}' parseado como: {}  <-- VERIFICAR que sea 1 minuto".format(
        INTERVALO_MUESTREO, intervalo.ToString()))
    log('Extracción masiva (bulk): {} [{}]'.format(
        'DISPONIBLE' if BULK_DISPONIBLE else 'NO DISPONIBLE -> modo tag por tag',
        _NS_PAGING))

    usar_bulk = BULK_DISPONIBLE
    os.makedirs(DIR_CHUNKS, exist_ok=True)
    guarda_esquema(columnas)
    bloques = list(bloques_tiempo(inicio_dt, fin_dt, CHUNK_DIAS))
    log('Total de bloques de {} días: {}'.format(CHUNK_DIAS, len(bloques)))

    rutas = []
    for i, (t0, t1) in enumerate(bloques, 1):
        # El nombre incluye inicio Y fin: dos corridas con distinto CHUNK_DIAS
        # (o el MODO_PRUEBA frente a la corrida completa) generan bloques que
        # arrancan el mismo día pero cubren rangos distintos. Sin la fecha de
        # fin, REANUDAR reutilizaría el bloque corto y perdería datos en
        # silencio.
        base = os.path.join(DIR_CHUNKS, 'bloque_{:04d}_{}_{}'.format(
            i, t0.strftime('%Y%m%d'), t1.strftime('%Y%m%d')))

        if REANUDAR:
            existente = ruta_chunk_existente(base)
            if existente:
                log('[{}/{}] {} -> ya existe, se omite.'.format(i, len(bloques), t0.date()))
                rutas.append(existente)
                continue

        grid = pd.date_range(t0.replace(tzinfo=None), t1.replace(tzinfo=None),
                             freq=freq_pandas(), inclusive='left')

        df_b, t_ini = None, time.time()
        if usar_bulk:
            for intento in range(1, MAX_REINTENTOS + 1):
                try:
                    df_b = extraer_bloque_bulk(puntos, t0, t1, intervalo, grid)
                    break
                except (TypeError, AttributeError) as e:
                    # Firma o método inexistente: problema de API, no de red.
                    # Reintentar no sirve; se desactiva bulk para toda la corrida.
                    log('    API bulk no utilizable ({}: {}). Cambiando a tag por tag '
                        'para el resto de la extracción.'.format(type(e).__name__, e))
                    usar_bulk = False
                    break
                except Exception as e:
                    log('[{}/{}] intento {}/{} falló: {}: {}'.format(
                        i, len(bloques), intento, MAX_REINTENTOS, type(e).__name__, e))
                    if intento < MAX_REINTENTOS:
                        time.sleep(ESPERA_REINTENTO_S)
                        if not server.ConnectionInfo.IsConnected:
                            log('    reconectando...')
                            server.Connect()

        if df_b is None:
            df_b = extraer_bloque_por_tag(puntos, t0, t1, intervalo, grid, server)

        # Columnas ausentes (tag no encontrado) -> NaN, para esquema homogéneo
        for c in columnas:
            if c not in df_b.columns:
                df_b[c] = np.nan
        df_b = df_b[columnas].astype(DTYPE_SALIDA)

        ruta = guardar_df(df_b, base)
        rutas.append(ruta)
        log('[{}/{}] {} -> {} filas, cobertura {:.1f}%, {:.1f}s'.format(
            i, len(bloques), t0.date(), len(df_b),
            100.0 * df_b.notna().mean().mean(), time.time() - t_ini))

    return rutas


# =========================================================================== #
# 7. CONSOLIDACIÓN, VERIFICACIÓN Y MANIFIESTO
# =========================================================================== #
def consolidar(rutas):
    log('Consolidando {} bloques...'.format(len(rutas)))
    df = pd.concat([leer_df(r) for r in rutas], axis=0)
    df = df[~df.index.duplicated(keep='first')].sort_index()
    df.index.name = 'timestamp'
    log('DataFrame final: {} filas x {} columnas'.format(len(df), df.shape[1]))
    return df


def verificar_continuidad(df, inicio_dt, fin_dt):
    """Prueba que el troceado no rompió la serie temporal.

    Compara el índice obtenido contra la grilla teórica completa. Detecta
    huecos, duplicados de borde y timestamps fuera de retícula. Si pasa, el
    troceado es equivalente a una extracción única.

    Nota: valida la GRILLA, no la COBERTURA. Puede dar OK y aun así haber
    columnas con NaN si un tag no devolvió datos; eso lo cuantifica el
    manifiesto en `pct_nan`.
    """
    esperado = pd.date_range(inicio_dt.replace(tzinfo=None),
                             fin_dt.replace(tzinfo=None),
                             freq=freq_pandas(), inclusive='left')
    n_dup = int(df.index.duplicated().sum())
    faltantes = esperado.difference(df.index)
    fuera = df.index.difference(esperado)
    espaciados = pd.Series(df.index).diff().dropna().value_counts()

    log('Verificación de continuidad temporal:')
    log('  filas esperadas           : {}'.format(len(esperado)))
    log('  filas obtenidas           : {}'.format(len(df)))
    log('  timestamps duplicados     : {}'.format(n_dup))
    log('  timestamps faltantes      : {}'.format(len(faltantes)))
    log('  timestamps fuera de grilla: {}'.format(len(fuera)))
    log('  espaciados observados     : {}'.format(
        {str(k): int(v) for k, v in list(espaciados.items())[:5]}))
    if len(faltantes):
        log('  primeros faltantes        : {}'.format([str(t) for t in faltantes[:5]]))

    ok = (n_dup == 0 and len(faltantes) == 0 and len(fuera) == 0)
    log('  RESULTADO: {}'.format(
        'CONTINUIDAD OK (troceado equivalente a extracción única)'
        if ok else 'REVISAR - la serie no cubre la grilla completa'))
    return ok


def construir_manifiesto(df, meta):
    """Estadísticos de auditoría por tag. Sin esto, nada es trazable."""
    filas, n = [], len(df)
    for m in meta:
        col = m['columna']
        s_val = (df[col] if col in df.columns else pd.Series(dtype=float)).dropna()
        # Fracción de muestras idénticas a la anterior: proxy directo de tag
        # congelado por constante de respaldo del PLC.
        frac_cong = float((s_val.diff() == 0).mean()) if len(s_val) > 1 else np.nan
        filas.append({
            'tag_pi': m['tag_pi'],
            'columna': col,
            'grupo': m['grupo'],
            'descripcion': m['descripcion'],
            'encontrado': m['encontrado'],
            'unidades': m['unidades'],
            'descriptor_pi': m['descriptor_pi'],
            'n_filas': n,
            'n_validos': int(len(s_val)),
            'pct_nan': round(100.0 * (1 - len(s_val) / n), 3) if n else np.nan,
            'frac_congelado': round(frac_cong, 4) if pd.notna(frac_cong) else np.nan,
            'n_valores_unicos': int(s_val.nunique()) if len(s_val) else 0,
            'min': float(s_val.min()) if len(s_val) else np.nan,
            'p50': float(s_val.median()) if len(s_val) else np.nan,
            'max': float(s_val.max()) if len(s_val) else np.nan,
            'media': float(s_val.mean()) if len(s_val) else np.nan,
            'std': float(s_val.std()) if len(s_val) else np.nan,
            'primer_ts': str(s_val.index.min()) if len(s_val) else '',
            'ultimo_ts': str(s_val.index.max()) if len(s_val) else '',
        })
    return pd.DataFrame(filas)


def reportar(manifiesto):
    log('-' * 70)
    faltan = manifiesto.loc[~manifiesto['encontrado'], 'tag_pi'].tolist()
    if faltan:
        log('TAGS NO ENCONTRADOS ({}):'.format(len(faltan)))
        for t in faltan:
            log('   - ' + t)

    vacios = manifiesto[manifiesto['encontrado'] & (manifiesto['n_validos'] == 0)]
    if len(vacios):
        log('TAGS SIN NINGÚN DATO ({}): {}'.format(len(vacios), vacios['columna'].tolist()))

    cong = manifiesto[manifiesto['frac_congelado'] > 0.5].sort_values(
        'frac_congelado', ascending=False)
    if len(cong):
        log('TAGS CONGELADOS >50% (revisar constantes de respaldo del PLC):')
        for _, r in cong.iterrows():
            log('   - {:<28} {:.1%} congelado, {} valores únicos'.format(
                r['columna'], r['frac_congelado'], r['n_valores_unicos']))

    pobres = manifiesto[manifiesto['encontrado'] & (manifiesto['pct_nan'] > 20)]
    if len(pobres):
        log('TAGS CON >20% NaN:')
        for _, r in pobres.iterrows():
            log('   - {:<28} {:.1f}% NaN'.format(r['columna'], r['pct_nan']))
    log('-' * 70)


# =========================================================================== #
# 8. MAIN
# =========================================================================== #
def main():
    validar_tags(TAGS)
    columnas = [t[1] for t in TAGS]

    tz = pytz.timezone(ZONA_HORARIA_LOCAL)
    inicio_dt = tz.localize(datetime.strptime(FECHA_INICIO, '%Y-%m-%d %H:%M:%S'))
    fin_dt = (tz.localize(datetime.strptime(FECHA_FIN, '%Y-%m-%d %H:%M:%S'))
              if FECHA_FIN else datetime.now(tz))

    if MODO_PRUEBA:
        fin_dt = min(fin_dt, inicio_dt + timedelta(days=DIAS_PRUEBA))
        log('*** MODO_PRUEBA ACTIVO: solo {} días. Chunks en {}. '
            'Poner MODO_PRUEBA=False para la corrida completa (usa otra '
            'carpeta, no hace falta borrar nada). ***'.format(DIAS_PRUEBA, DIR_CHUNKS))

    if fin_dt <= inicio_dt:
        raise ValueError('FECHA_FIN debe ser posterior a FECHA_INICIO.')

    os.makedirs(DIR_SALIDA, exist_ok=True)
    log('Rango: {} -> {}  ({} días)'.format(inicio_dt, fin_dt, (fin_dt - inicio_dt).days))

    server = conectar()
    try:
        puntos, meta = resolver_puntos(server)
        rutas = extraer(server, puntos, inicio_dt, fin_dt, columnas)
    finally:
        try:
            server.Disconnect()
            log('Desconectado del servidor PI.')
        except Exception:
            pass

    df = consolidar(rutas)
    verificar_continuidad(df, inicio_dt, fin_dt)

    sello = datetime.now().strftime('%Y%m%d_%H%M')
    sufijo = '_PRUEBA' if MODO_PRUEBA else ''
    base_out = os.path.join(DIR_SALIDA, 'datos_espesadores{}_{}'.format(sufijo, sello))

    ruta_datos = guardar_df(df, base_out)
    log('Datos: {}'.format(ruta_datos))

    manifiesto = construir_manifiesto(df, meta)
    ruta_man = os.path.join(
        DIR_SALIDA, 'manifiesto_extraccion{}_{}.csv'.format(sufijo, sello))
    manifiesto.to_csv(ruta_man, index=False, encoding='utf-8-sig')
    log('Manifiesto: {}'.format(ruta_man))

    if EXPORTAR_CSV:
        df.to_csv(base_out + '.csv')
        log('CSV: {}'.format(base_out + '.csv'))

    reportar(manifiesto)
    log('Extracción completada. Cobertura global: {:.2f}%'.format(
        100.0 * df.notna().mean().mean()))
    return df


if __name__ == '__main__':
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)