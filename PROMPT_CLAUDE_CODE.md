# Encargo para Claude Code — Proyecto Espesadores C2 (TH-001 / TH-002 / TH-003)

> Este documento es a la vez un **traspaso de estado** y un **encargo de trabajo**.
> Léelo completo antes de tocar nada. La sección 4 contiene hallazgos que
> invalidan conclusiones previas del proyecto: no los pases por alto.

---

## 1. Qué es este proyecto

Análisis de datos operacionales de los tres espesadores de pasta de relaves del
área 4100/4500 de Concentradora 2 (C2), Southern Peru. El objetivo es
identificar **ventanas de parámetros operativos que maximicen la recuperación
de agua por rebose** (overflow), y presentar los hallazgos a la gerencia de
operaciones. El trabajo alimenta simultáneamente una tesis de posgrado y un
reporte operacional.

Criterios de éxito, en este orden:

1. **Auditabilidad.** Todo número debe ser trazable hasta el dato crudo del
   historiador. Cada etapa deja un CSV/parquet intermedio inspeccionable.
2. **Interpretabilidad física.** Se prefiere un resultado explicable por el
   proceso antes que uno estadísticamente cómodo.
3. **Reproducibilidad y escalado.** El pipeline validado en TH-001 debe
   replicarse en TH-002 y TH-003 sin reescribirlo.
4. **Recomendaciones basadas en lo demostrado.** Se reporta lo que la planta ya
   logró, no óptimos teóricos.

Etapa siguiente prevista: modelado predictivo. De ahí la exigencia de que la
estructura soporte MLOps.

---

## 2. Encargo (lo que debes hacer)

### Tarea A — Inventario

Recorre **toda** la carpeta del proyecto (raíz `ESPESOS/` y subcarpetas) y
produce `docs/inventario_proyecto.md` con:

- Todo archivo `.py`, `.ipynb`, `.yaml/.yml`, `.md`, `.csv`, `.parquet`, `.pkl`,
  `.xlsx`, `.json`, imágenes de croquis, y cualquier documento de planta.
- Por cada uno: ruta, tamaño, fecha de modificación, y una línea de propósito
  inferida de su contenido (no del nombre).
- Clasificación en: `produccion` / `exploracion` / `duplicado` / `obsoleto` /
  `dato` / `documentacion` / `desconocido`.
- **Detección de duplicados y versiones**: archivos con contenido igual o casi
  igual, y familias tipo `script.py`, `script_v2.py`, `script_final.py`.
  Indica cuál es el vigente y por qué.
- **Grafo de dependencias**: qué script importa o lee la salida de cuál.
- **Archivos huérfanos**: los que nadie invoca ni importa.

No borres ni muevas nada todavía. El inventario es para revisión.

### Tarea B — Propuesta de estructura

Propón la migración a la estructura de la sección 6. Entrega
`docs/plan_migracion.md` con la tabla `origen -> destino` archivo por archivo,
y marca cuáles requieren cambios de código (rutas absolutas, imports, tags
hardcodeados). Espera aprobación antes de ejecutar.

### Tarea C — Migración

Tras aprobación: ejecuta la migración, adapta imports y rutas, crea los
`__init__.py`, mueve la configuración a YAML, y deja el proyecto corriendo de
punta a punta. Sin romper nada que hoy funcione.

### Tarea D — Consolidar la bitácora

Localiza `bitacora_hallazgos.md`. Incorpora los hallazgos de la sección 4 con
su evidencia y su nivel de confianza. Si no existe, créala en `docs/`.

---

## 3. Estado verificado a la fecha

Entorno: Windows, gestor `pixi`, directorios de trabajo
`ESPESOS/notebooks/` y `ESPESOS/th001/`.
Stack: pandas, numpy, scikit-learn, statsmodels, hmmlearn, ruptures, pythonnet
(AF SDK de PI). Formato principal parquet, con respaldo pickle por una
incompatibilidad conocida pandas 3.0 / pyarrow al escribir.

### Ya ejecutado y validado

| Artefacto | Estado |
|---|---|
| `extraccion_pi_espesadores.py` (alias `getDataAllTH.py`) | Corrido completo. 780 días, 1 min, 68 tags |
| `salida_pi/datos_espesadores_20260906_1317.parquet` | 1.123.200 filas × 68 columnas. Continuidad verificada: 0 faltantes, 0 duplicados, espaciado único de 1 min |
| `salida_pi/manifiesto_extraccion_20260906_1317.csv` | Auditoría por tag: unidades de ingeniería, descriptor PI, cobertura, %NaN, `frac_congelado`, rango |
| `diagnostico_extraccion.py` (alias `verificaciondata.py`) | Partes A y B corridas |
| `rol_guardias.py` | `calendario_guardias.parquet`, 1.578.240 filas |
| `nivel_piscinas.py` | **Corrido pero con resultado inválido.** Ver 5.1 |

### Configuración de la extracción

- Servidor `tpi.southernperu.com.pe`, zona `America/Lima` (UTC-5 fijo, sin DST).
- Rango 2024-07-14 a 2026-09-05, intervalo 1 min.
- Bulk vía `PIPointList.InterpolatedValues` con `PIPagingConfiguration`
  (**namespace `OSIsoft.AF.PI`**, no `OSIsoft.AF.Data`).
- Bloques de 15 días, semiabiertos `[t0, t1)`, con checkpoint en disco,
  reanudación y guarda de esquema.
- Duración: ~55 minutos.
- 68 tags: 7 planta, 17 por cada espesador, 7 aguas abajo, 3 de estado del
  sistema experto.

---

## 4. Hallazgos de esta sesión

Cada uno lleva su evidencia y su nivel de confianza. **Verifica los marcados
como inferidos antes de citarlos.**

### H-A. Bug de clave duplicada en `tags_config` — CONFIRMADO

El diccionario original tenía `'_293200_Alim_Total_PB01_ABB'` repetido en dos
líneas, mapeado a `Alim_Total_PB01` y a `Alim_Total_PB02`. Python conserva la
última asignación: **PB01 desaparecía del diccionario y PB02 apuntaba al tag
del Molino 1**. 63 entradas escritas, 62 claves únicas. Silencioso, sin error.

Corregido: los tags se declaran como lista de tuplas
`(tag_pi, columna, grupo, descripcion)` y `validar_tags()` aborta ante
duplicados de tag o de columna. El tag real de PB02 es
`_293200_Alim_Total_PB02_ABB`, confirmado por el usuario. Total actual: 68 tags.

**Acción:** cualquier resultado previo que compare Molino 1 contra Molino 2
está comprometido y debe recomputarse.

### H-B. El "congelamiento" del rebose era un artefacto de `ffill` — CONFIRMADO

El script antiguo aplicaba `df.ffill().bfill()`. Eliminado.

Con NaN preservados, los tags de rebose **no aparecen entre los congelados**:
aparecen entre los de alto NaN (66.6% a 68.0%). Cuando tienen dato,
`frac_cong_adyacente` es 0.006 — prácticamente nunca se congelan.

La parte A del diagnóstico descartó la explicación alternativa: en la ventana
probada los cuatro tags de rebose dan **100% de valores buenos**, 0% de estados
digitales y 0% de valores marcados como no buenos. No hay constante de respaldo
del PLC siendo descartada por el filtro `IsGood`.

**Conclusión: retirar la hipótesis de "constante de respaldo del PLC".** La
serie plana de los reportes anteriores la fabricó el `bfill`, propagando hacia
atrás el primer valor válido.

### H-C. Los tags de rebose no se historizaron antes de diciembre 2025 — INFERIDO, verificar

Evidencia convergente:

- `FLUJO_REBOSE_AGUA_TH1` tiene 122 episodios de hueco; 121 duran de 1 a 6
  minutos, y **uno dura 750.743 minutos = 521,3 días**. Sobre 780 días eso es
  66,8%, que coincide con el 66,87% de NaN observado.
- La cobertura mensual de los cuatro tags de rebose salta de ~47% a ~100% en
  **2026-01**.
- Jaccard entre las máscaras de NaN de TH1/TH2/TH3/G: 0,98 a 0,9997. Causa
  común, no tres fallas.

**Verificación pendiente** (una línea, el dato ya está en disco):

```python
import pandas as pd
df = pd.read_parquet(r'salida_pi/datos_espesadores_20260906_1317.parquet')
val = df.notna()
print(pd.DataFrame({'primer_dato': val.idxmax().mask(~val.any()),
                    'ultimo_dato': val[::-1].idxmax().mask(~val.any()),
                    'cobertura': val.mean().round(4)}).sort_values('primer_dato').to_string())
```

**Implicación crítica:** la ventana útil para análisis basado en el tag de
rebose es de ~260 días, no 780. Todo resultado numérico previo que haya usado
valores de rebose anteriores a diciembre 2025 se ajustó contra una constante
fabricada. **Determina qué tags alimentaron cada cifra publicada y recomputa
las afectadas.** Esto incluye la estimación de ganancia en m³/h que se venía
usando para la defensa.

Ruta alternativa: `WT_146` y `WT_144` (%Sólidos de descarga) tienen cobertura
prácticamente completa desde 2024-07. Como el estimador de rebose del PLC es
función biyectiva del %sólidos de la línea activa, ambos objetivos son
equivalentes — pero uno tiene tres veces más datos. **Recomendación: anclar el
pipeline en %Sólidos y usar el rebose solo como validación en el tramo donde
existe.**

### H-D. El ciclo del rol es de 14 días, no semanal — CONFIRMADO

Parseados los tres archivos `Rol_Operaciones_2024/2025/2026.md`:

- 1096 días, sin huecos. El día de semana declarado coincide con el calendario
  en las 7.672 celdas.
- 7 guardias, ciclo base `AAAADDDBBBBDDD`.
- **Exactamente 2 guardias en A, 2 en B y 3 en descanso todos los días**, sin
  una sola excepción.
- Solo 14 firmas diarias distintas, con período de repetición exacto de 14 días.
- 7 pares distintos en turno A, en anillo: G1+G3, G3+G5, G5+G7, G2+G7, G2+G4,
  G4+G6, G1+G6. Reparto balanceado: 112.320 a 113.760 minutos cada uno.
- Turnos: **A de 07:30 a 19:30, B de 19:30 a 07:30**. C2 = Concentradora 2,
  engloba el área 4100, por lo que el rol aplica a los espesadores.

**Corrección a una conclusión previa.** El análisis anterior descartó la guardia
como driver de régimen probando autocorrelación a 12 h, 96 h y 168 h. **El ciclo
real son 336 h y ese lag nunca se probó.** La hipótesis no quedó falsificada; se
buscó en el período equivocado. `rol_guardias.py` mide 336 h junto a 168 h y
672 h.

**Advertencia de identificación que debe quedar escrita en la tesis:** la
dotación es función determinista de la fecha, así que un efecto de guardia es
indistinguible de cualquier rutina quincenal (mantenimiento, calibración de
laboratorio, rotación de supervisión). Un resultado positivo es una hipótesis a
contrastar contra el programa de mantenimiento, no una conclusión sobre las
personas. Las campañas de mineral (persistencia de 4 días) no confunden, porque
no están sincronizadas con el ciclo de 14 días.

### H-E. `Sol_Overflow_Output` está muerto — CONFIRMADO

El punto `C2_Sol_Overflow_Output` existe en PI pero devuelve el estado digital
`Pt Created` en el 100% de las muestras: nunca recibió un valor en 780 días. No
es recuperable por extracción; requiere configurar la escritura desde el DCS.

**Acción:** si alguna etapa del pipeline lo consume, excluirlo explícitamente en
la configuración. No dejarlo caer como NaN silencioso.

### H-F. Dos escalones de cobertura instrumental — CONFIRMADO

Cobertura global mensual: ~88% hasta 2025-11, 90,5% en 2025-12, ~94% en
2026-01/03, ~95% en 2026-04/07, 98,4% desde 2026-08.

Tags que **entran** en línea: los cuatro de rebose (2026-01),
`Ratio_concentracion_Output` (0% → 80% en 2026-04), `FV_1002` (33% → 100% en
2025-03), `YY_4100TH001` y `YY_4100TH003` (4% → 100% en 2026-08).

Tags que **se degradan**, que es el patrón inverso y menos esperado:
`PP_007A_Speed` 100% → 69% en 2024-09, `PP_009A_Speed` 100% → 71% en 2025-05,
`FV_1001` 100% → 80% en 2024-11. Los dos primeros afectan al tren activo de
TH-001.

**Acción:** cualquier comparación entre trenes, entre espesadores o entre
períodos debe controlar por régimen de instrumentación. Agrupar datos de antes y
después de estos escalones mezcla regímenes distintos.

### H-G. `frac_congelado` del manifiesto es fiable — CONFIRMADO

Yo mismo advertí que estaría sesgado al alza por calcularse tras `dropna`. La
parte B2 lo desmintió: la sobreestimación máxima sobre las 68 columnas es
0,0003. La métrica sirve tal como está. **Registrar esta advertencia como
descartada** para que nadie la reintroduzca.

### H-H. Congelamiento alto que NO es problema de dato — CONFIRMADO

Velocidades de bomba con 93–99% de congelamiento y válvulas con ~95% son
duty/standby con períodos largos en reposo y válvulas en posición fija. Es
física, no calidad de dato. No investigar.

Sí merece atención el BedMass: 67,8% / 78,1% / 88,2% de congelamiento en
TH-001 / TH-002 / TH-003. Si la resolución efectiva de la cama de sólidos
difiere tanto entre unidades, **las ventanas operativas basadas en BedMass no
se comparan en igualdad de condiciones entre espesadores.** Cuantificar antes de
replicar el pipeline a TH-002 y TH-003.

---

## 5. Bloqueos y preguntas abiertas

### 5.1 Nivel de piscina — regla confirmada, magnitud por verificar

Regla operativa declarada por el usuario: las dos piscinas son un **vaso
comunicante**, son la fuente de agua de la planta, **ambos transmisores están en
porcentaje y ambas lecturas son válidas**. El nivel **nunca debe bajar de 75%** y
al **cierre de cada guardia debe quedar en 90% o más**. Para derivar el valor:

- Si los valores son **iguales o parecidos** → se toma el **promedio**.
- Si hay una **diferencia grande** → se toma el **mayor**.

`nivel_piscinas.py` implementa exactamente eso. La versión anterior era
incorrecta por dos motivos, ambos ya corregidos: aplicaba siempre el máximo, y
descartaba un canal si marcaba ≥99,5% o si no cambiaba durante 60 minutos,
asumiendo falla de instrumento. Para una piscina ambos criterios son erróneos —
llena marca 100% y estable no cambia en una hora — y ese filtro descartaba dato
bueno, lo que explicaba el 22,9% de muestras atribuidas a un solo canal. Ahora
solo se rechaza lo físicamente imposible: NaN y valores fuera de [0, 105].

**Queda una anomalía sin explicar.** Con ambos tags en porcentaje, la corrida
anterior reportó divergencia mediana de 67,34 pp y máximo de 49.622. Un
porcentaje no puede valer 49.622. El script ahora **caracteriza antes de
derivar**: imprime cuantiles de cada transmisor, cuenta valores fuera de rango,
muestra el histograma de |A−B| y calcula la correlación de incrementos horarios.

Cómo leerlo:

- Si el histograma de divergencia es **bimodal**, el valle marca el umbral
  natural entre "parecido" y "diferencia grande". Ajustar `--umbral` a ese valor
  en vez de dejar el default de 5 pp.
- Correlación de incrementos alta con niveles muy distintos indica el mismo
  nivel físico con offset o span mal configurado en un transmisor.
- Los valores fuera de [0, 105] son la fuente del máximo de 49.622 y deben
  cuantificarse: si son pocos y aislados, son picos de instrumento.

**Sobre R1**: la corrida anterior dio 6.509 episodios bajo 75% con duración
mediana de 1 minuto. Episodios de uno o dos minutos son ruido de instrumento,
no incumplimiento operativo. El script ahora reporta aparte los episodios de 30
minutos o más, que es lo reportable a operaciones.

Lo que sobrevivió de la corrida anterior, porque depende de la forma y no del
nivel absoluto (reconfirmar): autocorrelación del nivel a 12 h = +0,267 y
24 h = +0,261, por encima de 72 h (+0,178) y 168 h (+0,136), o sea hay firma de
ciclo de guardia; y el cumplimiento de R2 casi idéntico entre turnos (noche
90,4%, día 90,6%), sin un turno sistemáticamente peor.

### 5.2 Tags aún sin identificar

`FIT_114` (flujo hacia piscinas), `LIT_106`, `LIT_107` (niveles de piscina, con
el problema de escala de 5.1), `LIT_108`, `LIT_109` (tanques temporales
294300TK001/TK002). **Mantener declarados aparte para que no entren al modelo
sin decisión explícita.**

`FIT_123` y `FIT_601` **sí** están identificados: traen agua fresca desde el
tanque principal y agua recuperada de QH, respectivamente. **Ninguno es rebose
de los espesadores.** Si entran a un balance hídrico deben sumar por separado, o
inflarán la recuperación atribuida a los espesadores.

### 5.3 Falta la curva nivel-volumen de la piscina

Sin ella, el porcentaje de nivel no se convierte a m³ salvo que el tanque sea
recto. Necesaria para cerrar el balance de agua.

### 5.4 Oportunidad abierta: reconstruir el rebose del tramo sin dato

La piscina integra el balance: entra rebose de espesadores más `FIT_123` y
`FIT_601`, sale consumo de planta. La derivada del nivel más los dos flujos de
entrada **acotan** la contribución de los espesadores en los ~520 días donde el
tag de rebose no existe. Requiere 5.3, y como el consumo de planta no está
medido solo se obtiene el neto, no el rebose aislado. Aun así sería una
restricción física real sobre un período que hoy no tiene ninguna.

### 5.5 Contexto operativo

La planta viene operando exclusivamente con Tren 1 (Bomba 7 + Cizalla 1C) desde
principios de julio. Tiene implicancias sobre los KPI del período reciente y
sobre el balance duty/standby.

---

## 5.bis Hallazgos preliminares del árbol de archivos

Se revisó un listado de la carpeta del proyecto (~150 archivos, **todos planos
en un solo directorio**). Estas son pistas para la Tarea A; confírmalas leyendo
los archivos, no los nombres.

### Riesgos de confusión que hay que resolver primero

**Hay al menos seis datasets candidatos y no está marcado cuál es el vigente.**
`datos.parquet`, `datos_th1c2_020926.parquet`, `Data_Esp1_20260714_0921.parquet`
(y su `.pkl`), `Data_Esp1_*.csv`, `datos_espesadores_20260905_1912.parquet`,
`datos_espesadores_20260906_1317.parquet`,
`datos_espesadores_PRUEBA_20260905_1811.parquet`.

El **canónico es `datos_espesadores_20260906_1317.parquet`**: 68 columnas, 780
días, continuidad verificada. El de `20260905_1912` es la corrida anterior de 63
columnas, previa a la corrección de PB02 y a los cinco tags nuevos. Los
`Data_Esp1_*` provienen del script original **con `ffill().bfill()` aplicado**:
contienen la constante fabricada de H-B y no deben usarse para nada. Mover a
`data/99_deprecated/` con un README que explique por qué.

**Un chunk huérfano de la corrida vieja.** `bloque_0001_20240714.parquet` usa la
nomenclatura antigua, sin fecha de fin, y pertenece a la extracción de 63 tags.
Convive con `bloque_0001_20240714_20240729.parquet`, que es el válido. Verificar
el número de columnas de cada uno antes de decidir; el `_esquema.json` presente
indica cuál esquema corresponde a la carpeta.

**Los archivos `-checkpoint` no son versiones.** Son artefactos de
`.ipynb_checkpoints/` que quedaron aplanados en el listado. No los trates como
historial ni los uses para reconstruir nada. Van a `.gitignore` y se eliminan.
Lo mismo con los `.pyc` (`config_espesadores.cpython-311.pyc`,
`onepager_espesadores.cpython-311.pyc`).

**Las salidas E01–E11 son de una corrida anterior.** Están todas presentes
(`E01_perfil_estructural.csv` hasta `E11c_cizalle.csv`), pero se generaron con un
dataset previo al de 68 columnas y anterior a los hallazgos de la sección 4.
**Deben regenerarse**, no reutilizarse. Prioridad de auditoría, en este orden:

1. `E05_balance_agua.csv` — es el más expuesto a H-C. Si usó el tag de rebose
   sobre el período completo, se ajustó contra la constante fabricada.
2. `E09a_guardias_vs_nulo.csv`, `E09b_guardia_vs_mineral.csv`,
   `E09c_desempeno_por_guardia.csv` — es el análisis de guardias cuya conclusión
   corrige H-D. Revisar qué lags se probaron y rehacerlo con 336 h.
3. `E10c_ventana_consolidada.csv` — probablemente la fuente de la ventana
   operativa recomendada. Depende de las dos anteriores.

**No aparece `bitacora_hallazgos.md` en el listado.** Sí están `LEEME.md`,
`glosario_espesador.md` y `REPORTE_COMPLETO.txt`. Búscala en otras carpetas; si
no existe, créala en `docs/` a partir de la sección 4 y de lo que puedas
reconstruir de `REPORTE_COMPLETO.txt`.

**Nombre del pipeline.** El archivo es `pipeline_espesadores.py`, no
`pipeline_espesadores_v2.py`. Confirmar cuál es el vigente y si hay más de una
versión en otras carpetas.

### Pista valiosa: los cinco tags no identificados podrían estar resueltos

Existen utilidades de descubrimiento de tags —`getAtributes.py` y
`searchTAg.py`— y sus salidas ya en disco:

- `Atributos_PI_20260904_1732/1735/1739-checkpoint.csv`
- `Busqueda_X294100X_20260904_1818-checkpoint.csv`
- `Busqueda_X_294100XFlowX_20260904_1745/1755/1757-checkpoint.csv`
- `Busqueda_X2101XPPX101X_20260905_1751-checkpoint.csv`
- `Busqueda_X2101XPPX10XAmperaje_ABB_20260905_1803-checkpoint.csv`

**Revísalas antes de pedirle nada a planta.** Es posible que el descriptor o los
atributos de PI de `FIT_114`, `LIT_106`–`109` ya estén ahí, y con ellos se
resuelva la sección 5.2 y parte de 5.1 sin gestión externa. Las dos últimas
sugieren además que se estaba buscando amperaje de bombas del área 2101, o sea
hay una línea de trabajo abierta que este traspaso no cubre: pregúntale al
usuario qué buscaba.

### Scripts sin contexto en este traspaso

`demanda_agua.py`, `diagnostico_deriva.py`, `io_espesador.py`,
`regimenes_mineral.py`, `regimenes_v2.py`, `test_escala_temporal.py`,
`test_mineral_vs_operador.py`, `onepager_espesadores.py`, más los notebooks
`TEST1`, `TEST2_2YEARS`, `TEST3_2YEARS`, `test_cluster`, `pipeline.ipynb`,
`getData.ipynb`, `Untitled.ipynb`, y `segmentos.json`.

Ninguno se discutió en la sesión que originó este documento. Clasifícalos en la
Tarea A leyendo su contenido. Presta atención especial a
`test_mineral_vs_operador.py` y `regimenes_v2.py`: por el nombre, son la
implementación del análisis que H-D corrige.

`Untitled.ipynb` y `TEST*.ipynb` son casi con seguridad exploración
desechable, pero **confirma con el usuario antes de archivar cualquier notebook**
— a veces contienen el único registro de una decisión.

---

## 6. Estructura destino propuesta

Orientada a MLOps: configuración declarativa, etapas deterministas con
manifiesto, sin rutas absolutas ni tags hardcodeados, con puntos de entrada CLI
y tests.

```
espesadores/
├─ README.md
├─ pixi.toml
├─ conf/
│  ├─ base/
│  │  ├─ extraccion.yaml          servidor, rango, intervalo, chunking
│  │  ├─ tags.yaml                los 68 tags: id, columna, grupo, unidad, tipo
│  │  ├─ calidad.yaml             umbrales de congelado, NaN, saturación
│  │  ├─ reglas_operativas.yaml   R1=75%, R2=90%, turnos 07:30/19:30
│  │  └─ pipeline.yaml            etapas E00-E12, parámetros por espesador
│  └─ local/                      gitignored: credenciales y rutas de máquina
├─ data/
│  ├─ 00_raw/                     salida cruda de PI. INMUTABLE
│  ├─ 01_interim/                 chunks, calendario de guardias
│  ├─ 02_primary/                 dataset validado + máscara de validez
│  ├─ 03_features/
│  ├─ 04_model_input/
│  ├─ 05_models/
│  └─ 06_reporting/               one-pagers, figuras, tablas
├─ src/espesadores/
│  ├─ extraccion/                 cliente PI, chunking, manifiesto
│  ├─ calidad/                    validez, congelados, diagnósticos
│  ├─ dominio/                    piscinas, trenes duty/standby, rol de guardias
│  ├─ pipeline/                   una etapa por módulo, interfaz común
│  ├─ modelado/
│  └─ reportes/
├─ notebooks/                     exploración numerada. NO producción
├─ tests/
├─ docs/
│  ├─ bitacora_hallazgos.md
│  ├─ diccionario_tags.md
│  ├─ inventario_proyecto.md      lo genera la Tarea A
│  ├─ plan_migracion.md           lo genera la Tarea B
│  └─ decisiones/                 un archivo por decisión metodológica
└─ scripts/                       entrypoints CLI
```

Requisitos de la migración:

- Toda etapa lee de la capa `N` y escribe en la `N+1`. Nunca al revés, nunca
  sobre `00_raw`.
- Toda etapa emite un manifiesto: filas de entrada y salida, filas descartadas y
  por qué, y el hash de su configuración.
- Ningún tag hardcodeado en código. Todo sale de `conf/base/tags.yaml`.
- Los cinco tags no identificados quedan en un bloque aparte del YAML, marcados
  para que no entren al modelo sin decisión explícita.
- El espesador es un parámetro, no una copia del código. Una sola
  implementación debe correr para TH-001, TH-002 y TH-003.

---

## 7. Principios no negociables

Se aprendieron a costa de errores reales en este proyecto. No los relajes.

1. **Nunca `ffill()` ni `bfill()` sobre datos del historiador.** Fabricó una
   constante que se interpretó como comportamiento del PLC durante meses. Los
   huecos se preservan como NaN en su posición correcta.
2. **Los bugs silenciosos son el riesgo principal.** El diccionario duplicado
   mapeó Molino 1 como Molino 2 en toda la historia sin lanzar un error.
   Cualquier estructura que permita colisión silenciosa se valida o se cambia.
3. **El torque de rastra es una respuesta del proceso, no una consigna.** No
   entra como variable de decisión del operador.
4. **La variable de control en correlaciones parciales es la participación de
   tonelaje del propio espesador**, no el tonelaje total del molino.
5. **El estimador within es el correcto para datos de lazo cerrado.** La
   regresión directa sobre registros del historiador da el signo invertido
   (r = +0,133); el estimador de efectos fijos intra-ventana (ventanas de 12 h,
   errores agrupados) recupera el signo correcto (z = −17) sin medir el
   confusor, explotando solo su persistencia temporal.
6. **Los trenes de bombeo están totalmente acoplados.** PP007+PP001 (Tren 1) y
   PP008+PP002 (Tren 2) en TH-001, sin combinaciones cruzadas. Topología
   estrictamente paralela entre C1 y C2, confirmada por croquis en los tres
   espesadores.
7. **Refutación iterativa.** Las conclusiones se prueban contra ventanas de
   datos ampliadas y restricciones físicas. Las correcciones se documentan en la
   bitácora, no se disimulan.
8. **Prueba de humo antes de correr largo.** Dos días de datos antes de
   comprometer horas de extracción.
9. **Los documentos para personas van en español.**
10. **Ninguna cifra de análisis previos se arrastra.** Si hay datos nuevos, se
    recomputa y las cifras viejas se descartan.

---

## 8. Criterios de aceptación

1. `docs/inventario_proyecto.md` existe y cubre todos los archivos, con
   duplicados y huérfanos identificados.
2. `docs/plan_migracion.md` propone `origen -> destino` archivo por archivo.
3. Tras la migración, el pipeline corre de punta a punta con un solo comando y
   produce salidas idénticas a las actuales, salvo donde esta hoja indica una
   corrección deliberada.
4. `conf/base/tags.yaml` contiene los 68 tags, con los cinco no identificados
   en un bloque aparte.
5. `docs/bitacora_hallazgos.md` incorpora H-A a H-H con su evidencia y su nivel
   de confianza.
6. Existe al menos un test que falla si se reintroduce una clave de tag
   duplicada, y otro que falla si alguna etapa aplica `ffill` o `bfill` sobre
   datos del historiador.
7. Ningún módulo de `src/` contiene rutas absolutas ni nombres de tag
   hardcodeados.

---

## 9. Primeros pasos sugeridos

1. **Marcar el dataset canónico.** Antes de nada, dejar por escrito que el
   vigente es `datos_espesadores_20260906_1317.parquet` y apartar los
   `Data_Esp1_*` a `data/99_deprecated/`. Contienen la constante fabricada por
   `ffill` y son la trampa más probable para quien retome el trabajo.
2. **Revisar los CSV de búsqueda de atributos PI** listados en 5.bis. Pueden
   resolver la identidad de `FIT_114` y `LIT_106`–`109` sin gestión con planta.
3. **Verificar H-C** con el snippet de la sección 4. De su resultado depende
   cuánta ventana temporal tiene realmente el análisis y qué cifras publicadas
   hay que recomputar. Es el hallazgo de mayor impacto.
4. **Correr `nivel_piscinas.py` y leer la sección de caracterización** antes que
   R1 y R2, para ajustar `--umbral` al valle del histograma de divergencia.
5. **Correr la Tarea A** y revisar el inventario con el usuario.
6. **Preguntar al usuario** qué buscaba en las consultas de amperaje del área
   2101: hay una línea de trabajo abierta que este traspaso no cubre.
7. Recién entonces proponer el plan de migración.
