# Bitácora de hallazgos — Espesadores C2 (TH-001/002/003)

Tarea D de `PROMPT_CLAUDE_CODE.md`. No existía `bitacora_hallazgos.md` en
ningún lugar del proyecto (confirmado en la Tarea A); se crea aquí a partir
de la sección 4 del traspaso y de la auditoría de migración de las Tareas
A-C (`docs/inventario_proyecto.md`, `docs/plan_migracion.md`).

Convención: cada hallazgo lleva **evidencia**, **nivel de confianza** y
**estado** (si ya se corrigió/verificó en la migración de 2026-09-06 o si
sigue abierto). Los hallazgos H-A a H-H vienen de la sesión que originó el
traspaso; los N-1 a N-7 son de la auditoría de migración de esta sesión.
Todos están re-verificados contra `data/00_raw/espesadores_20260906_1317.parquet`
(el dataset canónico) salvo donde se indica lo contrario.

---

## Resumen

| ID | Hallazgo | Confianza | Estado |
|---|---|---|---|
| H-A | Clave duplicada en `tags_config`: PB01 desaparecía, PB02 apuntaba al Molino 1 | CONFIRMADO | **Corregido** — tags como lista, `validar_tags()`, test de regresión |
| H-B | El "congelamiento" del rebose era artefacto de `ffill().bfill()` | CONFIRMADO | **Corregido** — sin ffill/bfill en el pipeline, test de regresión |
| H-C | Los tags de rebose no se historizaron antes de dic-2025 (~258 días útiles, no 780) | **CONFIRMADO** (verificado en esta sesión, ver abajo) | Abierto — recomputar cualquier cifra que haya usado rebose crudo en el tramo sin dato |
| H-D | El ciclo del rol es de 14 días (336 h), no semanal | CONFIRMADO | Verificado de nuevo — `dominio/guardias.py` mide 336h |
| H-E | `Sol_Overflow_Output` está muerto en PI (`Pt Created` 100%) | CONFIRMADO | Sin acción posible sin cambio en el DCS; el pipeline ya usa el valor por defecto |
| H-F | Dos escalones de cobertura instrumental (dic-2025, abr-2026, ago-2026) | CONFIRMADO | Verificado de nuevo contra el dataset canónico |
| H-G | `frac_congelado` del manifiesto es fiable (sobreestimación máx. 0.0003) | CONFIRMADO | Verificado de nuevo — sobreestimación máx. 0.0003 |
| H-H | Congelamiento alto en bombas es física, no dato; BedMass difiere 67.8/78.1/88.2% entre TH-001/002/003 | CONFIRMADO | Verificado de nuevo, cifras exactas |
| N-1 | El pipeline apuntaba a un dataset contaminado (`datos.parquet`, huella de H-B) | CONFIRMADO | **Corregido** en la migración — `conf/base/pipeline.yaml` |
| N-2 | Los 5 tags no identificados de §5.2 ya estaban resueltos en `pi_metadata/` | CONFIRMADO | Incorporado a `conf/base/tags.yaml` |
| N-3 | Los 54 `bloque_*.parquet` en disco son del esquema viejo (63 tags) | CONFIRMADO | Movidos a `data/99_deprecated/`; borrado real pendiente de decisión |
| N-4 | `test_cluster.ipynb` tenía una v2 sin script propio | CONFIRMADO | Extraída antes de borrar el notebook |
| N-5 | Todas las salidas E01-E11 viejas comparten el origen contaminado de N-1 | CONFIRMADO | Regeneradas contra el dataset canónico |
| N-6 | `E05_balance_agua` no usa el tag crudo de rebose — ya implementa la ruta de H-C | CONFIRMADO | Sin acción; corrige una suposición del propio traspaso |
| N-7 | Notebooks rescatados de checkpoints eran el origen probable de "trenes acoplados" | CONFIRMADO | Rescatados a `notebooks/regimenes_mineral/`; "fito" confirmado como otro proyecto sin relación |

---

## H-A. Bug de clave duplicada en `tags_config` — CONFIRMADO, CORREGIDO

**Evidencia:** el diccionario original tenía `'_293200_Alim_Total_PB01_ABB'`
repetido en dos líneas, mapeado a `Alim_Total_PB01` y a `Alim_Total_PB02`.
Python conserva la última asignación: PB01 desaparecía del diccionario y
PB02 apuntaba al tag del Molino 1. 63 entradas escritas, 62 claves únicas.
Silencioso, sin error.

**Acción:** cualquier resultado previo que compare Molino 1 contra Molino 2
está comprometido y debe recomputarse.

**Corrección aplicada:** los tags se declaran como lista de tuplas
`(tag_pi, columna, grupo, descripcion)` en `conf/base/tags.yaml::extraccion_pi`
(no ya como diccionario embebido en `getDataAllTH.py`). El tag real de PB02
es `_293200_Alim_Total_PB02_ABB`, confirmado por el usuario. Total: 68 tags.

**Guarda permanente:** `tests/test_config_tags.py` falla si se reintroduce
un `tag_pi` o una `columna` duplicados en `tags.yaml`, y verifica
explícitamente que PB01 y PB02 sean tags distintos.

---

## H-B. El "congelamiento" del rebose era un artefacto de `ffill` — CONFIRMADO, CORREGIDO

**Evidencia:** el script antiguo aplicaba `df.ffill().bfill()`. Con NaN
preservados, los tags de rebose no aparecen entre los congelados: aparecen
entre los de alto NaN (66.6%-68.0%). Cuando tienen dato, `frac_cong_adyacente`
es 0.006 — prácticamente nunca se congelan. La parte A del diagnóstico
descartó la explicación alternativa de una constante de respaldo del PLC: en
la ventana probada los cuatro tags de rebose dan 100% de valores buenos, 0%
de estados digitales, 0% de valores no buenos.

**Conclusión:** la serie plana de los reportes anteriores la fabricó el
`bfill`, propagando hacia atrás el primer valor válido.

**Corrección aplicada:** `getDataAllTH.py`/`extraer_pi.py` no aplica
`ffill`/`bfill` en ningún punto. Verificado además durante esta migración
que `datos.parquet`, `datos_th1c2_020926.parquet` y toda la familia
`Data_Esp1_*` **sí** cargan ese artefacto (huella: un solo valor ocupa
66.8%-70.5% de las filas válidas de `FLUJO_REBOSE_AGUA_TH1` con 0% de NaN) —
ver N-1.

**Guarda permanente:** `tests/test_sin_ffill_bfill.py` tokeniza el código de
`src/espesadores/` y falla si aparece `.ffill(`/`.bfill(`/`fillna(method=...)`
fuera de un allowlist explícito y justificado (la única excepción hoy es
propagar una etiqueta de cluster categórica en E08, no un dato de sensor).

---

## H-C. Los tags de rebose no se historizaron antes de diciembre 2025 — CONFIRMADO (verificación ejecutada en esta sesión)

**Evidencia original:** `FLUJO_REBOSE_AGUA_TH1` tiene 122 episodios de
hueco; uno dura 750.743 minutos = 521,3 días, que sobre 780 días es 66,8%,
coincidente con el NaN observado. La cobertura mensual salta de ~47% a
~100% en 2026-01. Jaccard entre máscaras de NaN de TH1/TH2/TH3/G: 0,98 a
0,9997 — causa común.

**Verificación ejecutada** (el snippet que el traspaso dejaba pendiente,
corrido contra `data/00_raw/espesadores_20260906_1317.parquet`):

| Tag | Primer dato | Último dato | Cobertura | Días útiles |
|---|---|---|---:|---:|
| `FLUJO_REBOSE_AGUA_TH1` | 2025-12-17 08:23 | 2026-09-01 23:59 | 33,13% | 258 |
| `FLUJO_REBOSE_AGUA_TH2` | 2025-12-17 08:23 | 2026-09-01 23:59 | 33,14% | 258 |
| `FLUJO_REBOSE_AGUA_TH3` | 2025-12-17 08:23 | 2026-09-01 23:59 | 32,07% | 258 |
| `FLUJO_REBOSE_AGUA_G` | 2025-12-19 13:07 | 2026-09-01 23:59 | 31,79% | 256 |

Sobre 779 días totales del dataset, **258 días son la ventana útil real**
para cualquier análisis basado en el tag de rebose — confirma casi
exactamente la estimación de "~260 días" del traspaso. **Sube de INFERIDO a
CONFIRMADO.**

**Implicación crítica (sigue abierta):** todo resultado numérico que haya
usado valores de rebose anteriores a diciembre 2025 se ajustó contra una
constante fabricada por `ffill` (H-B). Esto incluye cualquier estimación de
ganancia en m³/h calculada antes de esta migración con la familia
`Data_Esp1_*`/`datos.parquet`/`datos_th1c2_020926.parquet` — **ninguna de
esas cifras es válida** (Principio #10: ninguna cifra de análisis previos se
arrastra).

**Ruta alternativa, ya validada (ver N-6):** `WT_146`/`WT_144` (%sólidos de
descarga) tienen cobertura casi completa desde 2024-07. `E05_balance_agua`
ya ancla el cálculo de rebose en esa ruta, no en el tag crudo — así que el
pipeline de producción **no está expuesto** a esta ventana corta, aunque el
análisis exploratorio (`notebooks/regimenes_mineral/demanda_agua.py`, que
sí necesita `y7/y8` de la familia `Data_Esp1_*`) sigue sin dataset de
entrada vigente.

**Pendiente:** reconstruir el rebose del tramo sin dato vía balance de
piscina (oportunidad §5.4 del traspaso) requiere la curva nivel-volumen de
la piscina (§5.3), que no existe todavía.

---

## H-D. El ciclo del rol es de 14 días, no semanal — CONFIRMADO

**Evidencia (re-verificada con `pixi run guardias` en esta sesión):**
1096 días sin huecos en los tres `Rol_Operaciones_202X.md`. 7 guardias,
ciclo base `AAAADDDBBBBDDD`. Dotación diaria exacta: `{(2, 2, 3): 1096}` —
2 en A, 2 en B, 3 en descanso, sin una sola excepción. 14 firmas diarias
distintas, período de repetición exacto de 14 días. 7 pares distintos en
turno A y en turno B. Turnos: A 07:30→19:30, B 19:30→07:30 (confirmado
directamente por el usuario el 2026-09-06).

**Corrección a una conclusión previa:** el análisis anterior descartó la
guardia como driver de régimen probando autocorrelación a 12h, 96h y 168h.
El ciclo real son 336h y ese lag nunca se probó — la hipótesis no quedó
falsificada, se buscó en el período equivocado.
`src/espesadores/dominio/guardias.py` mide 168h, 336h y 672h. Corrida contra
el dataset canónico: `WT_146` da autocorrelación 0,714 a 168h y **0,430 a
336h** (frente a -0,049 a 672h) — hay señal real en el ciclo de rol, más
allá de lo que ya se explicaba por autocorrelación de corto plazo. `LIT_106`
(piscina) sostiene 0,761 incluso a 336h.

**Advertencia de identificación que debe quedar en la tesis:** la dotación
es función determinista de la fecha, así que un efecto de guardia es
indistinguible de cualquier rutina quincenal (mantenimiento, calibración de
laboratorio, rotación de supervisión). Un resultado positivo es una
hipótesis a contrastar contra el programa de mantenimiento, no una
conclusión sobre las personas.

---

## H-E. `Sol_Overflow_Output` está muerto — CONFIRMADO

**Evidencia:** el punto `C2_Sol_Overflow_Output` devuelve el estado digital
`Pt Created` en el 100% de las muestras (`diagnostico_calidad_rebose.csv`:
`pct_estado_digital=100.0`, `estados_digitales={'Pt Created': 10081}`).
Nunca recibió un valor en 780 días. No es recuperable por extracción;
requiere configurar la escritura desde el DCS.

**Estado:** sin acción posible desde el pipeline. `E05_balance_agua` ya
maneja este caso: si el tag está descartado (por E02) o 100% nulo, usa el
valor por defecto del DCS (36%) — ver `conf/base/reglas_operativas.yaml::proceso.sol_alim_default`.

---

## H-F. Dos escalones de cobertura instrumental — CONFIRMADO

**Evidencia (re-verificada con `pixi run diagnostico --parte B` en esta
sesión, contra el dataset canónico):**

Cobertura global mensual: 87,2%-88,2% hasta 2025-11, **90,5% en 2025-12**,
93,9%-94,1% en 2026-01/03, 94,8%-95,6% en 2026-04/07, **98,4%-98,5% desde
2026-08**.

Tags que entran en línea: `YY_4100TH001`/`YY_4100TH003` (4%→100% en
2026-08), `Ratio_concentracion_Output` (0%→80% en 2026-04), `FV_1002`
(33%→100% en 2025-03), los cuatro de rebose (~47%→100%/96% en 2026-01).

Tags que se degradan (patrón inverso, menos esperado): `PP_007A_Speed`
100%→69% en 2024-09, `PP_009A_Speed` 100%→71% en 2025-05, `FV_1001`
100%→80% en 2024-11.

**Acción:** cualquier comparación entre trenes, espesadores o períodos debe
controlar por régimen de instrumentación. Sigue sin resolverse (no era el
objetivo de esta migración): es una condición a aplicar en cada análisis
nuevo, no un bug a corregir una sola vez.

---

## H-G. `frac_congelado` del manifiesto es fiable — CONFIRMADO

**Evidencia (re-verificada en esta sesión):** la sobreestimación esperada
por calcularse tras `dropna()` fue descartada por la parte B2 del
diagnóstico. Sobreestimación máxima sobre las columnas del dataset
canónico: **0,0003** (columna `PP_005A_U_Speed`, `frac_cong_manifiesto`
0,4930 vs `frac_cong_adyacente` 0,4929). La métrica sirve tal como está.

**Registrado como descartado** para que nadie reintroduzca esta advertencia:
no hace falta recalcular `frac_congelado` sobre la grilla completa en
producción, la versión del manifiesto ya es correcta dentro de ±0,03pp.

---

## H-H. Congelamiento alto que NO es problema de dato — CONFIRMADO

**Evidencia:** velocidades de bomba con 93-99% de congelamiento y válvulas
con ~95% son duty/standby con períodos largos en reposo y válvulas en
posición fija — física, no calidad de dato.

**BedMass, re-verificado en esta sesión contra el dataset canónico**
(`data/06_reporting/diagnosticos/diagnostico_congelamiento.csv`):

| Columna | `frac_congelado` |
|---|---:|
| `TH001_PLC_BEDM` | 67,76% |
| `TH002_PLC_BEDM` | 78,14% |
| `TH003_PLC_BEDM` | 88,24% |

Coincide casi exactamente con lo documentado (67,8% / 78,1% / 88,2%). **Si
la resolución efectiva de la cama de sólidos difiere tanto entre unidades,
las ventanas operativas basadas en BedMass no se comparan en igualdad de
condiciones entre espesadores.** Sigue pendiente cuantificar el efecto antes
de comparar TH-001 contra TH-002/TH-003 — y esos dos todavía tienen 26 tags
`completar: true` sin confirmar con Instrumentación (`conf/base/tags.yaml`),
así que la comparación no es viable todavía de todos modos.

---

## N-1. El pipeline de producción apuntaba al dataset contaminado — CONFIRMADO, CORREGIDO

**Evidencia:** `config_espesadores.py::RUTAS["entrada"]` apuntaba a
`datos.parquet` (31 columnas, sin `Alim_Total_PB02`, sin TH-002/TH-003).
Huella de `ffill` confirmada: `FLUJO_REBOSE_AGUA_TH1` da 0% NaN con un solo
valor ocupando el 70,55% de las filas válidas (`pyarrow.compute.value_counts`).
La cabecera de `REPORTE_COMPLETO.txt` de la corrida anterior confirma
literalmente `Archivo: datos.parquet · 1.064.161 filas x 31 columnas`.
`datos_th1c2_020926.parquet` tiene la misma huella (66,84%).

**Corrección aplicada:** `conf/base/pipeline.yaml::rutas.entrada` apunta a
`data/00_raw/espesadores_20260906_1317.parquet` (el canónico). Verificado
corriendo `pixi run pipeline TH-001` de punta a punta: produjo cifras
distintas y ya no contaminadas (sensibilidad 11,0 m³/h/punto, AUC mineral
0,948, Tren 2 gana 34 de 35 celdas — ver `README.md`).

**Archivos contaminados**, conservados como evidencia en
`data/99_deprecated/` con este hallazgo como motivo: `datos.parquet`,
`datos_th1c2_020926.parquet`, `Data_Esp1_20260714_0921.*`,
`Data_Esp1_2026{06,07,09}*.csv`, y las 19 salidas E01-E11 +
`REPORTE_COMPLETO.txt` + `onepager_TH001.html` de la corrida vieja
(`data/99_deprecated/salidas_20260727_datos_parquet/`).

---

## N-2. Los cinco tags no identificados de §5.2 ya estaban resueltos — CONFIRMADO

**Evidencia:** `data/00_raw/pi_metadata/atributos_pi_293200_294100_20260904.csv`
(generado por `getAtributes.py` antes de esta sesión) trae el descriptor PI
completo:

| Tag | Descriptor PI | Unidad |
|---|---|---|
| `FIT_114` | Flujo hacia Piscinas | m³/h |
| `LIT_106` | Nivel agua recup. 296300XC001 — Piscina 1 | % |
| `LIT_107` | Nivel agua recup. 296300XC002 — Piscina 2 | % |
| `LIT_108` | Nivel 294300TK001 — Recuperación de Agua Espesadores Relaves | % |
| `LIT_109` | Nivel 294300TK002 — Recuperación de Agua Espesadores Relaves | % |

Confirma exactamente la hipótesis del traspaso: LIT_106/107 son los dos
transmisores de piscina (§5.1), LIT_108/109 son los tanques temporales
TK001/TK002 (§5.2), distintos de las piscinas. No hizo falta gestión con
Instrumentación.

**Incorporado a `conf/base/tags.yaml`:** LIT_106/107 como
`piscinas.transmisor_a/b` (usado por `dominio/piscinas.py`, antes
hardcodeado como `COL_A`/`COL_B`); los 5 en bloque `no_asignados` con su
descriptor, sin rol de espesador hasta decisión explícita (requisito de la
sección 6 del traspaso).

`FIT_123` y `FIT_601` siguen identificados por separado (agua fresca del
tanque principal y agua recuperada de QH respectivamente) — **ninguno es
rebose de espesadores**; si entran a un balance hídrico deben sumar aparte.

---

## N-3. Los 54 `bloque_*.parquet` son del esquema de 63 tags — CONFIRMADO

**Evidencia:** los 53 bloques `_20240714_20240729` a `_20260902_20260905` +
el huérfano `bloque_0001_20240714.parquet` tienen los 53 con 64 columnas
(63 tags + timestamp) — **no 69** como el `_esquema.json` vigente. La suma
de filas de la cadena válida (21.600×52 + 4.320 = 1.127.520) coincide EXACTO
con `datos_espesadores_20260905_1912.parquet` (64 columnas): son la corrida
anterior a la corrección de PB02, no solo el `bloque_0001` como sospechaba
el traspaso.

**Verificación de que NO contaminaron el dataset canónico:** la cobertura
mensual de `Alim_Total_PB02` en el dataset canónico es ~100% en TODO el
rango 2024-07/2026-09, incluido el período cubierto por los chunks viejos.
Si la corrida canónica hubiera reusado esos chunks por resume, esa columna
habría quedado NaN en ese tramo — no fue así, fue una extracción fresca
completa.

**Riesgo latente (no materializado):** `guarda_esquema()` en
`extraer_pi.py` valida la LISTA de columnas contra `_esquema.json`, pero no
valida el esquema de cada `bloque_*.parquet` individual. Si alguien borra
solo `_esquema.json` (no los chunks) y reanuda, el guard no detectaría el
desfase.

**Acción tomada:** los 54 bloques se movieron a
`data/99_deprecated/bloques_63tags_obsoletos/` (~215 MB). **Borrado real
pendiente de decisión del usuario** — moverlos ya elimina el riesgo de
reuso accidental por resume.

---

## N-4. `test_cluster.ipynb` tenía una v2 sin script propio — CONFIRMADO

**Evidencia:** la celda 1 era byte-idéntica a `test_mineral_vs_operador.py`
(9.630 caracteres). La celda 2 contenía una segunda versión completa
("DETECCION DE TIPO DE MINERAL + TEST DE INFLUENCIA... v2") que no existía
como archivo `.py` en ningún otro lugar del proyecto.

**Acción tomada:** la celda 2 se extrajo a
`notebooks/regimenes_mineral/v2_test_mineral_vs_operador.py` antes de
eliminar el notebook (indicación explícita del usuario del 2026-09-06 de
borrar todos los notebooks huérfanos restantes).

---

## N-5. Las salidas E01-E11 viejas comparten el origen contaminado de N-1 — CONFIRMADO, RESUELTO

**Evidencia:** la cabecera de `REPORTE_COMPLETO.txt` de la corrida del
2026-07-27 declara textualmente `Archivo: datos.parquet`. Esto extiende la
nota del traspaso (que solo decía "generadas con un dataset previo a 68
columnas") a algo más preciso: además de estar desactualizadas, **arrastran
el artefacto de `ffill`** en cualquier cifra que dependa de
`FLUJO_REBOSE_AGUA_TH1`/`_G`.

**Acción tomada:** archivadas en
`data/99_deprecated/salidas_20260727_datos_parquet/` y **regeneradas**
contra el dataset canónico en `data/06_reporting/TH001/` (ver N-1). El resto
de la lógica de E01-E11 (trenes, estado estacionario, mineral) no dependía
de los tags de rebose y no necesitó cambios de código, solo re-ejecución.

---

## N-6. `E05_balance_agua` no está tan expuesto a H-C como se temía — CONFIRMADO

**Evidencia:** leído el código de `e05_balance.py`, la etapa **nunca usa
el tag `FLUJO_REBOSE_AGUA_*`**. Recalcula `rebose` desde
`agua_alim - agua_descarga`, usando `wt_activo` (WT_146/WT_144, cobertura
casi completa desde 2024-07, per H-F) y el tonelaje del molino. Es
exactamente la "ruta alternativa" que H-C recomienda como ancla — el
pipeline ya la implementa por diseño, por una razón distinta (el estimador
del DCS se congela 70,5% del tiempo, no por la ventana corta de historización).

**Corrección al propio traspaso:** la prioridad 1 de auditoría de §5.bis
("`E05_balance_agua.csv` es el más expuesto a H-C") se basaba en el nombre
del archivo, no en su contenido. Sigue expuesto a **N-1** (si la entrada es
la equivocada) pero no al problema específico de H-C.

---

## N-7. Notebooks rescatados de checkpoints — origen probable de "trenes acoplados" — CONFIRMADO

**Evidencia:** `01_eda-checkpoint.ipynb` y `02_scaler-checkpoint.ipynb`
(sin original vivo, solo checkpoint de Jupyter) contenían: (a) la prueba
cuantitativa de exclusión mutua entre bombas (x1,x3) vs (x2,x4) — con alta
probabilidad el análisis original detrás del Principio #6 del traspaso
("los trenes de bombeo están totalmente acoplados"); (b) un enfoque de
clustering (`StandardScaler` + `GaussianMixture`/BIC) para regímenes de
mineral no documentado en ningún otro script.

**Dato adicional:** el notebook escribía a una ruta absoluta
`/home/fito/Proyects/data4Espesadores/...` de otra persona/máquina. **El
usuario confirmó (2026-09-06) que es otro proyecto sin relación con este.**

**Acción tomada:** los 5 archivos (2 notebooks + 1 PNG + 2 CSV de datos
limpios) se rescataron de `.ipynb_checkpoints/` a
`notebooks/regimenes_mineral/` con nombres descriptivos, antes de que la
limpieza general de checkpoints los borrara por error junto con la basura
real de Jupyter.

---

## Principios no negociables (sección 7 del traspaso) — estado tras la migración

1. **Nunca `ffill()`/`bfill()` sobre datos del historiador** — con guarda de test (H-B).
2. **Los bugs silenciosos son el riesgo principal** — con guarda de test (H-A).
3. **El torque de rastra es respuesta del proceso, no consigna** — sin cambios, ya se respeta en `e07_validacion.py`/`config`.
4. **La variable de control en correlaciones parciales es la participación de tonelaje del propio espesador** — sin cambios, `e07_validacion.py::corr_parcial`.
5. **El estimador *within* es el correcto para datos de lazo cerrado** — sin cambios; no se re-verificó en esta migración (no había código de esa etapa específica en el árbol relevado).
6. **Los trenes de bombeo están totalmente acoplados** — re-verificado: `pixi run pipeline TH-001` da 100,0%/99,9% de acoplamiento descarga/cizalle en E04 (ver N-7 sobre su origen probable).
7. **Refutación iterativa, correcciones documentadas en la bitácora** — esta misma bitácora.
8. **Prueba de humo antes de correr largo** — sin cambios; `conf/base/extraccion.yaml::modo_prueba` sigue disponible.
9. **Los documentos para personas van en español** — se mantiene en toda la documentación de la migración.
10. **Ninguna cifra de análisis previos se arrastra** — aplicado: `README.md` reemplazó las cifras de la corrida contaminada por las de la corrida canónica.
