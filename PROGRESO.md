# PROGRESO — Espesadores C2 (TH-001 / TH-002 / TH-003)

Bitácora de avance, decisiones y razonamiento de las sesiones del 2026-09-15
al 2026-09-17. Complementa `docs/bitacora_hallazgos.md` (que registra los
hallazgos técnicos con evidencia, H-A…H-H y N-1…N-14) con el **cómo y el por
qué** de cada paso, incluidos los errores cometidos y cómo se corrigieron.
Sirve para retomar el trabajo desde cero sin haber estado en la sesión.

---

## 0. Estado al empezar (2026-09-15)

- El repo ya era el resultado de la migración descrita en
  `PROMPT_CLAUDE_CODE.md` (Tareas A–D hechas en una sesión anterior del
  2026-09-06): estructura `conf/ data/ src/espesadores/ tests/ docs/`,
  pipeline E01–E11, `tags.yaml` con 68 tags, bitácora con H-A…H-H y N-1…N-7.
- El dataset canónico era `data/00_raw/datos_espesadores_20260906_1918.parquet`,
  extraído con **`interpolated`** (AF SDK + pythonnet, solo en Windows).
- `data/01_interim/` y `data/02_primary/` estaban vacíos: el pipeline nunca
  había corrido de punta a punta para los tres espesadores.
- Existía una herramienta nueva fuera del repo:
  `~/data4cdpv1_local/scripts/pi_tool.py` + `pi_client.py`, un cliente HTTP a
  una **pasarela PiGateway** (C#/AF SDK) que corre en Windows y permite
  consultar PI desde WSL2 sin pythonnet. Métodos: recorded, interpolated,
  summary, plot, perfil, buscar.

**Encargo del usuario:** validar los tags de `tags.yaml` contra PI con esa
herramienta, ejecutar lo pendiente de `PROMPT_CLAUDE_CODE.md`, **re-extraer
con método `recorded`** (dato crudo archivado) los tres espesadores y correr
el pipeline para los tres.

---

## 1. Validación de tags contra PI en vivo

**Qué se hizo:** `pi_tool.py perfil --tags-file` con los 68 tags de
`extraccion_pi`, más `buscar` con patrones para los tags dudosos.

**Hallazgos:**

| Tema | Resultado | Decisión |
|---|---|---|
| 67/68 tags existen con historia desde **2022-12-30** (1354 días) | Más rango del que asume `extraccion.yaml` (2024-07-14) | Se mantuvo 2024-07-14 por continuidad con la corrida anterior; extender es decisión de alcance del usuario (N-10) |
| `C2_Sol_Overflow_Output` **no existe** en PI con ese nombre | Los reales son `C2_Sol_Overflow_average/L1/L2_Output`, con **un solo evento** (2026-09-10) | H-E se sostiene en la práctica; no se cambió el tag, se documentó |
| `C2_Ratio_concentracion_Output` sin datos desde 2026-06-16 | Tag vivo pero congelado 91 días | Documentado |
| Bloques `completar: true` de TH-002/TH-003 en `tags.yaml` | `FV_1101` existe pero es la **válvula del Molino 1** (área 293400); `WT_154/DIT_154/WT_152/DIT_152/FV_1201/WT_164/DIT_164/WT_162/DIT_162` **no existen** | **Corregido**: se reemplazaron por los tags reales ya validados en `extraccion_pi` (WT_186/DIT_186/WT_184/DIT_184/FV_1002; WT_234/DIT_234/WT_236/DIT_236/FV_1003) |
| `floculante`/`agua_dilucion` de TH-002 y TH-003 apuntaban a los de TH-001 (FIT_104/FIT_101) | Existen dedicados: FIT_105/FIT_102 (E2), FIT_106/FIT_103 (E3) | **Corregido** (N-9) |
| PB03 (pedido posterior del usuario) | **No existe** ningún Molino 3 en PI (`*PB03*`, `*PB003*`, `*Molino_3*`, `*ML003*`) | `globales.molinos: [PB01, PB02]` (N-14) |

Razonamiento: los `completar: true` eran suposiciones nunca verificadas; la
misma clase de bug silencioso que H-A (Principio #2). Se probó cada nombre en
PI antes de tocar nada. Los 8 tests siguen pasando tras el cambio.

---

## 2. Re-extracción con `recorded`

### 2.1 Por qué `recorded` y no `interpolated`
`InterpolatedValues` interpola en el servidor sin distinguir tags `step`
(válvulas, consignas) de continuos: un tag congelado y uno estable se ven
igual. `recorded` entrega el evento crudo tal como lo archivó el historiador;
`pi_tool.py --grilla 1min` lo reconstruye a grilla con **ZOH para tags step**,
interpolación lineal para continuos, y NaN donde el hueco supera 1.5×`compmax`
(pérdida real, no compresión). Cumple el criterio #1 del traspaso
(auditabilidad hasta el dato crudo).

### 2.2 Prueba de humo (Principio #8)
2 días, 68 tags: 3 segundos, 2880 × 66 columnas, cobertura 90.8 %. Los dos
tags sin dato eran los esperados (Sol_Overflow inexistente, Ratio_conc
congelado).

### 2.3 Primer intento: una sola corrida de 793 días — **OOM**
- 265 bloques de 3 días, ~40 s/bloque (los bloques de 2024 traen ~1.9 M
  eventos crudos cada uno, 25× más densos que la prueba de humo reciente).
- Al terminar de bajar, `pi_tool.py` concatena los 265 bloques en memoria
  **antes** de reconstruir la grilla → 47 GB de memoria virtual, 31 GB RSS,
  **matado por el kernel** (`dmesg: Out of memory: Killed process`).
- El usuario pidió tomar el control manual; se detuvo mi proceso en segundo
  plano en 32/265 bloques y se le entregó el comando para retomar (los
  checkpoints en `_chunks_1min/` se reutilizan si `--inicio/--fin/--etiqueta`
  no cambian).

### 2.4 Solución: 7 tramos de ~120 días
Mismo rango total partido en tramos cuyos límites caen exactamente en la
grilla de 3 días desde 2024-07-14 (40 bloques por tramo), cada uno consolidado
y reconstruido por separado. Peak de memoria ~15 GB en el tramo más denso.

Decisión del usuario: **borrar todo y empezar de cero** (en vez de reutilizar
los chunks ya bajados) y correr cada tramo manualmente desde su terminal. Se
le fueron entregando los comandos uno por uno, verificando cada `_valores.csv`
(172 800 filas = 120 días × 1440 min, columnas 60/60/60/60/65/65/66 según
qué tags ya existían en cada período — consistente con H-C y H-F).

### 2.5 Fixes a `pi_tool.py` (fuera del repo, en `data4cdpv1_local`)
1. Con `--grilla`, el código escribía igual un CSV crudo evento-por-evento
   redundante (2 GB en el tramo 1). Se cambió para no escribirlo.
2. Se agregó log verbose en la consolidación (cada 10 bloques leídos) y en la
   reconstrucción (un renglón por tag con eventos y tiempo), porque el paso
   parecía "congelado" durante 8–10 min sin imprimir nada.
3. Mi primer monitor de progreso tenía un bug: el patrón de `pgrep` se
   auto-matcheaba con el texto del propio script y reportaba "vivo" siempre.
   Se corrigió filtrando por `bin/python pi_tool.py` y verificando el PID real.

> Nota: `pi_tool.py` cambió en disco después (edición del usuario); los fixes
> de arriba pueden no estar en su versión actual.

### 2.6 Consolidación
Script puntual (scratchpad) → `data/00_raw/datos_espesadores_recorded_20260916_0357.parquet`:
- 7 tramos concatenados, columnas renombradas de tag PI crudo a `columna` de
  `tags.yaml`, `Sol_Overflow_Output` agregada vacía para mantener 68 columnas.
- **1 142 242 filas × 68**, continuidad de índice **0 huecos, 0 duplicados**,
  cobertura global 87.23 %. Los tags digitales (STATUS) ya vienen como 0/1.
- `conf/base/pipeline.yaml::rutas.entrada` apunta a este parquet (N-8).
- El parquet anterior (`interpolated`) sigue en disco, no se borró.

---

## 3. Pipeline E01–E11 para los tres espesadores (N-11)

Corrido sin errores ni warnings. Cifras clave (dataset `recorded`):

| | TH-001 | TH-002 | TH-003 |
|---|---:|---:|---:|
| Brecha recuperación ALTA–BAJA por mineral | 5.3–7.2 pp | 7.0–9.3 pp | 7.7–9.6 pp |
| Ganancia a tonelaje constante | +39 a +52 m³/h | +71 a +96 m³/h | +67 a +80 m³/h |
| Tren 2 vs Tren 1 (emparejado) | 35/35 celdas, +1.60 pp | 36/36, +3.13 pp | 34/36, +3.32 pp |

Decisión: no se compararon número a número contra la corrida `interpolated`
(pendiente si se quiere cuantificar el efecto del método de extracción).

---

## 4. Conocimiento operativo aportado por el usuario (guardado en `tags.yaml`)

- **El insight principal es el nivel de piscina (LIT_106/LIT_107).**
- **FIT_114** (flujo hacia piscinas) es indicador **indirecto**: sube cuando
  los tanques temporales LIT_108/LIT_109 suben y arrancan bombas automáticas.
- Las **válvulas de alimentación FV_1001/1002/1003 las mueve el operador**;
  interesa cómo, y si depende del tipo de mineral.
- **FIT_123** (agua fresca) y **FIT_601** (agua de QH) entran a la piscina y
  **no son rebose** de espesadores: si entran a un balance, aparte.
- Hipótesis 1: piscina baja → se baja la velocidad de descarga a propósito.
- Hipótesis 2: parada aguas arriba → mineral grueso se apelmaza en la válvula
  de ingreso → flujo bajo persiste → el operador abre la válvula.

---

## 5. Mejoras al pipeline y al one-pager individual

### 5.1 Clasificación de variables con datos, no por supuesto (E10)
Antes `valvula_alim` y `floculante` estaban **hardcodeadas** como
`sin_efecto` y las de proceso como `objetivo`, sin prueba. Se agregó
`comun.prueba_diferencia()`: mediana del tercio ALTA vs BAJA de recuperación
(dentro de cada tipo de mineral, luego juntos) + p-valor por permutación.

Error cometido y corregido: con ~450 k filas **todo** sale p<0.05, hasta el
ruido (TH-003: válvula 44.174 vs 44.0 "significativa"). Se agregó un **piso
de relevancia**: la diferencia debe ser ≥ 3 % del rango p10–p90 de la
variable. Solo se promueve a objetivo si es significativa **y** relevante.

Resultado, distinto por espesador:
- TH-001: válvula sin efecto (31 vs 31); floculante **sí** (0.45 vs 0.39).
- TH-002: válvula **sí** (38 vs 33); floculante **sí**.
- TH-003: ninguna (diferencia estadística pero no relevante).
- Presión de cama confirma objetivo en los tres.

### 5.2 Métricas secundarias: piscina y FIT_114 (E10)
Nivel de piscina (vía `dominio/piscinas.derivar_nivel`) y FIT_114 en los
mismos timestamps del tercio ALTA vs BAJA de cada espesador. Con aviso de que
son de **planta** (compartidos por los 3 + agua externa). Error evitado: un
resultado "significativo" en dirección **contraria** a la hipótesis no se
reporta como confirmación (le pasó a TH-001: piscina más baja cuando recupera
más) — se distingue favorable / contrario / sin diferencia.

### 5.3 Mineral vs guardia sobre el resultado (E09)
La comparación η² guardia vs mineral solo cubría consignas; se extendió a
`wt_activo` y `recuperacion`. Respuesta: en TH-002 y TH-003 **manda el
mineral**; en TH-001 recuperación "similar", % sólidos mineral.

### 5.4 Hipótesis operativas en E10 (primera versión, agregada)
- Piscina baja → descarga: por **terciles**, la descarga sale **mayor** con
  piscina baja en los tres (contrario a la hipótesis).
- Atoro: correlación parcial válvula~flujo controlando tonelaje del molino
  (`comun.corr_parcial`): sin relación clara (TH-001 −0.03, TH-003 +0.05),
  directa en TH-002 (+0.16). Es contemporánea; no captura desfase.

Bug corregido en el one-pager: `str.capitalize()` en Python pone en
minúscula el resto de la frase ("No es…" → "no es…"); se quitó.

Los tres one-pagers individuales quedaron con secciones 5 (métricas
secundarias), 6 (mineral vs guardia) y 7 (piscina, válvula y atoro).

---

## 6. Análisis por episodios (dataset CRUDO)

Razonamiento: el filtro "planta produciendo" de E03 **elimina justamente las
filas de parada**, así que no se puede detectar paradas desde el pipeline.
Los módulos de `dominio/` leen el parquet crudo y reconstruyen las señales
activas (vel_descarga, vel_cizalle, wt_activo) con la regla de E04.

Método: **análisis de épocas superpuestas** — alinear todos los episodios en
t=0 y tomar la mediana por bin de tiempo, contra una referencia estable (≥ 4 h
lejos de cualquier evento).

### 6.1 Paradas de molienda (`atoro_alimentacion.py`, N-12)
- Primera versión: solo PB01, 248 episodios con mediana 78 min pero **p90 de
  1003 min y máximo de 6.9 días** → se agregó filtro 10–240 min para separar
  el corte breve de la parada de planta (dinámica no comparable).
- Segunda versión (pedido: considerar PB01 y PB02): eventos `parada_total`,
  `parada_parcial`, y luego `parada_PB01` / `parada_PB02` (un molino cae, el
  otro sigue), para **todos** los parámetros operativos.
- **Resultado (los tres espesadores):** al volver la molienda la válvula está
  **más abierta** y el flujo entra **más alto** que en operación estable, y
  ambos bajan a lo normal en 2–3 h mientras los molinos suben de ~50–75 % a
  ~95 %. **No aparece la firma de atoro.** Señal tenue solo en parada
  parcial (válvula sigue abierta de más entre min 60–135 con flujo 2–3 % bajo
  lo normal, pero por encima de lo que predice el tonelaje reducido).
- Lectura: al reiniciar se abre de más (a propósito o por lógica de control)
  y se acomoda solo. No hay tag de ciclón ni sensor de "material atorado".

### 6.2 Piscina baja (`piscina_episodios.py`, N-13)
- Episodios con nivel < 75 % (R1) durante ≥ 30 min (780 episodios; la
  piscina está bajo 75 % el **19.5 % del tiempo**, mediana 4.4 h por episodio).
- **Resultado:** al cruzar bajo 75 % la descarga está **elevada** (36 / 25 /
  26 vs 33 / 22 / 22 con piscina sana) y baja gradualmente a lo normal en
  ~2 h, **nunca por debajo**. La piscina sigue cayendo en esa ventana.
- Lectura: la hipótesis solo se ve como corrección lenta de vuelta a lo
  normal; coherente con la física (más descarga → menos rebose → piscina baja
  → el operador reduce). La forma fuerte ("que no descargue") no aparece.

### 6.3 Tendencia: qué se hizo para que la piscina SUBA (pedido posterior)
Ventana (p10–p90, mediana) de todos los parámetros cuando la piscina está
**subiendo** (≥ +1 pp/h) y llega al tercio alto en la hora siguiente, vs
mediana cuando **baja** desde el tercio alto. Lo mismo para FIT_114
(umbral +2 %/h). Solo con planta produciendo y un tren en servicio.
Resultado TH-001: mientras la piscina sube, descarga 30 vs 35 bajando, y
floculante 0.40 vs 0.33 — **en esta formulación sí aparece la hipótesis 1.**

---

## 7. Reportes

### 7.1 One-pagers individuales
`data/06_reporting/TH00X/onepager_TH00X.html` + `REPORTE_COMPLETO.txt`,
versionados en git (el resto de `06_reporting` no).

### 7.2 One-pager consolidado (`reportes/onepager_consolidado.py`)
Pedido: un solo one-pager con los tres, **más gráficos que texto**, en torno
al nivel de piscina, válvula y flujo de alimentación, tonos plomos, resaltar
máximos y mínimos, sin omitir ningún parámetro.

Diseño: SVG embebido generado en Python (sin dependencias, funciona offline
y en GitHub). Paleta validada con el validador de la guía de visualización:
un plomo por espesador (`#1F2326` / `#5C646C` / `#8C939A`, ΔE ≥ 16 entre
adyacentes, contraste ≥ 3:1) **más marcador distinto ●■▲** como codificación
secundaria (la identidad no depende solo del tono); acentos reservados
ámbar = máximo, azul = mínimo. Un solo eje por gráfico; cuando los tres
espesadores tienen escalas distintas se indexa a la operación estable = 100
y el valor absoluto va en la etiqueta y el tooltip.

Versión 2 según la evaluación del usuario:
1. Ventanas de los 7 parámetros de proceso + **bombas por tren y por tag**
   (E10g, nuevo).
2. **Qué se hizo para que suba** la piscina / FIT_114: los 9 parámetros,
   barra = subiendo, marcador = bajando (6.3).
3. **Parada de Molino 1 / Molino 2 / total**: molienda + 9 parámetros
   minuto a minuto, 3 h, índice base 100 (30 gráficos).
4. Operación **por tipo de mineral** (E10h, nuevo) y **por par de guardia**
   (E09d, nuevo) en líneas; η² mineral vs guardia; recuperación por mineral.
5. Recuperación y % sólidos **por tren, con las bombas de cada tren**.

88 gráficos. Publicado también como artefacto:
https://claude.ai/artifact/Sj5YRvduEcWRjDzN19tQDt

Limitación: no hay navegador en WSL para captura; se verificó estructura
(sin NaN en coordenadas, títulos, márgenes) pero no el render final.

### 7.3 Diagrama del pipeline (Mermaid)
`docs/diagrama_pipeline.html` (autocontenido, Mermaid desde cdnjs, imprime a
PDF en A3 apaisado) y `docs/diagrama_pipeline.mmd`. Artefacto:
https://claude.ai/artifact/7RJCvCAPmgjG5Bfd8RfPgB

---

## 8. Git y publicación

- Roles de operación (`data/00_raw/rol_operaciones/*.md`, nombres de
  personal) **sacados del tracking** por privacidad; siguen en disco y el
  pipeline los lee local. Decisión del usuario: **no** reescribir el
  historial (siguen en el primer commit `49e700c`).
- `.gitignore`: se versionan `onepager_*.html`, `REPORTE_COMPLETO.txt` y
  `onepager_consolidado.html`; se ignoran `tags_extraccion.txt` (derivado) y
  swaps de editor. `conf/base/tags.yaml.default` (copia vieja, no mía) se
  dejó sin trackear a pedido del usuario.
- Commits de estas sesiones: `3a9c739` → `f83f0da` en `origin/main`.

---

## 9. Cómo reproducir todo

```bash
# 1) Extracción recorded por tramos (desde ~/data4cdpv1_local/scripts, con la pasarela arriba)
pixi run --manifest-path ~/data4cdpv1_local/pixi.toml python pi_tool.py \
  --dir-salida ~/data4Espesadores/data/00_raw extraer \
  --tags-file ~/data4Espesadores/conf/base/tags_extraccion.txt \
  --metodo recorded --inicio "2024-07-14 00:00:00" --fin "2024-11-11 00:00:00" \
  --grilla 1min --formato ancho --prefijo espesadores_recorded_tramo1 --etiqueta 1min
# ... tramos 2-7 con límites cada 120 días: 2024-11-11, 2025-03-11, 2025-07-09,
#     2025-11-06, 2026-03-06, 2026-07-04, 2026-09-15 05:22:00
# tags_extraccion.txt se regenera con: python -c "import yaml;print('\n'.join(r[0] for r in yaml.safe_load(open('conf/base/tags.yaml'))['extraccion_pi']))"

# 2) Consolidar tramos -> parquet (script puntual, ver sección 2.6) y apuntar pipeline.yaml

# 3) Pipeline y episodios (desde ~/data4Espesadores)
pixi run pipeline TH-001 ; pixi run pipeline TH-002 ; pixi run pipeline TH-003
for e in TH-001 TH-002 TH-003; do pixi run episodios --espesador $e; pixi run piscina-episodios --espesador $e; done
pixi run onepager-consolidado
pixi run test
```

---

## 10. Pendientes y decisiones abiertas

1. **Extender el rango a 2022-12-30** (508 días más disponibles en PI).
2. Cuantificar la diferencia `recorded` vs `interpolated` sobre las cifras.
3. E03 sigue usando solo PB01 para "planta produciendo"; cambiarlo a la suma
   de molinos altera todas las cifras — decisión de alcance.
4. Un tag específico de ciclón (cortocircuito) afinaría el análisis de atoro;
   no hay ninguno en `tags.yaml`.
5. Curva nivel–volumen de la piscina (§5.3 del traspaso) para cerrar el
   balance de agua y reconstruir el rebose del tramo sin dato.
6. Revisar visualmente el consolidado y ajustar lo que se vea montado o
   cortado (no se pudo capturar pantalla desde WSL).
7. Actualizar `README.md` con las cifras `recorded` y el consolidado.
