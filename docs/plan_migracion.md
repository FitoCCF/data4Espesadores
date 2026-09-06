# Plan de migración — Espesadores C2 (TH-001/002/003)

Tarea B de `PROMPT_CLAUDE_CODE.md`. Propone la migración a la estructura de
la sección 6 del encargo, archivo por archivo, a partir de lo relevado en
`docs/inventario_proyecto.md`.

> ## TAREA C — EJECUTADA (2026-09-06)
>
> El usuario aprobó seguir con la Tarea C. Se ejecutó este plan casi en su
> totalidad: estructura de directorios creada, archivos movidos, config
> partida en YAML (con N-1 corregido), pipeline dividido en 11 módulos +
> orquestador, `dominio/piscinas.py` y `dominio/guardias.py` desduplicados,
> scripts de extracción adaptados (no ejecutables aquí — Windows/AF SDK),
> `pixi.toml` ampliado (`pyarrow`, `statsmodels`, `pyyaml`, `pytz`,
> `pytest`, `hmmlearn`, `ruptures`) y **verificado corriendo de punta a
> punta**: `pixi run pipeline TH-001`, `pixi run piscinas`, `pixi run
> guardias` y `pixi run diagnostico --parte B` corrieron completos contra el
> dataset canónico, con `pixi run test` (8 pruebas) en verde.
>
> **Verificación cruzada:** los números que devolvieron `piscinas.py` (mediana
> de divergencia 67,34 pp, máx 49.622, 6.509 episodios bajo 75%, autocorrelación
> 12h=+0,267/24h=+0,261) y `guardias.py`/`diagnostico_extraccion.py`
> (dotación 2/2/3, 14 firmas, ciclo de 14 días, cobertura mensual con los
> mismos escalones de H-F, sobreestimación máxima de H-G = 0,0003)
> **coinciden exactamente** con lo documentado en el traspaso y en
> `docs/inventario_proyecto.md` — la migración no cambió ningún resultado
> donde no debía. Donde sí cambió (el pipeline E01-E11, por la corrección de
> N-1) los números nuevos quedaron en `README.md` y
> `data/06_reporting/TH001/`, reemplazando a los contaminados.
>
> **Corrección de código no anticipada en el plan:** `e01_carga.py` no podía
> asumir que `timestamp` fuera una columna — el parquet canónico lo guarda
> como índice y pandas lo restituye como tal al leer, no como columna. Se
> corrigió para aceptar ambos casos.
>
> **Quedó fuera de esta ejecución** (no se pidió explícitamente y son
> acciones destructivas o requieren datos externos — ver la lista de
> decisiones pendientes al final de este documento, actualizada):
> - Borrado real de los 54 `bloque_*.parquet` y de los CSV `Data_Esp1_*`
>   grandes: se **movieron** a `data/99_deprecated/`, no se eliminaron.
> - Confirmación con Instrumentación de los 26 tags `completar: true` de
>   TH-002/TH-003.
> - Tarea D (bitácora de hallazgos) — ver `docs/bitacora_hallazgos.md`.
>
> **Actualización 2026-09-06 (posterior):** el usuario confirmó que el tema
> del área 2101/QH no tiene relación con este proyecto. `_fuera_de_alcance_area_2101/`
> (las dos búsquedas de amperaje) se **eliminó** — no se archivó en otro
> lado, por indicación explícita.
>
> El resto de este documento se conserva tal como se escribió en la Tarea B,
> como registro de la propuesta original.

Convención de rutas: todo bajo un nuevo directorio raíz `espesadores/` (nombre
tomado de la sección 6). Donde el encargo no cubre un caso exacto (p. ej. qué
hacer con exploración cuyo dataset de entrada ya no existe), se propone un
destino razonable y se marca **[DECIDIR]** para que el usuario confirme antes
de la Tarea C.

---

## 0. Antes de mover un solo archivo

Tres correcciones deben ir **junto con** la migración, no después, porque si
no la estructura nueva hereda los mismos bugs con nombres distintos:

1. **N-1 (crítico):** al migrar `config_espesadores.py` → `conf/base/*.yaml`,
   `RUTAS["entrada"]` deja de apuntar a `datos.parquet` (contaminado) y pasa a
   apuntar al dataset canónico ya ubicado en `data/00_raw/`.
2. **Tags hardcodeados fuera de `config_espesadores.py` (verificado con grep,
   no eran visibles en la Tarea A):**
   - `nivel_piscinas.py` línea 42-43: `COL_A = 'LIT_106'`, `COL_B = 'LIT_107'`
     — quemados en el script, no en `tags.yaml`. Incumple el criterio de
     aceptación 7 del encargo.
   - `nivel_piscinas.py` usa `HORAS_CAMBIO_GUARDIA` con **07:00/19:00**,
     mientras que `config_espesadores.py::TURNOS` y `rol_guardias.py` ya
     tienen **07:30/19:30 confirmado con planta** (H-D). **Confirmado
     directamente por el usuario (2026-09-06): turno A 07:30→19:30, turno B
     19:30→07:30.** `nivel_piscinas.py` queda con el valor equivocado —
     corregir a 07:30/19:30 al mover a `reglas_operativas.yaml`, fuente única
     junto con `guardias.py`. Ya no es un supuesto a confirmar, es un bug
     confirmado a corregir.
   - **Regla de derivación LIT_106/LIT_107, confirmada por el usuario
     (2026-09-06):** si ambos transmisores dan valores similares/muy
     cercanos, el valor es válido tal cual (ambos son la misma lectura real);
     si hay una diferencia grande, el válido es el **mayor**. Coincide con lo
     que ya implementa `nivel_piscinas.py` y con lo descrito en §5.1 del
     traspaso — queda confirmado, no es solo una hipótesis de planta. Sigue
     pendiente fijar el **umbral numérico** de "diferencia grande" a partir
     del valle del histograma de divergencia (el script ya lo caracteriza;
     falta leer el resultado y fijarlo en `reglas_operativas.yaml`).
   - `rol_guardias.py` líneas 61-62 declara `MINUTO_INICIO_A/B` por su cuenta,
     duplicando (aunque hoy coincide con) `config_espesadores.py::TURNOS`.
     Fuente única en `reglas_operativas.yaml`.
3. **Ruta absoluta de Windows quemada en 4 scripts** (`sys.path.append(r'C:\
   Program Files (x86)\PIPC\AF\PublicAssemblies\4.0')`): `getDataAllTH.py`
   línea 55, `getAtributes.py` línea 7, `searchTAg.py` línea 7,
   `verificaciondata.py` línea 65. Pasa a `conf/local/` (gitignored, por
   máquina) o a una variable de entorno `PI_AF_SDK_PATH`.

---

**Regla de vigencia de datasets, confirmada por el usuario (2026-09-06):** la
validez de un `.parquet` de extracción se determina por el timestamp en su
propio nombre de archivo (`datos_espesadores_YYYYMMDD_HHMM.parquet`) — el más
reciente es el vigente. Esto confirma la elección de
`datos_espesadores_20260906_1317.parquet` como canónico en §3 y debe quedar
escrito como convención explícita en `conf/base/extraccion.yaml` (no
depender de que quien mire la carpeta lo infiera solo).

---

## 1. Estructura de directorios a crear

```
espesadores/
├─ README.md                  ex-LEEME.md, actualizado
├─ pixi.toml / pixi.lock       ampliados (ver §7)
├─ .gitignore                  ampliado (ver §8)
├─ .gitattributes
├─ conf/
│  ├─ base/
│  │  ├─ extraccion.yaml
│  │  ├─ tags.yaml
│  │  ├─ calidad.yaml
│  │  ├─ reglas_operativas.yaml
│  │  └─ pipeline.yaml
│  └─ local/                   .gitignored: PI_AF_SDK_PATH, credenciales
├─ data/
│  ├─ 00_raw/
│  │  ├─ espesadores_20260906_1317.parquet      (ex canónico, renombrado)
│  │  ├─ manifiesto_extraccion_20260906_1317.csv
│  │  ├─ pi_metadata/           atributos y búsquedas PI (ver §2)
│  │  └─ .checkpoints/          _esquema.json (estado de resume, no dato)
│  ├─ 01_interim/
│  │  ├─ calendario_guardias.parquet
│  │  └─ nivel_piscinas_derivado.parquet
│  ├─ 02_primary/               (vacío — lo llena la Tarea C al correr E01-E03 ya corregido)
│  ├─ 03_features/ 04_model_input/ 05_models/   (vacíos, próxima etapa)
│  ├─ 06_reporting/             (vacío — Tarea C regenera E01-E11 + reporte + one-pager AQUÍ, contra el dataset canónico)
│  └─ 99_deprecated/            datasets y salidas contaminados/superseded (ver §3, §6)
├─ src/espesadores/
│  ├─ extraccion/  {extraer_pi.py, descubrir_atributos.py, buscar_tags.py}
│  ├─ calidad/     {diagnostico_extraccion.py}
│  ├─ dominio/     {guardias.py, piscinas.py}
│  ├─ pipeline/    {e01_carga.py ... e11_trenes.py, orquestador.py}
│  ├─ modelado/    (vacío, próxima etapa)
│  └─ reportes/    {onepager.py}
├─ notebooks/
│  ├─ regimenes_mineral/        línea de investigación no productiva (ver §5)
│  └─ 91_historico/             notebooks a confirmar con el usuario (ver §5)
├─ tests/                        nuevo, lo llena la Tarea C
├─ docs/
│  ├─ bitacora_hallazgos.md      lo genera la Tarea D
│  ├─ diccionario_tags.md        nuevo, a partir de pi_metadata + config
│  ├─ inventario_proyecto.md     ya generado (Tarea A)
│  ├─ plan_migracion.md          este archivo
│  ├─ glosario_espesador.md
│  └─ decisiones/
│     └─ 001_namespace_af_pi.md  extraído de Untitled.ipynb (ver §5)
└─ scripts/
   ├─ extraer.py                 CLI: llama a extraccion/extraer_pi.py
   ├─ correr_pipeline.py         CLI: llama a pipeline/orquestador.py
   ├─ generar_onepager.py
   ├─ descubrir_atributos.py
   └─ buscar_tags.py
```

---

## 2. Extracción PI y descubrimiento de tags

| Origen | Destino | Cambios de código |
|---|---|---|
| `getDataAllTH.py` | `src/espesadores/extraccion/extraer_pi.py` | **Sí.** (a) ruta AF SDK → `conf/local`; (b) `tags_config` (lista de tuplas) → `conf/base/tags.yaml`; (c) `SERVIDOR_NOMBRE`, rango de fechas, tamaño de bloque (15 días) → `conf/base/extraccion.yaml`; (d) `DIR_CHUNKS` → `data/00_raw/.checkpoints/` parametrizado. |
| `getDataAllTH-checkpoint.py` | — | Eliminar (idéntico, basura de Jupyter). |
| `getAtributes.py` | `src/espesadores/extraccion/descubrir_atributos.py` + `scripts/descubrir_atributos.py` (wrapper CLI) | **Sí.** Ruta AF SDK y `SERVIDOR_NOMBRE` → igual que arriba. |
| `getAtributes-checkpoint.py` | — | Eliminar. |
| `searchTAg.py` | `src/espesadores/extraccion/buscar_tags.py` + `scripts/buscar_tags.py` | **Sí.** Mismo tratamiento que `getAtributes.py`. |
| `searchTAg-checkpoint.py` | — | Eliminar. |
| ~~`getData.ipynb`~~ | — | **Ejecutado (2026-09-06).** Eliminado por indicación del usuario: no habrá otra extracción desde este proyecto; namespace incorrecto ya documentado en `getDataAllTH.py` y en la decisión 001. |
| ~~`getData-checkpoint.ipynb`~~ | — | **Ejecutado (2026-09-06).** Eliminado: hash idéntico a `getData.ipynb`. |
| ~~`Untitled.ipynb`~~ | `docs/decisiones/001_namespace_af_pi.md` (contenido extraído) | **Ejecutado (2026-09-06).** Notebook eliminado tras extraer su prueba de namespace AF.PI/AF.Data al decision doc. |
| ~~`Untitled-checkpoint.ipynb`~~ | — | **Ejecutado (2026-09-06).** Eliminado: diff de celdas confirmó plantilla vacía, sin pérdida de contenido. |
| `Atributos_PI_20260904_1732-checkpoint.csv` | `data/99_deprecated/pi_metadata/` | No. Corrida parcial (2 columnas), superseded por `_1735`. |
| `Atributos_PI_20260904_1735-checkpoint.csv` | `data/00_raw/pi_metadata/atributos_pi_293200_294100_20260904.csv` | No. Resuelve N-2 (`FIT_114`, `LIT_106`–`109`); insumo directo de `docs/diccionario_tags.md`. |
| `Atributos_PI_20260904_1739-checkpoint.csv` | — | Eliminar (idéntico a `_1735`). |
| `Busqueda_X294100X_20260904_1818-checkpoint.csv` | `data/00_raw/pi_metadata/busqueda_294100_20260904.csv` | No. Referencia de qué tags existen bajo el prefijo del área. |
| `Busqueda_X_294100XFlowX_20260904_1745-checkpoint.csv` | `data/00_raw/pi_metadata/busqueda_294100_flow_v1_20260904.csv` | No. Esquema de columnas distinto a `_1755`/`_1757` (le falta `instrumenttag`); se conserva como referencia de esa corrida. |
| `Busqueda_X_294100XFlowX_20260904_1755-checkpoint.csv` | — | Eliminar (idéntico a `_1757`). |
| `Busqueda_X_294100XFlowX_20260904_1757-checkpoint.csv` | `data/00_raw/pi_metadata/busqueda_294100_flow_20260904.csv` | No. |
| ~~`Busqueda_X2101XPPX101X_20260905_1751-checkpoint.csv`~~ | — | **Ejecutado (2026-09-06).** Eliminado: el usuario confirmó que el área 2101/QH no tiene relación con este proyecto. |
| `Busqueda_X2101XPPX10XAmperaje_ABB_20260905_1803-checkpoint.csv` | **No migrar.** | Ídem. |

---

## 3. Datos crudos / chunks de extracción

| Origen | Destino | Cambios de código |
|---|---|---|
| `datos_espesadores_20260906_1317.parquet` | `data/00_raw/espesadores_20260906_1317.parquet` | No al archivo. Sí a quien lo referencia: `config_espesadores.py::RUTAS["entrada"]` (ver N-1, §0). |
| `manifiesto_extraccion_20260906_1317.csv` | `data/00_raw/manifiesto_extraccion_20260906_1317.csv` | No. |
| `_esquema.json` | `data/00_raw/.checkpoints/_esquema.json` | No al contenido. Sí a `getDataAllTH.py`: `DIR_CHUNKS` debe apuntar a esta nueva ruta. |
| `bloque_0001_20240714.parquet` … `bloque_0053_*.parquet` (54 archivos, ~215 MB) | **Eliminar, no migrar.** | Ver N-3 del inventario: los 54 son del esquema de 63 tags, ya no coinciden con `_esquema.json` vigente, y su sola presencia es el vector de un riesgo de reuso silencioso en un futuro resume. **[DECIDIR]** es una acción destructiva (~215 MB) — confirmar antes de ejecutar en la Tarea C, aunque no tienen valor de recuperación (el dataset canónico ya se extrajo fresco, verificado en N-3). |
| `datos_espesadores_20260905_1912.parquet` | `data/99_deprecated/datos_espesadores_20260905_1912.parquet` | No. Corrida anterior (63 tags), conservar por trazabilidad de auditoría, no por uso. |
| `manifiesto_extraccion_20260905_1912.csv` | `data/99_deprecated/manifiesto_extraccion_20260905_1912.csv` | No. |
| `datos_espesadores_PRUEBA_20260905_1811.parquet` | `data/99_deprecated/datos_espesadores_PRUEBA_20260905_1811.parquet` | No. Prueba de humo, sin valor analítico pero documenta el Principio #8. |
| `manifiesto_extraccion_PRUEBA_20260905_1811.csv` | `data/99_deprecated/manifiesto_extraccion_PRUEBA_20260905_1811.csv` | No. |

---

## 4. Datasets contaminados / superseded (familia `datos.parquet` y `Data_Esp1_*`)

Todos comparten destino: `data/99_deprecated/`, con un único
`data/99_deprecated/README.md` que explique, citando N-1/H-B, por qué ninguno
debe usarse. Se conservan (no se borran) porque son la evidencia física de
N-1/H-B y porque `test_mineral_vs_operador.py` y `io_espesador.py` los citan
por nombre — utilidad de trazabilidad, no de análisis.

| Origen | Tamaño | Destino | Cambios de código |
|---|---:|---|---|
| `datos.parquet` | 80.119.315 B | `data/99_deprecated/datos.parquet` | No al archivo. **Sí y crítico** a quien lo referencia: `config_espesadores.py::RUTAS["entrada"]` (N-1) y `test_mineral_vs_operador.py::INPUT` (mismo problema, línea `INPUT = "datos.parquet"`). |
| `datos_th1c2_020926.parquet` | 87.537.620 B | `data/99_deprecated/datos_th1c2_020926.parquet` | No. |
| `Data_Esp1_20260714_0921.parquet` + `.pkl` | 64.9 MB + 84.1 MB | `data/99_deprecated/` | No al archivo. Sí a `io_espesador.py` si se sigue usando (ver §5) — su caché parquet↔pickle asume nombres de esta familia. |
| `Data_Esp1_20260613_1604/1811/1853-checkpoint.csv` | 200-230 MB c/u | `data/99_deprecated/` | No. **[DECIDIR]**: son `-checkpoint` sin original vivo (igual patrón que los huérfanos de `.ipynb_checkpoints/`, sección 11 del inventario) — confirmar con el usuario que no hace falta el original antes de conservarlos indefinidamente o descartarlos; son ~630 MB combinados. |
| `Data_Esp1_20260724_1545.csv` | 527 MB | `data/99_deprecated/` | No. **[DECIDIR]**: candidato fuerte a **eliminar** en vez de migrar — es un CSV crudo, íntegramente superseded por el parquet canónico, y migrar 527 MB de dato contaminado a la estructura nueva no tiene retorno. Acción destructiva: confirmar antes de la Tarea C. |
| `Data_Esp1_20260901_0727.csv` | 535 MB | `data/99_deprecated/` | Igual que el anterior — **[DECIDIR]** eliminar en vez de migrar. |
| `Data_Esp1_20260902_1056.csv` | 557 MB | `data/99_deprecated/` | Igual — **[DECIDIR]** eliminar en vez de migrar. Es además la fuente de `datos_th1c2_020926.parquet` vía `getData.ipynb`. |

**Nota de tamaño:** si se migran tal cual, `data/99_deprecated/` pesaría
~1,9 GB. Recomendación: mover solo `datos.parquet`, `datos_th1c2_020926.parquet`
y los dos archivos `Data_Esp1_20260714_0921.*` (evidencia mínima necesaria de
H-B/N-1, ~230 MB), y **eliminar** los tres CSV `Data_Esp1_202607/09*` de
527-557 MB y los tres checkpoints de 200-230 MB — son exports intermedios sin
ninguna columna o corrección que no esté ya en el dataset canónico. Esto es
una decisión de espacio en disco, no de auditabilidad, así que queda marcada
**[DECIDIR]** para el usuario en vez de asumida.

---

## 5. Diagnóstico, dominio (guardias/piscinas) y línea de regímenes de mineral

| Origen | Destino | Cambios de código |
|---|---|---|
| `verificaciondata.py` | `src/espesadores/calidad/diagnostico_extraccion.py` | **Sí.** Ruta AF SDK (línea 65) y `SERVIDOR_NOMBRE` (línea 50) → `conf/local` / `conf/base/extraccion.yaml`. |
| `verificaciondata-checkpoint.py` | — | Eliminar. |
| `diagnostico_calidad_rebose.csv` | `data/06_reporting/diagnosticos/diagnostico_calidad_rebose.csv` | No. Regenerar tras cada corrida de extracción, no es dato fijo. |
| `diagnostico_cobertura_mensual.csv` | `data/06_reporting/diagnosticos/diagnostico_cobertura_mensual.csv` | No. |
| `diagnostico_congelamiento.csv` | `data/06_reporting/diagnosticos/diagnostico_congelamiento.csv` | No. |
| `diagnostico_deriva.py` | `notebooks/regimenes_mineral/diagnostico_deriva.py` | No, pero **[DECIDIR]**: su consumidor declarado (`analisis_espesador_v3.py`) no existe; preguntar al usuario si se retoma esa línea o se descarta el script. |
| `segmentos.json` | `data/99_deprecated/segmentos.json` | No. Salida huérfana, sin consumidor vivo. |
| `rol_guardias.py` | `src/espesadores/dominio/guardias.py` | **Sí.** `MINUTO_INICIO_A/B` → `conf/base/reglas_operativas.yaml` (fuente única con `TURNOS`). |
| `Rol_Operaciones_2024/2025/2026.md` | `data/00_raw/rol_operaciones/Rol_Operaciones_202X.md` | No. Son fuente/insumo, no salida procesada — de ahí `00_raw` y no `01_interim`. |
| `Rol_Operaciones_202X-checkpoint.md` (×3) | — | Eliminar (idénticos). |
| `calendario_guardias.parquet` | `data/01_interim/calendario_guardias.parquet` | No. |
| `nivel_piscinas.py` | `src/espesadores/dominio/piscinas.py` | **Sí.** (a) `COL_A/COL_B` hardcodeados → `conf/base/tags.yaml`; (b) `HORAS_CAMBIO_GUARDIA` 07:00/19:00 → **corregir a 07:30/19:30 (confirmado por el usuario)** y tomarlo de `reglas_operativas.yaml` (fuente única con `guardias.py`); (c) `--umbral` default (5 pp) → ajustar al valle del histograma de divergencia según §5.1 del traspaso, antes de fijarlo en YAML. Regla de fondo (promedio si parecidos, mayor si difieren mucho) queda **confirmada por el usuario**, no cambia. |
| `nivel_piscinas_derivado.parquet` | `data/01_interim/nivel_piscinas_derivado.parquet` | No. Regenerar tras corregir (b) y (c). |

### Línea de regímenes de mineral (exploración, sin dataset de entrada vigente)

Todo este bloque comparte un problema: sus entradas (`dataset_con_regimen.csv`,
`dataset_regimenes_v2.csv`, `Data_Esp1_20260714_0921.csv`) no existen hoy en
disco (ver inventario, huérfanos §14). No se proponen como `src/` porque no
están validados de punta a punta contra el dataset canónico — son la
investigación que sustenta (parcialmente) H-D, no un pipeline probado.
**[DECIDIR]** con el usuario si esta línea se retoma (en cuyo caso conviene
adaptarla al esquema de 68 tags y moverla a `src/espesadores/modelado/` como
insumo de la etapa predictiva) o se archiva tal cual como antecedente.

| Origen | Destino propuesto | Cambios de código |
|---|---|---|
| `io_espesador.py` | `notebooks/regimenes_mineral/io_espesador.py` | No al código. Está atado al formato `x1..y8` de `Data_Esp1_*`, ya deprecado — si se retoma la línea, reescribir contra el esquema PI de 68 tags en vez de reutilizarlo. |
| `regimenes_mineral.py` (v1) | `notebooks/regimenes_mineral/v1_regimenes_mineral.py` | No. Superseded por v2 según su propio docstring; se conserva como antecedente, no para ejecutar. |
| `regimenes_v2.py` | `notebooks/regimenes_mineral/v2_regimenes_mineral.py` | No al código en sí. Su ruta de salida (`dataset_regimenes_v2.csv`, hardcodeada como default) debería apuntar a `data/03_features/` si se retoma. |
| `test_escala_temporal.py` | `notebooks/regimenes_mineral/test_escala_temporal.py` | No. Entrada rota (`dataset_con_regimen.csv`); requiere que `regimenes_mineral.py` o `regimenes_v2.py` corra primero. |
| `test_mineral_vs_operador.py` | `notebooks/regimenes_mineral/test_mineral_vs_operador.py` | **Sí si se retoma:** `INPUT = "datos.parquet"` apunta al dataset contaminado (mismo problema que N-1) → cambiar a `data/00_raw/espesadores_20260906_1317.parquet`. |
| `test_mineral_vs_operador-checkpoint.py` | — | Eliminar. |
| ~~`test_cluster.ipynb`~~ | `notebooks/regimenes_mineral/v2_test_mineral_vs_operador.py` (celda 2 extraída) | **Ejecutado (2026-09-06).** Celda 1 descartada (duplicado exacto de `test_mineral_vs_operador.py`); celda 2 (v2, N-4) extraída antes de eliminar el notebook. |
| ~~`test_cluster-checkpoint.ipynb`~~ | — | **Ejecutado (2026-09-06).** Eliminado: diff de celdas confirmó que ninguna difiere en código del vivo. |
| `demanda_agua.py` | `notebooks/regimenes_mineral/demanda_agua.py` | No al código. Ambas entradas por defecto (`dataset_regimenes_v2.csv`, `Data_Esp1_20260714_0921.csv`) no existen; no ejecutable hasta que la línea se retome. |
| ~~`TEST1.ipynb`~~ | — | **Ejecutado (2026-09-06).** Eliminado sin extracción: sus correcciones v2→v3 (muestreo, filtro de paradas, trenes A/B) ya están implementadas en `pipeline_espesadores.py` (E01, E03, E04). |
| ~~`TEST2_2YEARS.ipynb`~~ | — | **Ejecutado (2026-09-06).** Eliminado (driver de `diagnostico_deriva.py`, que se conserva como `.py`). |
| ~~`TEST3_2YEARS.ipynb`~~ | — | **Ejecutado (2026-09-06).** Eliminado (driver de `regimenes_v2.py`, que se conserva como `.py`). |
| ~~`pipeline.ipynb`~~ | — | **Ejecutado (2026-09-06).** Eliminado (vacío, sin contenido). |
| ~~`pipeline-checkpoint.ipynb`~~ | — | **Ejecutado (2026-09-06).** Eliminado. |

---

## 6. Pipeline principal, configuración, I/O y salidas

| Origen | Destino | Cambios de código |
|---|---|---|
| `config_espesadores.py` | Se reparte en 4 archivos: `conf/base/tags.yaml` (GLOBALES + tags por espesador + los 5 tags "aparte" ya resueltos por N-2), `conf/base/calidad.yaml` (RANGOS_POR_TIPO, DIAGNOSTICO), `conf/base/reglas_operativas.yaml` (TURNOS, PROCESO, y los valores de `piscinas.py`/`guardias.py` unificados), `conf/base/pipeline.yaml` (VENTANAS_MIN, CV_ESTADO_ESTACIONARIO, RUTAS ya corregido — N-1). | **Sí, es la migración central.** Todo módulo de `src/` pasa de `from config_espesadores import X` a cargar estos YAML. |
| `config_espesadores-checkpoint.py` | — | Eliminar. |
| `config_espesadores.cpython-311.pyc` | — | Eliminar. Añadir `__pycache__/`, `*.pyc` a `.gitignore`. |
| `pipeline_espesadores.py` | Se divide en `src/espesadores/pipeline/e01_carga.py` … `e11_trenes.py` + `src/espesadores/pipeline/orquestador.py` (llama a las 11 en orden, arma `ctx`, escribe manifiesto). | **Sí, es el cambio de código más grande del proyecto.** Requisito explícito de la sección 6: "una etapa por módulo, interfaz común". Cada función ya tiene la firma `(df, cfg, ctx) -> df`, así que la interfaz común ya existe — el trabajo es de separación de archivo, no de rediseño. `guardar()` deja de escribir en `salidas/` relativo a cwd y escribe en `data/06_reporting/` (o `data/02_primary`/`03_features` según la etapa, ver más abajo). |
| `pipeline_espesadores-checkpoint.py` | — | Eliminar. |
| `io_espesador.py` | `notebooks/regimenes_mineral/io_espesador.py` (ver §5) | No al código de producción — no lo usa `pipeline_espesadores.py`, solo la línea de regímenes de mineral. |
| `onepager_espesadores.py` | `src/espesadores/reportes/onepager.py` | No hay tags/rutas quemadas (verificado). Solo actualizar el import del contexto que recibe. |
| `onepager_espesadores.cpython-311.pyc` | — | Eliminar. |
| `onepager_TH001.html` | `data/99_deprecated/salidas_20260727_datos_parquet/onepager_TH001.html` | No. Generado contra `datos.parquet` contaminado (N-5) — se archiva como evidencia, se regenera fresco en `data/06_reporting/` en la Tarea C. |
| `E01_perfil_estructural.csv` … `E11c_cizalle.csv` (19 archivos) y sus `-checkpoint` (6 idénticos) | Vivos → `data/99_deprecated/salidas_20260727_datos_parquet/`; checkpoints → eliminar. | No al contenido. Regenerar todos en `data/06_reporting/` tras resolver N-1. |
| `REPORTE_COMPLETO.txt` | `data/99_deprecated/salidas_20260727_datos_parquet/REPORTE_COMPLETO.txt` | No. Su propia cabecera declara `datos.parquet` como entrada (evidencia de N-1/N-5). |

---

## 7. Documentación y entorno

| Origen | Destino | Cambios de código |
|---|---|---|
| `LEEME.md` | `espesadores/README.md` | No al código. Sí al contenido: actualizar cifras (fueron calculadas contra `datos.parquet`, N-1) y comandos de uso a las rutas nuevas. |
| `glosario_espesador.md` | `docs/glosario_espesador.md` | No. |
| `glosario_espesador-checkpoint.md` | — | Eliminar. |
| `PROMPT_CLAUDE_CODE.md` | `docs/traspaso_20260906.md` (o se deja en la raíz como registro histórico) | No. **[DECIDIR]** dónde prefiere el usuario conservarlo. |
| `pixi.toml` | `espesadores/pixi.toml` | **Sí.** Agregar `pyarrow` (falta por completo — ni `pd.read_parquet` funciona hoy en este entorno), `statsmodels` (instalado en el entorno pero ausente del archivo — falla de reproducibilidad ya detectada en la Tarea A), y evaluar `hmmlearn`/`ruptures` si se retoma la línea de regímenes de mineral. `pythonnet`/AF SDK son Windows-only: documentar como grupo opcional o feature aparte, no se pueden instalar en este entorno Linux. |
| `pixi.lock` | `espesadores/pixi.lock` | Se regenera solo al correr `pixi install` tras editar `pixi.toml`. |
| `.gitignore` | `espesadores/.gitignore` | **Sí**, ampliar (ver §8). |
| `.gitattributes` | `espesadores/.gitattributes` | No. |

---

## 8. `.gitignore` propuesto (reemplaza al actual)

```gitignore
# entorno
.pixi/*
!.pixi/config.toml

# checkpoints y compilados de Jupyter/Python
**/*-checkpoint.*
.ipynb_checkpoints/
__pycache__/
*.pyc

# configuración local (credenciales, rutas de máquina)
conf/local/*
!conf/local/.gitkeep

# datos (se versiona la estructura, no el contenido pesado)
data/00_raw/*
data/01_interim/*
data/02_primary/*
data/03_features/*
data/04_model_input/*
data/05_models/*
data/06_reporting/*
data/99_deprecated/*
!data/**/.gitkeep
!data/**/README.md
```

---

## 9. Rescatados de `.ipynb_checkpoints/` — ya no son huérfanos (ver N-7)

**Actualizado 2026-09-06.** Se analizó el contenido completo de estos 5
archivos (a pedido del usuario, para decidir si se borraban) y resultó ser
trabajo real y valioso, no basura: `01_eda` contiene la prueba cuantitativa de
exclusión mutua entre bombas que probablemente originó el Principio #6
(trenes acoplados), y `02_scaler` un enfoque de clustering (GMM+BIC) no
documentado en ningún otro script. Ya se movieron a `notebooks_historicos/`
en la raíz (fuera de `.ipynb_checkpoints/`, para que no se pierdan en una
limpieza futura). Faltan solo de ubicar en la estructura final:

| Origen (ya rescatado) | Destino en la migración | Cambios de código |
|---|---|---|
| `notebooks_historicos/01_eda_lineas_A_B.ipynb` | `notebooks/regimenes_mineral/01_eda_lineas_A_B.ipynb` | No. Contiene rutas absolutas de otra máquina (`/home/fito/Proyects/...`) en las celdas de escritura — no ejecutable tal cual, se conserva como referencia de lectura. |
| `notebooks_historicos/02_scaler_clustering_gmm.ipynb` | `notebooks/regimenes_mineral/02_scaler_clustering_gmm.ipynb` | No. Depende de `df_a_limpio.csv`/`df_b_limpio.csv`, que migran junto. |
| `notebooks_historicos/curva_codo_bic_linea_b.png` | `notebooks/regimenes_mineral/curva_codo_bic_linea_b.png` | No. |
| `notebooks_historicos/df_a_limpio.csv` | `data/99_deprecated/df_a_limpio.csv` (o `data/01_interim/` si se retoma esta línea — ver **[DECIDIR]** ítem 4) | No. |
| `notebooks_historicos/df_b_limpio.csv` | `data/99_deprecated/df_b_limpio.csv` (ídem) | No. |

**[DECIDIR] nuevo, N-7:** ¿quién es "fito"? La ruta absoluta en `01_eda`
(`/home/fito/Proyects/data4Espesadores/...`) sugiere trabajo de otra persona o
en otro entorno, no descrito en `PROMPT_CLAUDE_CODE.md`. Vale la pena
preguntar antes de dar por cerrada la Tarea A/B.

---

## 10. Resumen de decisiones pendientes del usuario (bloquean la Tarea C si no se resuelven)

1. Confirmar la corrección de N-1 (`RUTAS["entrada"]` → dataset canónico) antes de correr nada.
2. Autorizar eliminar los 54 `bloque_*.parquet` (~215 MB, N-3) y los 3 archivos `Data_Esp1_2026{07,09}*.csv` (~1,6 GB) en vez de migrarlos.
3. Dónde conservar `PROMPT_CLAUDE_CODE.md`.

Resueltos por el usuario (2026-09-06):

- ~~N-7 ("fito")~~ — confirmado: es otro proyecto sin relación con este. `01_eda_lineas_A_B.ipynb`/`02_scaler_clustering_gmm.ipynb` se conservan solo como antecedente de lectura (no ejecutable tal cual, ruta ajena), en `notebooks/regimenes_mineral/`.
- ~~Destino de `Untitled.ipynb`, `getData.ipynb`, `TEST1.ipynb`, `TEST2_2YEARS.ipynb`, `TEST3_2YEARS.ipynb`, `test_cluster.ipynb`~~ — **eliminados** (no archivados) por indicación del usuario: no habrá otra extracción desde este proyecto (`getDataAllTH.py` es el script vigente; si se repite, será desde otra máquina con su propio script). Antes de borrar se extrajo lo que tenía valor no duplicado: la prueba de namespace de `Untitled.ipynb` → `docs/decisiones/001_namespace_af_pi.md`; la celda v2 de `test_cluster.ipynb` → `notebooks/regimenes_mineral/v2_test_mineral_vs_operador.py`. `TEST1/2/3` no tenían contenido no capturado ya en `pipeline_espesadores.py`/`regimenes_v2.py`, se eliminaron sin extracción.
- ~~Línea de regímenes de mineral~~ — queda como antecedente archivado en `notebooks/regimenes_mineral/`, no se retoma como parte de esta migración (no se pidió explícitamente).

Resueltos por el usuario (2026-09-06), ya incorporados en el plan:

- ~~Regla LIT_106/LIT_107~~ — confirmada: promedio si son parecidos, el mayor si difieren mucho. Falta solo el umbral numérico exacto (valle del histograma, §5.1 del traspaso), a fijar cuando se corra `nivel_piscinas.py` con datos reales.
- ~~Horario de turnos en `nivel_piscinas.py`~~ — confirmado 07:30/19:30 (turno A) y 19:30/07:30 (turno B); el 07:00/19:00 del script queda identificado como bug a corregir, no como supuesto abierto.
- ~~Criterio de vigencia entre datasets `.parquet` homónimos~~ — confirmado: manda el timestamp del nombre de archivo, el más reciente es el vigente.
