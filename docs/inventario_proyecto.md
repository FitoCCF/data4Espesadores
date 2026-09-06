# Inventario del proyecto — Espesadores C2 (TH-001/002/003)

Generado como Tarea A de `PROMPT_CLAUDE_CODE.md`. Cobertura: **167 archivos**,
carpeta única y plana (no hay subcarpetas de proyecto; solo existían
`.pixi/` y `.ipynb_checkpoints/`, ambas excluidas del recuento anterior salvo
donde se indica).

> **Actualización 2026-09-06 (post-Tarea B):** por pedido explícito del
> usuario se analizó a fondo el contenido de los notebooks huérfanos para
> decidir cuáles borrar. Eso cambió la clasificación de la sección 11 (de
> "desconocido" a "valioso, rescatado") y motivó las únicas acciones
> destructivas de esta fase: se **rescataron** (movieron, no copiaron) los 5
> archivos de `.ipynb_checkpoints/` sin original vivo a `notebooks_historicos/`
> con nombres descriptivos, y luego se **borraron** 5 archivos confirmados sin
> ningún contenido único (`pipeline.ipynb`, `pipeline-checkpoint.ipynb`,
> `Untitled-checkpoint.ipynb`, `getData-checkpoint.ipynb`,
> `test_cluster-checkpoint.ipynb`), verificado por diff de celdas o hash antes
> de borrar. Ver **N-7** y la sección 11 actualizada. El resto del inventario
> sigue reflejando el estado original; ningún otro archivo fue movido ni
> borrado.

Metodología: cada propósito se infirió leyendo el contenido (docstring,
imports, `argparse`, llamadas `read_*`/`to_*`) — no del nombre. Para los
datasets se leyó el esquema real con `pyarrow` (instalado en un directorio
temporal fuera del entorno del proyecto, solo para esta auditoría de
solo-lectura; no se tocó `pixi.toml`). Para los notebooks se parseó el JSON de
celdas. Varias afirmaciones se verificaron por huella de datos, no solo por
lectura de código (ver hallazgos nuevos §0).

---

## 0. Hallazgos nuevos de esta auditoría (no estaban en el traspaso)

Estos se descubrieron leyendo contenido, no nombres. Recomendado incorporarlos
a `docs/bitacora_hallazgos.md` en la Tarea D, con nivel de confianza CONFIRMADO
salvo donde se indique.

### N-1. El pipeline de producción apunta al dataset contaminado, no al canónico — CONFIRMADO, CRÍTICO

`config_espesadores.py` → `RUTAS["entrada"] = "datos.parquet"`. Ese archivo:

- Tiene 31 columnas / 1.064.161 filas (esquema antiguo, sin `Alim_Total_PB02`,
  sin TH-002/TH-003, sin los 5 tags nuevos).
- **Tiene la huella exacta del artefacto de `ffill` (H-B):** `FLUJO_REBOSE_AGUA_TH1`
  da 0% NaN pero un solo valor ocupa el **70,55%** de las filas válidas
  (verificado con `pyarrow.compute.value_counts`, sin cargar pandas). Es el
  mismo patrón que el traspaso solo había detectado en la familia `Data_Esp1_*`.
  El mismo chequeo sobre `datos_th1c2_020926.parquet` da **66,84%** — también
  contaminado.
- Es, verificado por huella de fecha y por la cabecera de `REPORTE_COMPLETO.txt`
  (`Archivo: datos.parquet · 1.064.161 filas x 31 columnas · rango
  2024-07-14→2026-07-23`), **el archivo que efectivamente generó** los E01–E11,
  `REPORTE_COMPLETO.txt` y `onepager_TH001.html` que hoy están en la raíz.

**Consecuencia:** el traspaso (sección 5.bis) señala que E01–E11 "se generaron
con un dataset previo al de 68 columnas" y deben regenerarse — cierto, pero la
causa raíz no estaba identificada: **nadie actualizó `RUTAS["entrada"]`**. Si
alguien ejecuta `pipeline_espesadores.py` hoy tal cual está, sin tocar nada más,
vuelve a producir salidas contaminadas por el mismo bug de `ffill` que motivó
esta sesión completa. Esto es exactamente el tipo de "bug silencioso" que el
Principio #2 del traspaso pide vigilar.

**Acción para la Tarea B/C:** cambiar `RUTAS["entrada"]` a
`datos_espesadores_20260906_1317.parquet` (o, tras la migración, a la ruta en
`02_primary/`) antes de considerar vigente cualquier salida nueva del pipeline.

### N-2. Los cinco tags no identificados de la sección 5.2 ya están resueltos en disco — CONFIRMADO

`Atributos_PI_20260904_1735-checkpoint.csv` (y su gemelo `_1739`) trae el
descriptor PI completo de los 63 tags de esa corrida, incluidos los 5 dudosos:

| Tag | Descriptor PI | Unidad |
|---|---|---|
| `FIT_114` | Flujo hacia Piscinas | m³/h |
| `LIT_106` | Nivel agua recup. 296300XC001 — Recuperación de Agua QH **Piscina 1** | % |
| `LIT_107` | Nivel agua recup. 296300XC002 — Recuperación de Agua QH **Piscina 2** | % |
| `LIT_108` | Nivel 294300TK001 — Recuperación de Agua Espesadores Relaves (**tanque 1**) | % |
| `LIT_109` | Nivel 294300TK002 — Recuperación de Agua Espesadores Relaves (**tanque 2**) | % |

Esto confirma exactamente la hipótesis del propio traspaso en §5.1 (LIT_106/107
son los dos transmisores de piscina que alimentan `nivel_piscinas.py`) y en
§5.2 (LIT_108/109 son los tanques temporales TK001/TK002, distintos de las
piscinas). **No hace falta gestión con Instrumentación** para esta parte de
5.2; ya se puede escribir en `conf/base/tags.yaml` con su descripción correcta.
Las búsquedas `Busqueda_X2101XPPX...` son de un tema **no relacionado**
(amperaje/horómetro de bombas de lamas del área 2101 / QH) — confirma la nota
del traspaso de que hay una línea de trabajo abierta que hay que preguntarle
al usuario.

### N-3. Los 53 `bloque_*.parquet` en disco son íntegramente de la corrida vieja (63 tags), no solo `bloque_0001` — CONFIRMADO

El traspaso (5.bis) marcaba solo `bloque_0001_20240714.parquet` como huérfano.
Verificado el esquema de los 53 bloques con `pyarrow`: **los 53 tienen 64
columnas** (63 tags + timestamp), ninguno tiene 69. Sumando filas de la cadena
válida (`_20240714_20240729` + bloques 2–52 + 53) da exactamente 1.127.520
filas — coincide EXACTO con `datos_espesadores_20260905_1912.parquet` (64
columnas). Es decir: **todo el directorio de chunks-checkpoint pertenece a la
corrida de 63 tags, previa a la corrección de PB02**, y ya no coincide con
`_esquema.json` actual (69 nombres, esquema de la corrida de 68 tags).

**Verificación de que esto NO contaminó el dataset canónico:** se comprobó la
cobertura mensual de `Alim_Total_PB02` en `datos_espesadores_20260906_1317.parquet`
y es ~100% en TODO el rango 2024-07 a 2026-09, incluyendo el período cubierto
por los chunks viejos. Si la corrida canónica hubiera reutilizado esos chunks
por resume, `Alim_Total_PB02` habría quedado NaN en ese tramo. **No fue así: la
corrida canónica fue una extracción fresca completa.** El riesgo es solo
latente hacia adelante: `guarda_esquema()` en `getDataAllTH.py` valida la LISTA
de columnas contra `_esquema.json`, pero no valida el esquema de cada archivo
`bloque_*.parquet` individual contra ese registro. Si alguien borra solo
`_esquema.json` (no los chunks) y reanuda, el guard no detectaría el desfase y
reutilizaría silenciosamente chunks de 63 tags bajo un esquema de 68. No
ocurrió esta vez, pero es un hueco real en la guarda.

**Acción:** borrar (no archivar) los 53 `bloque_*.parquet` antes de cualquier
futura re-extracción con `REANUDAR=True`; son ~230 MB de un estado ya
superado y su sola presencia es el vector del riesgo descrito.

### N-4. `test_cluster.ipynb` no es un duplicado puro — contiene una v2 sin script propio — CONFIRMADO

La celda 1 es **byte-idéntica** a `test_mineral_vs_operador.py` (9630
caracteres, hash igual). Pero la celda 2 contiene una segunda versión completa
("DETECCION DE TIPO DE MINERAL + TEST DE INFLUENCIA SOBRE EL OPERADOR v2") que
**no existe como archivo `.py` independiente en ningún lugar del proyecto**.
Archivar o descartar este notebook sin extraer esa celda perdería esa versión.

### N-5. Todas las salidas E01–E11 + `REPORTE_COMPLETO.txt` + `onepager_TH001.html` comparten el mismo origen contaminado

Ver N-1: la cabecera de `REPORTE_COMPLETO.txt` declara textualmente
`Archivo: datos.parquet`. Estos artefactos no son solo "anteriores a los 68
tags" (como decía el traspaso) sino que además **arrastran el artefacto de
`ffill`** en cualquier cifra que dependa de `FLUJO_REBOSE_AGUA_TH1`/`_G`. El
resto de E01-E11 (trenes, estado estacionario, mineral) no depende de esos
tags y su lógica es reutilizable; lo que hay que regenerar es la ejecución
completa contra el dataset canónico, no reescribir el código.

### N-7. Los 5 huérfanos de `.ipynb_checkpoints/` NO eran descartables — son el origen probable del hallazgo de "trenes acoplados" — CONFIRMADO

La sección 11 original los dejaba como "desconocido" por falta de original vivo
con el que compararlos. Leído su contenido completo:

- **`01_eda-checkpoint.ipynb`** (rescatado como `01_eda_lineas_A_B.ipynb`): EDA
  sobre un CSV `Data_Esp1_20260613_1853.csv` (familia `x1..y8`, ya no existe
  ese CSV puntual). Su sección 6 ("Análisis de Exclusión Mutua entre (x1,x3) y
  (x2,x4)") verifica cuantitativamente que las bombas del grupo A (`x1`,`x3`)
  y del grupo B (`x2`,`x4`) nunca están activas al mismo tiempo — **es, con
  alta probabilidad, el análisis original que sustenta el Principio #6 del
  traspaso** ("los trenes de bombeo están totalmente acoplados... 0
  combinaciones cruzadas"). También contiene una función
  `limpiar_dataset_industrial_v3` (filtro Hampel + splines) que produjo
  `df_a_limpio.csv`/`df_b_limpio.csv` — un dataset limpio partido por línea,
  independiente del que usa el pipeline actual.
- **`02_scaler-checkpoint.ipynb`** (rescatado como `02_scaler_clustering_gmm.ipynb`):
  toma `df_a_limpio.csv`, estandariza con `StandardScaler` y evalúa número de
  clusters con `GaussianMixture` + criterio BIC (método del codo). Es un
  **enfoque de clustering para regímenes distinto** al de `regimenes_mineral.py`
  (KMeans) y `regimenes_v2.py` (HMM) — no está mencionado en ningún otro lugar
  del proyecto ni del traspaso.
- **`curva_codo_bic_linea_b-checkpoint.png`**: es literalmente el gráfico que
  produce la celda de evaluación BIC de `02_scaler`. Sin valor si se separa del
  notebook, con valor como figura de esa exploración.
- **`df_a_limpio-checkpoint.csv`** / **`df_b_limpio-checkpoint.csv`**: salidas
  de `01_eda`, entrada de `02_scaler`. Verificado el header: `df_a_limpio`
  (524.612 filas, línea A, sin `x2/x4`) empieza 2025-01-01; `df_b_limpio`
  (235.050 filas, línea B, sin `x1/x3`, con `y5` en vez de `y4`) empieza
  2025-01-02. Consistentes entre sí y con la hipótesis de exclusión mutua de
  `01_eda`.

**Dato adicional — resuelto:** `01_eda` escribe a
`/home/fito/Proyects/data4Espesadores/data/processed` — una ruta absoluta de
otra máquina/usuario ("fito"). **Confirmado por el usuario (2026-09-06): es
otro proyecto sin relación con este.** Los dos notebooks se conservan solo
como antecedente de lectura (no ejecutables tal cual, por esa ruta ajena).

**Acción tomada:** los 5 archivos se movieron (no copiaron) de
`.ipynb_checkpoints/` a `notebooks_historicos/` con nombres descriptivos, antes
de que cualquier limpieza futura de checkpoints los borrara por error. No se
modificó su contenido.

### N-6. `E05_balance_agua.csv` está menos expuesto a H-C de lo que temía el traspaso

El traspaso (§5.bis, prioridad 1) advertía que `E05_balance_agua.csv` era "el
más expuesto a H-C" por si usó el tag crudo de rebose. Leído el código
(`pipeline_espesadores.py::e05_balance`): **no usa el tag `FLUJO_REBOSE_AGUA_*`
en ningún momento.** Recalcula `rebose` desde el balance de agua
(`agua_alim - agua_descarga`) usando `wt_activo` (WT_146/WT_144, cobertura
casi completa desde 2024-07 según H-F) y el tonelaje del molino. Es
exactamente la "ruta alternativa" que H-C recomienda como ancla — el pipeline
ya la implementa por diseño, aunque por una razón distinta (el estimador del
DCS se congela 70,5% del tiempo). Sí sigue expuesto a **N-1** (dataset de
entrada equivocado) y a **H-A** (si `datos.parquet` tiene el bug de PB01/PB02;
no tiene `Alim_Total_PB02` en absoluto, así que el reparto de tonelaje por
partición no está afectado por ese bug específico, pero sí por estar en el
esquema viejo de 31 columnas). Esto se puede escribir en la bitácora como
corrección al propio traspaso.

---

## 1. Datasets candidatos — cuál es vigente

| Archivo | Filas | Columnas | Fecha | Veredicto |
|---|---|---|---|---|
| **`datos_espesadores_20260906_1317.parquet`** | 1.123.200 | 69 (68 tags + timestamp) | 2026-09-06 13:17 | **CANÓNICO.** Único con TH-002/TH-003 completos, PB02 corregido, sin `ffill`. |
| `datos_espesadores_20260905_1912.parquet` | 1.127.520 | 64 | 2026-09-05 19:12 | Corrida inmediatamente anterior (63 tags, previa a PB02). Superseded. |
| `datos_espesadores_PRUEBA_20260905_1811.parquet` | 2.880 | 64 | 2026-09-05 18:11 | Prueba de humo (2 días) de la corrida anterior. Correcto que exista, no usar para análisis. |
| `datos.parquet` | 1.064.161 | 31 | 2026-07-25 21:15 | **Contaminado (ver N-1):** huella de `ffill` confirmada (70,55% de un solo valor en rebose TH1). Es el `RUTAS["entrada"]` actual del pipeline — **hay que cambiarlo**. |
| `datos_th1c2_020926.parquet` | 1.123.201 | 31 | 2026-09-02 11:02 | Mismo esquema de 31 col. que `datos.parquet`, generado por `getData.ipynb` desde `Data_Esp1_20260902_1056.csv`. También contaminado (66,84% moda en rebose TH1). |
| `Data_Esp1_20260714_0921.parquet` (+ `.pkl` gemelo) | 1.051.201 | 19 (`x1`..`y8`) | 2026-07-14 | Extracción original con nombres genéricos `x/y`, con `ffill().bfill()` aplicado (confirmado por el propio traspaso, H-B). **No usar.** |
| `Data_Esp1_20260613_*.csv` (3 checkpoints), `Data_Esp1_20260724_1545.csv`, `Data_Esp1_20260901_0727.csv`, `Data_Esp1_20260902_1056.csv` | — | — | 2026-06 a 2026-09 | Exports CSV de la misma familia `x/y`, tamaños 200–557 MB. Fuente cruda de `Data_Esp1_20260714_0921.*` y de `datos_th1c2_020926.parquet`. Todas heredan el problema de `ffill` del script original. |

**Recomendación (ya adelantada por el propio traspaso, aquí confirmada con
evidencia adicional):** mover toda la familia `Data_Esp1_*`, `datos.parquet` y
`datos_th1c2_020926.parquet` a `data/99_deprecated/` con un `README.md` que
cite N-1 y H-B como motivo. Son ~1,66 GB en conjunto.

---

## 2. Extracción PI y descubrimiento de tags

| Ruta | Tamaño | Modificado | Propósito (inferido del contenido) | Clasificación |
|---|---:|---|---|---|
| `getDataAllTH.py` (alias `extraccion_pi_espesadores.py` en su docstring) | 35.307 B | 2026-09-06 12:21 | Extracción bulk PI AF SDK (namespace `AF.PI`), troceado de 15 días con checkpoint/resume, manifiesto y `guarda_esquema()`. **Vigente**, generó el dataset canónico. | producción |
| `getDataAllTH-checkpoint.py` | ídem | — | Checkpoint de Jupyter, byte-idéntico al anterior. | duplicado (basura) |
| `getAtributes.py` | 4.554 B | 2026-09-04 17:38 | Utilidad interactiva (`input()`) que consulta 52 atributos PI por patrón de tag y exporta CSV. Generó los `Atributos_PI_*`. | producción (utilidad) |
| `getAtributes-checkpoint.py` | ídem | — | Idéntico al anterior. | duplicado (basura) |
| `searchTAg.py` | 3.841 B | 2026-09-04 18:19 | Igual patrón que `getAtributes.py` pero para búsqueda de tags por patrón (`Busqueda_*`). | producción (utilidad) |
| `searchTAg-checkpoint.py` | ídem | — | Idéntico. | duplicado (basura) |
| `getData.ipynb` | 26.661 B | 2026-09-05 17:14 | Notebook de extracción **anterior** a `getDataAllTH.py`: usa `OSIsoft.AF.Data` (namespace incorrecto, corregido en H-lista del traspaso). Generó `Data_Esp1_20260902_1056.csv` → `datos_th1c2_020926.parquet`. | obsoleto (superseded) |
| `getData-checkpoint.ipynb` | ídem | — | Idéntico. | duplicado (basura) |
| `Untitled.ipynb` | 1.473 B | 2026-09-05 18:03 | 2 celdas: prueba puntual de si `PIPointList().InterpolatedValues` existe en `AF.PI` vs `AF.Data`. Es, con alta probabilidad, **el registro de la decisión de namespace** citada en `getDataAllTH.py` (corrección #3). **No archivar sin confirmar con el usuario** — el traspaso lo pide explícitamente. | exploración (posible valor histórico) |
| `Untitled-checkpoint.ipynb` | 72 B | 2026-09-05 17:59 | Checkpoint **anterior a la edición** (solo 72 B vs 1.473 B del vivo) — no es un duplicado exacto, es un estado más viejo. | basura (checkpoint desactualizado) |
| `Atributos_PI_20260904_1732-checkpoint.csv` | 1.168 B | 2026-09-04 17:32 | Export parcial (solo 2 columnas: tag/alias), primera corrida de `getAtributes.py`. | dato (exploración, superseded) |
| `Atributos_PI_20260904_1735-checkpoint.csv` | 17.042 B | 2026-09-04 17:35 | Export completo (52 atributos) de 63 tags. **Resuelve N-2.** | dato (referencia — promover a `docs/`) |
| `Atributos_PI_20260904_1739-checkpoint.csv` | 17.042 B | 2026-09-04 17:39 | Idéntico contenido a `_1735` (diff vacío). | duplicado |
| `Busqueda_X294100X_20260904_1818-checkpoint.csv` | 277.908 B | 2026-09-04 18:18 | Búsqueda amplia `*294100*` (área de espesadores). Sin coincidencias para los 5 tags dudosos (ya resueltos vía `Atributos_PI`). | dato (exploración) |
| `Busqueda_X_294100XFlowX_20260904_1745/1755/1757-checkpoint.csv` | 1.892 B c/u | 2026-09-04 17:45–17:57 | Tres corridas casi idénticas de búsqueda `*294100*Flow*` (columnas difieren levemente entre la primera y las dos últimas, que sí son idénticas entre sí). | dato (exploración, duplicado parcial) |
| `Busqueda_X2101XPPX101X_20260905_1751-checkpoint.csv` | 11.789 B | 2026-09-05 17:51 | Búsqueda de horómetro de bombas **área 2101 (QH)** — tema distinto a espesadores C2. | dato (fuera de alcance — preguntar al usuario, §9.6 del traspaso) |
| `Busqueda_X2101XPPX10XAmperaje_ABB_20260905_1803-checkpoint.csv` | 5.440 B | 2026-09-05 18:03 | Ídem, amperaje de bombas área 2101. | dato (fuera de alcance) |

---

## 3. Datos crudos / chunks de extracción

| Ruta | Tamaño | Modificado | Propósito | Clasificación |
|---|---:|---|---|---|
| `bloque_0001_20240714.parquet` | 569.740 B | 2026-09-05 18:11 | Chunk parcial (2.880 filas), nomenclatura antigua sin fecha de fin. Huérfano señalado por el propio traspaso. | obsoleto |
| `bloque_0001_20240714_20240729.parquet` … `bloque_0053_20260902_20260905.parquet` (53 archivos) | ~1–5 MB c/u, ~215 MB total | 2026-09-05 18:18–19:12 | Chunks de 15 días de la corrida de **63 tags** (ver N-3). Los 53 tienen 64 columnas — ninguno coincide con el `_esquema.json` actual (69 nombres). | obsoleto (todo el lote, no solo el 0001 — ver N-3) |
| `_esquema.json` | 1.175 B | 2026-09-06 12:22 | Lista de 68 nombres de tag + registro de guarda anti-resume-silencioso (`guarda_esquema()`). Es el esquema de la corrida **canónica**, no el de los chunks físicos actuales (ver N-3). | producción (config generada) |

---

## 4. Diagnóstico y calidad de datos

| Ruta | Tamaño | Modificado | Propósito | Clasificación |
|---|---:|---|---|---|
| `verificaciondata.py` (docstring: `diagnostico_extraccion.py`) | 12.207 B | 2026-09-06 13:21 | Partes A (conexión PI, estados AFValue) y B (offline: coincidencia de NaN, `frac_congelado` recalculado, escalones de cobertura). Produce los 3 CSV siguientes. Corre contra el parquet canónico. | producción |
| `verificaciondata-checkpoint.py` | ídem | — | Idéntico. | duplicado (basura) |
| `diagnostico_calidad_rebose.csv` | 420 B | 2026-09-06 13:21 | Salida Parte A: % bueno/no-bueno/estado digital por tag de rebose. Sustenta H-B/H-E. | dato (producción, vigente) |
| `diagnostico_cobertura_mensual.csv` | 11.795 B | 2026-09-06 13:22 | Cobertura mensual de las 68 columnas. Sustenta H-C/H-F. Esquema de 69 columnas → generado contra el dataset canónico. | dato (producción, vigente) |
| `diagnostico_congelamiento.csv` | 2.982 B | 2026-09-06 13:22 | `frac_congelado` recalculado sobre grilla completa (no tras `dropna`). Sustenta H-G. | dato (producción, vigente) |
| `diagnostico_deriva.py` | 12.658 B | 2026-07-14 10:48 | "PASO 2 del pipeline" (v2 del CUSUM de deriva de densímetros por campaña, no por mes calendario). Escribe `segmentos.json`. Declara como consumidor `analisis_espesador_v3.py`, **que no existe en el proyecto**. | exploración (huérfano de salida — ver §6) |
| `segmentos.json` | 823 B | 2026-07-14 10:49 | Salida de una corrida vieja de `diagnostico_deriva.py` sobre `Data_Esp1_20260714_0921.csv` (que ya no existe como `.csv`, solo `.parquet`/`.pkl`). Callejón sin salida: su único consumidor declarado no existe. | dato (obsoleto/huérfano) |

---

## 5. Dominio: guardias y piscinas

| Ruta | Tamaño | Modificado | Propósito | Clasificación |
|---|---:|---|---|---|
| `rol_guardias.py` | 12.969 B | 2026-09-06 14:05 | Parsea los 3 roles `.md`, construye tabla de turnos, mide autocorrelación a 168/336/672 h. Sustenta H-D. | producción |
| `Rol_Operaciones_2024.md` / `2025.md` / `2026.md` | ~15,7 KB c/u | 2026-07-27 01:38 | Rol de turnos C2, fuente de `rol_guardias.py`. Verificado sin huecos (H-D). | dato (fuente, producción) |
| `Rol_Operaciones_2024/2025/2026-checkpoint.md` | ídem | ídem | Idénticos a los vigentes. | duplicado (basura) |
| `calendario_guardias.parquet` | 10.095.443 B | 2026-09-06 14:06 | Salida de `rol_guardias.py`: 1.578.240 filas, tabla de turnos por minuto. | dato (producción, vigente) |
| `nivel_piscinas.py` | 9.285 B | 2026-09-06 14:04 | Deriva nivel de piscina desde LIT_106/LIT_107 (promedio o máximo según divergencia), evalúa R1 (≥75%) y R2 (≥90% a cierre de guardia). Caracteriza antes de derivar (cuantiles, histograma de divergencia). | producción |
| `nivel_piscinas_derivado.parquet` | 20.123.929 B | 2026-09-06 14:07 | Salida de `nivel_piscinas.py` sobre el dataset canónico (mismo timestamp que la corrida más reciente). | dato (producción, vigente — pendiente ajustar `--umbral` según §5.1 del traspaso) |

---

## 6. Regímenes de mineral y pruebas relacionadas

| Ruta | Tamaño | Modificado | Propósito | Clasificación |
|---|---:|---|---|---|
| `regimenes_mineral.py` | 10.151 B | 2026-07-14 11:43 | v1: KMeans sobre 4 índices reológicos (`y3/y1`, `x8/solidos`, etc.). El propio docstring de v2 explica por qué v1 está mal (features endógenas). Escribe `dataset_con_regimen.csv` (no existe hoy en disco). | exploración (superseded por v2) |
| `regimenes_v2.py` | 15.555 B | 2026-07-14 13:55 | v2: índice residual de sedimentabilidad (exógeno) + HMM + PELT como contraste. Corrige los 4 defectos de v1 explicados en su propio docstring. Escribe `dataset_regimenes_v2.csv` (no existe hoy en disco). Invocado desde `TEST3_2YEARS.ipynb`. Es la implementación que corrige el análisis de mineral, mencionada en el traspaso. | exploración (vigente conceptualmente, sin dataset de salida presente) |
| `test_escala_temporal.py` | 8.902 B | 2026-07-14 13:42 | 4 pruebas (duración de corridas, autocorrelación, perfil horario, ciclo de rol) para distinguir mineral vs. operador como driver de régimen. Requiere `dataset_con_regimen.csv`, que no existe → **no ejecutable tal cual hoy**. | exploración (entrada rota) |
| `test_mineral_vs_operador.py` | 9.632 B | 2026-07-26 02:46 | Prueba formal (ARI/NMI/Cramér's V + RandomForest + descomposición de varianza) de independencia mineral↔operador. `INPUT = "datos.parquet"` — **apunta al dataset contaminado** (mismo problema que N-1). Es el script que, por nombre, el traspaso pedía revisar con atención especial. | exploración (lógica válida, entrada a corregir) |
| `test_mineral_vs_operador-checkpoint.py` | ídem | — | Idéntico. | duplicado (basura) |
| `test_cluster.ipynb` | 32.769 B | 2026-09-02 10:32 | Celda 1 = copia exacta de `test_mineral_vs_operador.py`. Celda 2 = una **v2 sin equivalente `.py` en el proyecto** (ver N-4). | exploración (contiene contenido único, no archivar sin extraer la celda 2) |
| `test_cluster-checkpoint.ipynb` | 32.703 B | 2026-07-26 03:56 | Versión **anterior** del mismo notebook (66 B menos) — antecede a la adición de la celda 2. No es un duplicado exacto. | basura (checkpoint desactualizado, sin contenido único adicional) |
| `demanda_agua.py` | 9.407 B | 2026-07-14 17:19 | Preguntas sobre saturación del tanque de agua recuperada y acoplamiento entre los 3 espesadores vía tanque común. Depende de `dataset_regimenes_v2.csv` (no existe) y, dentro de `cargar()`, de `Data_Esp1_20260714_0921.csv` (no existe como `.csv`, solo `.parquet`/`.pkl`). | exploración (entradas rotas, análisis planteado pero no corrido) |
| `TEST1.ipynb` | 62.400 B | 2026-07-13 07:08 | Notebook con 2 versiones de análisis TH-001 pegadas como docstrings (v2: trenes A/B; v3: correcciones de muestreo y filtro de paradas) más una celda que lee `dataset_operacion.csv` (no existe). | exploración (histórico, entrada rota) |
| `TEST2_2YEARS.ipynb` | 20.570 B | 2026-07-14 11:48 | Driver de `diagnostico_deriva.main(...)` sobre `Data_Esp1_20260714_0921.csv` (no existe como csv). | exploración (driver, entrada rota) |
| `TEST3_2YEARS.ipynb` | 28.619 B | 2026-07-14 17:24 | Driver de `regimenes_v2.main(...)`; celdas posteriores leen `dataset_regimenes_v2.csv` (no existe). Contiene el detalle del test HMM/PELT que sustenta H-D indirectamente (ciclo de 12h del mineral vs. el de 336h de guardia). | exploración (driver, entrada rota, valor de referencia) |
| `pipeline.ipynb` | 670 B | 2026-09-02 09:00 | 1 celda vacía. | obsoleto (sin contenido) |
| `pipeline-checkpoint.ipynb` | 615 B | 2026-07-27 05:02 | Checkpoint de una versión distinta y aún más vacía. | basura |

---

## 7. Pipeline principal, configuración e I/O

| Ruta | Tamaño | Modificado | Propósito | Clasificación |
|---|---:|---|---|---|
| `config_espesadores.py` | 13.144 B | 2026-07-27 05:06 | Única fuente de tags/parámetros/rangos físicos por espesador. TH-002/TH-003 tienen la mayoría de sus tags marcados `# <<< COMPLETAR` (no confirmados con Instrumentación). **`RUTAS["entrada"] = "datos.parquet"` es el causante de N-1.** | producción (requiere el fix de N-1 antes de recomputar nada) |
| `config_espesadores-checkpoint.py` | ídem | — | Idéntico. | duplicado (basura) |
| `config_espesadores.cpython-311.pyc` | 4.080 B | 2026-07-27 05:07 | Bytecode compilado, sin valor fuera del intérprete que lo generó. | basura (→ `.gitignore`, borrar) |
| `pipeline_espesadores.py` | 57.139 B | 2026-07-27 06:50 | Pipeline E01–E11 completo (perfilado, diagnóstico, limpieza, trenes, balance de agua, estado estacionario, validación de palanca, mineral, guardias, ventanas óptimas, comparación de trenes). Parametrizado por `config_espesadores.py`, sin tags quemados en el propio archivo (verificado por grep). **E05 no usa el tag crudo de rebose (ver N-6).** | producción (vigente en lógica; su última ejecución usó la entrada equivocada, ver N-1/N-5) |
| `pipeline_espesadores-checkpoint.py` | ídem | — | Idéntico. | duplicado (basura) |
| `io_espesador.py` | 6.663 B | 2026-07-14 10:40 | Carga CSV/parquet con caché parquet↔pickle automática, `float32`, de-duplicado de timestamps. Pensado para la familia `x1..y8` (`Data_Esp1_*`), no para el esquema de 68 tags con nombres PI. Usado por `demanda_agua.py`, `diagnostico_deriva.py`, `regimenes_mineral.py`. | producción (utilidad, pero ligada a datasets ya obsoletos) |
| `onepager_espesadores.py` | 20.089 B | 2026-07-27 06:50 | Genera el HTML de una página estilo ISA-101 (HMI) a partir del contexto que devuelve el pipeline. Sin números fijos (agnóstico de espesador). Produjo `onepager_TH001.html`. | producción |
| `onepager_espesadores.cpython-311.pyc` | 24.075 B | 2026-07-27 06:53 | Bytecode compilado. | basura (→ `.gitignore`, borrar) |
| `onepager_TH001.html` | 17.369 B | 2026-07-27 06:53 | One-pager generado — mismo run contaminado que E01–E11 (ver N-5). | dato (obsoleto, regenerar) |

---

## 8. Salidas E01–E11 del pipeline (corrida de 2026-07-27)

Las 19 salidas siguientes se generaron en la misma corrida (06:51–06:53 del
27-jul-2026), contra `datos.parquet` (ver N-1/N-5: dataset de 31 columnas con
el artefacto de `ffill`). Se listan agrupadas porque comparten origen,
propósito documentado en `LEEME.md`/`REPORTE_COMPLETO.txt`, y veredicto.

| Archivo(s) | Tamaño | Etapa | Clasificación |
|---|---:|---|---|
| `E01_perfil_estructural.csv` | 1.200 B | E01 — perfil estructural | dato (obsoleto, regenerar) |
| `E02_diagnostico_variables.csv` | 259 B | E02 — variables inservibles | dato (obsoleto, regenerar) |
| `E03a_rango_fisico.csv`, `E03b_hampel.csv` | 274 / 246 B | E03 — limpieza | dato (obsoleto, regenerar) |
| `E04_trenes.csv` | 82 B | E04 — trenes duty/standby | dato (obsoleto, regenerar) |
| `E05_balance_agua.csv` (+`-checkpoint`) | 906 B | E05 — balance de agua | dato (obsoleto por N-1, pero lógica ya alineada con H-C — ver N-6) |
| `E06_retencion.csv` | 125 B | E06 — estado estacionario | dato (obsoleto, regenerar) |
| `E07_validacion_palanca.csv` | 245 B | E07 — control de calidad | dato (obsoleto, regenerar) |
| `E08a_comparacion_algoritmos.csv`, `E08b_estabilidad.csv` (+`-checkpoint`) | 729 / 89 B | E08 — tipos de mineral | dato (obsoleto, regenerar) |
| `E09a_guardias_vs_nulo.csv`, `E09b_guardia_vs_mineral.csv`, `E09c_desempeno_por_guardia.csv` | 222 / 212 / 188 B | E09 — efecto de guardias | dato (obsoleto por N-1 **y** por H-D: hay que confirmar qué lags probó antes de recomputar con 336 h) |
| `E10a_brecha_por_mineral.csv`, `E10b_regimenes_por_mineral.csv` (+`-checkpoint`), `E10c_ventana_consolidada.csv` | 166 / 261 / 554 B | E10 — ventanas óptimas | dato (obsoleto, regenerar — es la fuente probable de la ventana operativa recomendada, según §5.bis) |
| `E11a_trenes_crudo.csv` (+`-checkpoint`), `E11b_trenes_emparejado.csv`, `E11c_cizalle.csv` | 144 / 5.326 / 80 B | E11 — comparación de trenes | dato (obsoleto, regenerar) |

Todos los `-checkpoint.csv` de esta sección son idénticos byte a byte a su
contraparte viva (verificado con `md5sum`).

`REPORTE_COMPLETO.txt` (12.778 B, 2026-07-27 06:53) — reporte de auditoría
completo de esa misma corrida, escrito por `pipeline_espesadores.py`. Confirma
por su propia cabecera que la entrada fue `datos.parquet` (ver N-1/N-5).
Clasificación: documentación (obsoleta, regenerar).

---

## 9. Documentación

| Ruta | Tamaño | Modificado | Propósito | Clasificación |
|---|---:|---|---|---|
| `LEEME.md` | 2.605 B | 2026-07-27 05:06 | README del pipeline: uso, tabla de etapas con su sustento metodológico, resultados de TH-001 (control de calidad, sensibilidad, trenes). Cifras de la corrida contaminada — hay que actualizarlas tras N-1. | documentación (vigente en estructura, cifras a refrescar) |
| `glosario_espesador.md` | 13.227 B | 2026-07-27 07:03 | Glosario de términos del one-pager y del `REPORTE_COMPLETO.txt` (roles de variable, etc.). | documentación (vigente) |
| `glosario_espesador-checkpoint.md` | ídem | — | Idéntico. | duplicado (basura) |
| `PROMPT_CLAUDE_CODE.md` | 27.715 B | 2026-09-06 15:06 | El propio encargo/traspaso que originó esta tarea. | documentación (control) |
| `docs/bitacora_hallazgos.md` | — | 2026-09-06 | **Creado en la Tarea D.** No existía en ningún lugar del árbol; incorpora H-A a H-H más N-1 a N-7, todos re-verificados contra el dataset canónico. | documentación (vigente) |

---

## 10. Infraestructura del entorno

| Ruta | Tamaño | Modificado | Propósito | Clasificación |
|---|---:|---|---|---|
| `pixi.toml` | 560 B | 2026-06-24 05:32 | Declara `python`, `jupyterlab`, `pandas`, `numpy`, `matplotlib`, `seaborn`, `scikit-learn`, `tensorflow`, `hdbscan`. | producción (config) |
| `pixi.lock` | 158.600 B | 2026-06-24 05:32 | Lockfile del entorno anterior. | producción (config, generado) |
| `.gitignore` | 47 B | 2026-06-17 12:11 | Solo ignora `.pixi/*`. No ignora `*.pyc`, `*-checkpoint.*`, ni `.ipynb_checkpoints/` — de ahí que estén todos aplanados en el listado. | producción (config, **incompleto** — ampliar en la Tarea C) |
| `.gitattributes` | 128 B | 2026-06-17 12:11 | Marca `pixi.lock` como generado/binario para el diff. | producción (config) |

**Hallazgo de reproducibilidad (nuevo, no estaba en el traspaso):** el entorno
`pixi` de **esta máquina** (Linux) no tiene `pyarrow` ni `fastparquet`
instalados — `pd.read_parquet()` falla aquí con
`ImportError: Unable to find a usable engine`. Tampoco declara `hmmlearn`,
`ruptures` ni `pythonnet` (mencionados como stack en la sección 3 del
traspaso). Sí aparece `statsmodels` instalado pero **no está en `pixi.toml`**
— fue agregado al entorno por fuera del lockfile. Todo esto es consistente con
que el traspaso describe un entorno **Windows**; esta réplica Linux/WSL no es
funcionalmente equivalente hoy. Para que la Tarea C deje "el proyecto
corriendo de punta a punta" en esta máquina hace falta agregar `pyarrow`,
`hmmlearn`, `ruptures`, y `statsmodels` a `pixi.toml` (o documentar que
`pythonnet`/PI SDK solo corren en Windows y separar esa etapa).

---

## 11. `notebooks_historicos/` — rescatados de `.ipynb_checkpoints/` (ver N-7)

**Actualizado 2026-09-06.** Estos cinco archivos vivían solo como checkpoint
de Jupyter, sin original vivo. Se leyó su contenido completo (no solo el
nombre) y resultaron ser evidencia real de trabajo previo, no basura. Se
rescataron a `notebooks_historicos/` con nombres descriptivos:

| Ruta actual | Tamaño | Modificado | Contenido verificado |
|---|---:|---|---|
| `notebooks_historicos/01_eda_lineas_A_B.ipynb` (ex `01_eda-checkpoint.ipynb`) | 532.406 B | 2026-06-17 12:09 | EDA de Espesador 1; prueba cuantitativa de exclusión mutua entre bombas (x1,x3) y (x2,x4) — probable origen del Principio #6 (trenes acoplados). Contiene `limpiar_dataset_industrial_v3` (Hampel + splines). |
| `notebooks_historicos/02_scaler_clustering_gmm.ipynb` (ex `02_scaler-checkpoint.ipynb`) | 140.575 B | 2026-06-17 12:09 | `StandardScaler` + `GaussianMixture`/BIC sobre `df_a_limpio.csv`. Enfoque de clustering de regímenes no documentado en ningún otro script. |
| `notebooks_historicos/curva_codo_bic_linea_b.png` (ex `curva_codo_bic_linea_b-checkpoint.png`) | 181.122 B | 2026-06-17 14:23 | Gráfico de salida de la evaluación BIC de `02_scaler`. |
| `notebooks_historicos/df_a_limpio.csv` (ex `df_a_limpio-checkpoint.csv`) | 143.228.897 B | 2026-06-24 06:10 | 524.612 filas, línea A (sin x2/x4), desde 2025-01-01. Salida de `01_eda`, entrada de `02_scaler`. |
| `notebooks_historicos/df_b_limpio.csv` (ex `df_b_limpio-checkpoint.csv`) | 64.216.282 B | 2026-06-24 06:13 | 235.050 filas, línea B (sin x1/x3, con y5 en vez de y4), desde 2025-01-02. |

Clasificación: **exploración (valor histórico confirmado)**, ~207 MB. Pendiente
de Task B/C: decidir destino final dentro de `notebooks/91_historico/` (o
`notebooks/regimenes_mineral/` para los dos notebooks, dado que su contenido
es análogo a esa línea de trabajo) y **preguntar al usuario quién es "fito"**
— `01_eda` escribe a una ruta absoluta `/home/fito/Proyects/data4Espesadores/...`
que no corresponde a este entorno ni aparece descrita en el traspaso.

---

## 12. Clasificación "basura de Jupyter/compilados" — acción ya ejecutada (2026-09-06)

Por pedido explícito del usuario se analizó el contenido de los notebooks
huérfanos y se actuó de inmediato sobre lo inequívoco, sin esperar a la Tarea C:

**Rescatado primero** (ver N-7, sección 11): los 5 archivos de
`.ipynb_checkpoints/` se movieron a `notebooks_historicos/` porque, al leerlos,
resultaron tener contenido único y valioso (no eran basura).

**Borrado después**, ya con la carpeta de checkpoints vacía de contenido
valioso, y verificado cada uno por diff de celdas o hash antes de borrar:

- `pipeline.ipynb`, `pipeline-checkpoint.ipynb` — vacíos, sin ninguna celda con código.
- `Untitled-checkpoint.ipynb` — diff de celdas confirmó 0 código (plantilla vacía); el contenido real está en `Untitled.ipynb` (vivo, no se tocó).
- `getData-checkpoint.ipynb` — hash idéntico a `getData.ipynb` (vivo, no se tocó).
- `test_cluster-checkpoint.ipynb` — diff de celdas confirmó que ninguna celda difiere en código del vivo (la diferencia de tamaño era metadata/output); el contenido real, incluida la celda única de N-4, está en `test_cluster.ipynb` (vivo, no se tocó).
- La carpeta `.ipynb_checkpoints/` (ya vacía tras el rescate) se eliminó.

**Deliberadamente NO borrado**, pendiente de que el usuario decida su destino
final en la Tarea C (archivar vs. descartar, según lo dejado abierto en
`docs/plan_migracion.md`): `Untitled.ipynb`, `getData.ipynb`, `TEST1.ipynb`,
`test_cluster.ipynb` — los cuatro notebooks "huérfanos" que sí tienen código
propio y no duplicado en ningún otro archivo.

**Pendiente para la Tarea C** (sin acción hoy, requiere revisión de contenido
uno por uno, no son mecánicos):
- Los **19** archivos `*-checkpoint.*` restantes en la raíz que dieron
  `IDENTICO` en la comparación md5 (listados en las secciones 2, 4, 5, 6, 7, 9
  arriba) — mismo criterio que los ya borrados, pendientes solo por prolijidad
  de hacerlo junto con el resto de la migración.
- `config_espesadores.cpython-311.pyc`, `onepager_espesadores.cpython-311.pyc`.

**Acción pendiente:** agregar `**/*-checkpoint.*`, `.ipynb_checkpoints/`,
`__pycache__/` y `*.pyc` a `.gitignore` (ya recogido en `docs/plan_migracion.md`
§8) para que esto no vuelva a acumularse.

---

## 13. Grafo de dependencias

```
PI Data Archive (AF SDK, Windows)
  └─ getDataAllTH.py ──────────────────────────► datos_espesadores_20260906_1317.parquet  [CANÓNICO]
       │                                          manifiesto_extraccion_20260906_1317.csv
       │ (corrida anterior, 63 tags)
       └────────────────────────────────────────► datos_espesadores_20260905_1912.parquet [superseded]
                                                    bloque_0001..0053*.parquet [obsoletos, ver N-3]
                                                    _esquema.json [ya actualizado al esquema nuevo]

  └─ getData.ipynb (namespace AF.Data, obsoleto) ► Data_Esp1_20260902_1056.csv
                                                     └─► datos_th1c2_020926.parquet [contaminado]

  └─ getAtributes.py ──────────────────────────► Atributos_PI_*.csv  [resuelve N-2]
  └─ searchTAg.py ─────────────────────────────► Busqueda_*.csv

verificaciondata.py ◄── datos_espesadores_20260906_1317.parquet
  └──► diagnostico_calidad_rebose.csv, diagnostico_cobertura_mensual.csv,
       diagnostico_congelamiento.csv                              [vigentes]

rol_guardias.py ◄── Rol_Operaciones_2024/2025/2026.md
  └──► calendario_guardias.parquet                                [vigente]

nivel_piscinas.py ◄── datos_espesadores_20260906_1317.parquet (LIT_106, LIT_107)
  └──► nivel_piscinas_derivado.parquet                            [vigente]

config_espesadores.py ◄── (nada; es la raíz de configuración)
  └── RUTAS["entrada"] = "datos.parquet"   ⚠ ver N-1, apunta al dataset contaminado

pipeline_espesadores.py ◄── config_espesadores.py
       ◄── datos.parquet (según config actual; DEBERÍA ser el canónico)
       ◄── Rol_Operaciones_*.md (opcional, vía RUTAS)
  └──► E01..E11_*.csv, REPORTE_COMPLETO.txt              [obsoletos, ver N-1/N-5]
       (usa la carpeta "salidas/" que HOY NO EXISTE — estas 19 salidas están
        sueltas en la raíz, de una versión anterior que escribía ahí directo)

onepager_espesadores.py ◄── contexto de pipeline_espesadores.py
  └──► onepager_TH001.html                                [obsoleto, ver N-5]

io_espesador.py ◄── (utilidad de carga, formato x1..y8)
  ├── demanda_agua.py           (entradas rotas: dataset_regimenes_v2.csv,
  │                               Data_Esp1_20260714_0921.csv no existen)
  ├── diagnostico_deriva.py ───► segmentos.json
  │        (consumidor declarado "analisis_espesador_v3.py" NO EXISTE)
  └── regimenes_mineral.py ───► dataset_con_regimen.csv (no existe hoy)
             │                        │
             │                        └─◄── test_escala_temporal.py (entrada rota)
             └─ (v1, superseded por regimenes_v2.py)

regimenes_v2.py ───► dataset_regimenes_v2.csv (no existe hoy)
  ◄── invocado por TEST3_2YEARS.ipynb
       └─◄── demanda_agua.py (entrada rota)

test_mineral_vs_operador.py ◄── datos.parquet  ⚠ mismo problema que N-1
  └── duplicado embebido en test_cluster.ipynb (celda 1)
       test_cluster.ipynb celda 2 = v2 sin script propio (ver N-4)

TEST1.ipynb ◄── dataset_operacion.csv (no existe)   [huérfano]
TEST2_2YEARS.ipynb ──► diagnostico_deriva.main(Data_Esp1_20260714_0921.csv)
Untitled.ipynb — prueba aislada de namespace AF.PI/AF.Data, sin dependencias
pipeline.ipynb — vacío, sin dependencias
```

---

## 14. Archivos huérfanos (nadie los invoca ni los importa, y/o su entrada ya no existe)

- `pipeline.ipynb`, `pipeline-checkpoint.ipynb` — vacíos.
- `segmentos.json` — su consumidor declarado (`analisis_espesador_v3.py`) no existe en el proyecto.
- `TEST1.ipynb` — su entrada (`dataset_operacion.csv`) no existe.
- `demanda_agua.py`, `test_escala_temporal.py` — sus entradas por defecto (`dataset_regimenes_v2.csv`, `dataset_con_regimen.csv`, `Data_Esp1_20260714_0921.csv`) no existen hoy en disco; no se pueden ejecutar tal cual.
- `Untitled.ipynb` — no lo importa ni lo lee ningún otro script, pero es probable evidencia de una decisión (namespace PI); no tratar como huérfano descartable.
- Los 5 archivos de `.ipynb_checkpoints/` sin original vivo (sección 11) — huérfanos por definición, de origen desconocido.
- `getAtributes.py` / `searchTAg.py` — no los importa nada, pero son utilidades CLI de uso intencional, no huérfanos de verdad.

---

## 15. Preguntas para el usuario (Tarea A las deja abiertas, no las resuelve)

1. ~~Línea de trabajo del área 2101 (QH)~~ — **Resuelto (2026-09-06):** el
   usuario confirmó que es otro proyecto sin relación con este. Los dos
   archivos (`Busqueda_X2101XPPX...`) se eliminaron.
2. **`Untitled.ipynb`** parece ser el registro de la decisión de namespace
   `AF.PI` vs `AF.Data`. ¿Se confirma antes de decidir su destino?
3. **`test_cluster.ipynb` celda 2** contiene una v2 del test mineral-vs-operador
   sin script propio. ¿Se extrae a un `.py` antes de archivar el notebook?
4. **Los 5 archivos huérfanos de `.ipynb_checkpoints/`** (`01_eda`,
   `02_scaler`, `curva_codo_bic_linea_b`, `df_a_limpio`, `df_b_limpio`) no
   tienen original vivo. ¿Se recuerda qué contenían, o se pueden descartar?
5. **`RUTAS["entrada"]` en `config_espesadores.py`** — confirmar que se
   actualiza a `datos_espesadores_20260906_1317.parquet` antes de recomputar
   nada (N-1), y decidir si TH-002/TH-003 corren igual antes o después de que
   Instrumentación confirme los tags `# <<< COMPLETAR`.

---

## 16. Resumen numérico

- **167** archivos en la raíz plana + **5** rescatados de `.ipynb_checkpoints/` = **172** analizados.
- **5** archivos rescatados de `.ipynb_checkpoints/` a `notebooks_historicos/` por tener contenido único y valioso (N-7) — ya NO se van a borrar.
- **5** archivos borrados el 2026-09-06 tras verificar que no tenían ningún contenido único (`pipeline.ipynb`, `pipeline-checkpoint.ipynb`, `Untitled-checkpoint.ipynb`, `getData-checkpoint.ipynb`, `test_cluster-checkpoint.ipynb`) + la carpeta `.ipynb_checkpoints/` (ya vacía).
- **4** notebooks huérfanos con código propio dejados intactos, pendientes de decisión de archivado en la Tarea C (`Untitled.ipynb`, `getData.ipynb`, `TEST1.ipynb`, `test_cluster.ipynb`).
- **19** pares `archivo`/`archivo-checkpoint` byte-idénticos restantes (basura de Jupyter, pendiente de borrar en la Tarea C).
- **2** archivos `.pyc` (borrar, agregar a `.gitignore`).
- **7** candidatos a "dataset vigente" reducidos a **1** canónico verificado.
- **53 + 1** chunks de extracción obsoletos (~215 MB), todos del esquema de 63 tags.
- **19** salidas E01–E11 + reporte + one-pager, todas generadas contra el dataset contaminado (regenerar en la Tarea C, después de resolver N-1).
- **5** tags de la sección 5.2 del traspaso, resueltos por esta auditoría sin gestión externa (N-2).
- **2** hallazgos críticos nuevos que requieren decisión del usuario: N-1 (bloquea cualquier recomputación) y N-7 (¿quién es "fito"? — trabajo de otra persona/entorno no descrito en el traspaso).
