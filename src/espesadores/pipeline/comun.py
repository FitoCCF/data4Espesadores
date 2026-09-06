# -*- coding: utf-8 -*-
"""
comun.py — utilidades compartidas por las 11 etapas del pipeline (E01-E11).

Antes vivían al principio de `pipeline_espesadores.py` (un solo archivo de
1188 líneas). Se separan aquí para que cada etapa sea un módulo propio con
una interfaz común `(df, cfg, ctx) -> df`, tal como pide la sección 6 del
traspaso ("una etapa por módulo, interfaz común").
"""
import os

import numpy as np

# Acumulador del texto del reporte de auditoría, compartido por todas las
# etapas de una misma corrida. `orquestador.ejecutar()` lo reinicia al empezar.
_REPORTE = []


def reiniciar_reporte():
    _REPORTE.clear()


def texto_reporte():
    return "\n".join(_REPORTE)


def log(msg=""):
    """Imprime en consola y guarda la línea para el reporte de auditoría."""
    print(msg)
    _REPORTE.append(str(msg))


def titulo(txt):
    """Encabezado visible de etapa."""
    log("")
    log("=" * 78)
    log(txt)
    log("=" * 78)


def guardar(df, nombre, carpeta):
    """Escribe una salida intermedia en CSV para que la etapa sea auditable."""
    os.makedirs(carpeta, exist_ok=True)
    ruta = os.path.join(carpeta, nombre)
    df.to_csv(ruta, index=True)
    log(f"    [salida] {ruta}")
    return ruta


def eta2(df, variable, grupo):
    """
    Fracción de la varianza de 'variable' que queda explicada por 'grupo'.

    Se usa para comparar cuánto pesa un factor (tipo de mineral, guardia)
    sobre un parámetro operativo. Interpretación práctica: 0.01 = 1% de la
    variación.
    """
    d = df[[variable, grupo]].dropna()
    if len(d) < 50 or d[variable].std() == 0:
        return np.nan
    media_global = d[variable].mean()
    grupos = d.groupby(grupo)[variable]
    ss_entre = sum(len(g) * (g.mean() - media_global) ** 2 for _, g in grupos)
    ss_total = ((d[variable] - media_global) ** 2).sum()
    return ss_entre / ss_total if ss_total > 0 else np.nan


def residuo(y, X):
    """Devuelve el residuo de y tras remover el efecto lineal de X."""
    X = np.c_[np.ones(len(X)), X]
    beta = np.linalg.lstsq(X, y, rcond=None)[0]
    return y - X @ beta


def corr_parcial(df, x, y, controles):
    """
    Correlación entre x e y DESPUÉS de descontar el efecto de 'controles'.

    Imprescindible en este proceso: el rebose escala con el tonelaje, así que
    sin controlar por tonelaje cualquier variable "correlaciona" con el
    rebose solo por seguir a la producción.
    """
    cols = [x, y] + list(controles)
    d = df[cols].dropna()
    if len(d) < 300:
        return np.nan
    rx = residuo(d[x].values, d[list(controles)].values)
    ry = residuo(d[y].values, d[list(controles)].values)
    return float(np.corrcoef(rx, ry)[0, 1])


def filtro_hampel(serie, ventana, n_sigma=3.0):
    """
    Filtro de Hampel: marca como atípico lo que se aleja de la MEDIANA móvil
    más de n_sigma veces la MAD (desviación absoluta mediana).

    SUSTENTO (Hampel 1974; Leys et al. 2013): no se usa media +- 3
    desviaciones porque la media y la desviación ya están contaminadas por
    los propios atípicos. La mediana y la MAD son robustas: un valor extremo
    no las mueve. El 1.4826 convierte MAD a escala de desviación estándar en
    una normal.
    """
    mediana = serie.rolling(ventana, center=True, min_periods=1).median()
    desviacion = (serie - mediana).abs()
    mad = desviacion.rolling(ventana, center=True, min_periods=1).median()
    umbral = n_sigma * 1.4826 * mad
    es_atipico = desviacion > umbral
    return serie.mask(es_atipico, np.nan), int(es_atipico.sum())
