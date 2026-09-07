# Espesadores de Relaves C2 — TH-001 / TH-002 / TH-003

Analiza un espesador y entrega las ventanas operativas para el sistema
experto. Validado sobre TH-001. Estructura migrada a MLOps el 2026-09-06 —
ver `docs/plan_migracion.md` para el detalle de la migración y
`docs/inventario_proyecto.md` para el inventario y los hallazgos que la
motivaron.

## Uso

```bash
pixi install
pixi run pipeline TH-001     # o TH-002, TH-003
pixi run test                # tests/ — guardas anti-regresión de H-A y H-B
```

Salida: `data/06_reporting/<espesador>/` con los 19 archivos intermedios
E01-E11, el reporte de auditoría completo (`REPORTE_COMPLETO.txt`) y el
one-pager en HTML.

## Para aplicarlo a TH-002 o TH-003

Editar **únicamente** `conf/base/tags.yaml`. Los campos marcados
`completar: true` deben confirmarse con Instrumentación antes de correr —
no estaban en el dataset original de TH-001 y su nombre es una suposición.

## Estructura

```
conf/base/      configuración declarativa (tags, calidad, reglas, extracción)
conf/local/     credenciales y rutas de máquina — gitignored
data/           00_raw -> 01_interim -> ... -> 06_reporting, más 99_deprecated
src/espesadores/  código de producción (extracción, calidad, dominio, pipeline, reportes)
notebooks/      exploración — NO producción
tests/          guardas anti-regresión
docs/           inventario, plan de migración, bitácora de hallazgos, glosario
scripts/        entrypoints CLI
```

Ver `docs/plan_migracion.md` §1 para el árbol completo.

## Etapas del pipeline y su sustento

| Etapa | Qué hace | Sustento | Salida |
|---|---|---|---|
| E01 | Carga, perfil, detecta muestreo | CRISP-DM, Data Understanding | `E01_perfil_estructural.csv` |
| E02 | Descarta variables con hold y verifica independencia %sólidos/densidad | Hallazgo TH-001: 86% de una variable en un solo valor; SG cableado en 2.77 | `E02_diagnostico_variables.csv` |
| E03 | Rango físico, planta produciendo, atípicos | Narasimhan & Jordache (2000); Hampel (1974); Leys et al. (2013) | `E03a`, `E03b` |
| E04 | Señal activa de descarga y acoplamiento de trenes | Hallazgo TH-001: la correlación pasó de +0.06 a +0.85 al usar la bomba en servicio | `E04_trenes.csv` |
| E05 | Recalcula rebose desde balance de agua (no usa el tag crudo de rebose — H-C) | El estimador del DCS queda congelado 70% del tiempo | `E05_balance_agua.csv` |
| E06 | Estado estacionario | Cao & Rhinehart (1995) | `E06_retencion.csv` |
| E07 | **Control de calidad**: pendiente medida vs teórica | Si no coinciden, no seguir | `E07_validacion_palanca.csv` |
| E08 | Tipos de mineral, 4 algoritmos + control positivo | Firma sólo exógena, evita circularidad | `E08a`, `E08b` |
| E09 | Efecto de guardias con nulo por desplazamiento circular (lag real: 336h, H-D) | Comparar contra "día" es tramposo | `E09a`, `E09b`, `E09c` |
| E10 | Ventanas óptimas y ¿hay regímenes por mineral? | p10–p90 del tercio de mejor recuperación | `E10a`, `E10b`, `E10c` |
| E11 | Comparación de trenes con emparejamiento | Descarta que un tren se use sólo en condiciones difíciles | `E11a`, `E11b`, `E11c` |

## Principios no negociables

Ver `PROMPT_CLAUDE_CODE.md` sección 7 y `docs/inventario_proyecto.md` para
el detalle de cada hallazgo (H-A a H-H, N-1 a N-7). En resumen:

1. Nunca `ffill()`/`bfill()` sobre datos del historiador (H-B) — guardado por `tests/test_sin_ffill_bfill.py`.
2. Los bugs silenciosos son el riesgo principal (H-A) — guardado por `tests/test_config_tags.py`.
3. Ningún tag ni ruta absoluta hardcodeados en `src/` — guardado por `tests/test_sin_hardcodeo.py`.
4. El espesador es un parámetro (`conf/base/tags.yaml`), no una copia del código.

## Resultados obtenidos en TH-001 (recomputados 2026-09-07 contra la reextracción manual, post-migración)

Corrida de `pixi run pipeline TH-001` contra
`data/00_raw/datos_espesadores_20260906_1918.parquet` (68 tags de
`conf/base/tags.yaml::extraccion_pi`, extraídos de cero el 2026-09-06/07
desde la máquina Windows con `pixi run -e extraccion extraer`, sin el
artefacto de `ffill` de H-B, con la corrección de PB01/PB02 de H-A). Mismo
rango (2024-07-14 → 2026-09-02) y mismas 1,123,200 filas crudas que la
corrida anterior contra `espesadores_20260906_1317.parquet` (borrada al
reiniciar la extracción desde cero) — cifras idénticas, confirma que la
reextracción es reproducible.

- Control de calidad **superado**: 4 de 5 bandas de tonelaje con desvío < 30%
- Sensibilidad: **11.0 m³/h por punto de % sólidos de descarga** (ton=396 t/h, wt=60.2%)
- Detector de mineral **válido** (AUC 0.948)
- Trenes acoplados al 100%; el Tren 2 gana en **34 de 35** comparaciones emparejadas (+1.67 puntos, 18 m³/h)
- La ventana óptima **no cambia mucho** entre tipos de mineral (BedMass varía 2.4 puntos, cizalle 0.0)
- Retención: 1.123.200 filas crudas -> 452.432 en estado estacionario (40.3%)

Estas cifras son de **TH-001 únicamente**; TH-002 y TH-003 requieren primero
confirmar con Instrumentación los tags marcados `completar: true` en
`conf/base/tags.yaml` (26 tags pendientes) antes de correr `pixi run
pipeline TH-002`/`TH-003` con resultados confiables.
