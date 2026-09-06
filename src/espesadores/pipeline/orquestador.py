# -*- coding: utf-8 -*-
"""
orquestador.py — corre las 11 etapas en orden para un espesador y devuelve
el contexto con todos los resultados, listo para generar el one-pager.

Reemplaza el bloque final de `pipeline_espesadores.py` (archivado en
`data/99_deprecated/pipeline_espesadores_monolito_original.py`). Cada etapa
vive en su propio módulo con la interfaz común `(df, cfg, ctx) -> df`
(requisito de la sección 6 del traspaso).
"""
import os

from espesadores.config import ESPESADORES, RUTAS

from .comun import log, reiniciar_reporte, texto_reporte
from .e01_carga import e01_cargar
from .e02_diagnostico import e02_diagnostico
from .e03_limpieza import e03_limpiar
from .e04_trenes import e04_trenes
from .e05_balance import e05_balance
from .e06_estado_estacionario import e06_estado_estacionario
from .e07_validacion import e07_validar_palanca
from .e08_mineral import e08_mineral
from .e09_guardias import e09_guardias
from .e10_ventanas import e10_ventanas
from .e11_comparacion_trenes import e11_comparar_trenes


def ejecutar(espesador="TH-001", k_mineral=4):
    """
    Corre el pipeline completo (E01-E11) para un espesador y devuelve el
    contexto con todos los resultados.
    """
    reiniciar_reporte()
    cfg = ESPESADORES[espesador]
    ctx = {"espesador": espesador, "cfg": cfg,
           "salidas": os.path.join(RUTAS["salidas"], espesador.replace("-", ""))}
    os.makedirs(ctx["salidas"], exist_ok=True)

    log("#" * 78)
    log(f"# PIPELINE DE ESPESADORES  ·  {cfg['nombre_largo']}  ({cfg['tag_equipo']})")
    log("#" * 78)

    df = e01_cargar(cfg, ctx)
    df = e02_diagnostico(df, cfg, ctx)
    df = e03_limpiar(df, cfg, ctx)
    df = e04_trenes(df, cfg, ctx)
    df = e05_balance(df, cfg, ctx)
    df = e06_estado_estacionario(df, cfg, ctx)
    df = e07_validar_palanca(df, cfg, ctx)
    df = e08_mineral(df, cfg, ctx, k=k_mineral)
    df = e09_guardias(df, cfg, ctx)
    df = e10_ventanas(df, cfg, ctx)
    df = e11_comparar_trenes(df, cfg, ctx)

    with open(os.path.join(ctx["salidas"], "REPORTE_COMPLETO.txt"), "w",
              encoding="utf-8") as f:
        f.write(texto_reporte())
    log("")
    log(f"Reporte de auditoria: {ctx['salidas']}/REPORTE_COMPLETO.txt")

    ctx["df"] = df
    return ctx


if __name__ == "__main__":
    import sys
    esp = sys.argv[1] if len(sys.argv) > 1 else "TH-001"
    contexto = ejecutar(esp)
    from espesadores.reportes.onepager import generar_onepager
    generar_onepager(contexto)
