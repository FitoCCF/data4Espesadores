# Agente offline — espesadores C2

Agente que corre íntegramente en WSL2, lee PI OSIsoft por la pasarela
PiGateway (host Windows) y analiza el comportamiento de TH-001/002/003 en
tres capas, de la más confiable a la más flexible:

| Capa | Dónde | Qué hace | Necesita |
|---|---|---|---|
| 1. Reglas de operadores | `conf/base/reglas_operadores.yaml` + `agente/reglas.py` | Condiciones declarativas sobre variables por rol; emiten hallazgos con severidad | nada |
| 2. Estadística | `agente/estadistica.py` | Percentiles y tendencia, señales congeladas, atípicos (Hampel), escalones, comparación A/B con permutación, correlación parcial | nada |
| 3. LLM local | `agente/llm.py` (Ollama) | Entiende la pregunta, elige herramientas, redacta; **nunca ve datos crudos** y **no decide qué es alerta** | Ollama + modelo en la GPU |

Las capas 1 y 2 funcionan sin el LLM (`informe`, `vigilar`, `reglas`). El
LLM agrega `preguntar`, `chat` y la redacción del resumen de turno.

```
                 ┌───────────────┐   HTTP/JSON    ┌───────────────────────┐
  PI Data ───►   │ PiGateway (C#)│ ◄────────────  │ agente/datos.py        │
  Archive        │ host Windows  │                │  parquet ▸ caché ▸ PI  │
                 └───────────────┘                │  grilla 1 min, roles   │
                                                  └──────────┬────────────┘
                                                             │ DataFrame por rol
                                 ┌───────────────────────────┼─────────────────┐
                                 ▼                           ▼                 ▼
                          reglas.py                  estadistica.py      dominio/ (episodios)
                                 └───────────────────────────┼─────────────────┘
                                                             ▼
                                                  herramientas.py (JSON)
                                                    ▲                 ▲
                                          cli.py ───┘                 └─── llm.py (Ollama, tool calling)
```

## Uso

```bash
pixi run agente estado                       # cobertura, pasarela, LLM
pixi run agente informe --inicio=-24h        # informe determinístico (+ redacción si hay LLM)
pixi run agente informe --inicio=2026-03-01 --fin=2026-03-08 --espesador TH-001 --guardar
pixi run agente vigilar                      # ciclo cada N min -> data/06_reporting/agente/
pixi run agente preguntar "¿por qué bajó la piscina anoche?"
pixi run agente chat
pixi run agente herramienta anomalias '{"espesador":"TH-002","inicio":"-12h"}'
```

Fechas: `'2026-03-01'`, `'2026-03-01 08:00'`, `ahora`, `hoy 08:00`, `ayer 06:30`, o relativas `-6h`, `-1d 18:30`,
`-2d`. Con `--inicio=-6h` va el `=` (argparse confunde `-6h` con una opción).

### Fuente de datos
`datos.FuenteDatos.ventana(inicio, fin, espesador)` decide sola:
1. **Parquet canónico** (`pipeline.yaml::rutas.entrada`, 2024-07-14 → 2026-09-15).
2. **Caché por día** `data/03_cache_agente/YYYY-MM-DD.parquet` (lo bajado antes).
3. **Pasarela PI** (`recorded`, dato crudo) para lo que falte, a grilla de
   1 min con ZOH para tags `step` y NaN si el hueco supera 1.5×compmax —
   la misma regla con la que se construyó el parquet. El día en curso no se
   cachea en disco (se reutiliza en memoria 2 min).

Cota dura: `max_dias_por_consulta: 31` (agente.yaml). Un día × 68 tags tarda
~2 s por la pasarela.

## Reglas de operadores

Se escriben en `conf/base/reglas_operadores.yaml` con **nombres de rol**,
no tags PI (el encabezado del archivo lista variables y funciones):

```yaml
- id: valvula_abierta_flujo_bajo
  espesador: "*"            # TH-001, TH-002 y TH-003; o 'planta'; o un TH-00X
  condicion: "(valvula_alim > mediana(valvula_alim, '6h') + 10) & (flujo_alim < 0.85 * mediana(flujo_alim, '6h')) & (molienda_total > 100)"
  duracion_min: 45          # debe cumplirse de forma continua
  severidad: media          # alta | media | baja
  mensaje: "Válvula {valvula_alim:.0f} % con flujo {flujo_alim:.0f} m3/h"
```

Funciones: `media/mediana/minimo/maximo(x, '2h')`, `delta(x, '1h')`,
`pendiente(x, '1h')` (por hora), `congelado(x, '60min')`,
`hora_entre('07:15', '07:30')`. Operadores lógicos `& | ~` con paréntesis.
Los resultados de las funciones se pueden citar en el mensaje como
`{pendiente_nivel_piscina_2h:.1f}`.

```bash
pixi run agente reglas listar
pixi run agente reglas validar                                  # sintaxis + nombres, sin datos
pixi run agente reglas probar --id torque_alto --inicio=2026-03-01 --fin=2026-03-31
pixi run agente reglas proponer --id x --condicion "..." --mensaje "..." --severidad alta
pixi run agente reglas pendientes
pixi run agente reglas aprobar --id x      # pasa de reglas_pendientes.yaml a reglas_operadores.yaml
pixi run agente reglas rechazar --id x
```

El LLM también puede **proponer** reglas (herramienta `proponer_regla`)
cuando un operador le describe una condición en lenguaje natural; quedan
en `reglas_pendientes.yaml` hasta que alguien las apruebe. Nunca entra en
vigor una regla sin aprobación humana.

Seguridad de la expresión: se evalúa con `eval` sobre un espacio de nombres
cerrado (solo Series, funciones de arriba y `abs/min/max`), sin builtins; se
rechaza `__`, `import`, `lambda`, `exec`, `eval`, `open`.

## Vigilancia

`pixi run agente vigilar` baja cada `cada_min` (10) la última `ventana_horas`
(8) y escribe en `data/06_reporting/agente/`:
- `alertas.jsonl` — un hallazgo por línea, sin repetir (regla, espesador, inicio).
- `informe_YYYYMMDD_HHMM.{txt,json}` y `ultimo_informe.txt`.

Para dejarlo corriendo: `nohup pixi run agente vigilar > data/06_reporting/agente/vigilar.log 2>&1 &`
(o un servicio de systemd de usuario en WSL2).

## LLM local

Instalación en espacio de usuario (sin sudo), una sola vez con internet:

```bash
curl -L https://github.com/ollama/ollama/releases/latest/download/ollama-linux-amd64.tar.zst | tar --zstd -x -C ~/.local
~/.local/bin/ollama serve &            # queda en http://127.0.0.1:11434
~/.local/bin/ollama pull qwen3:14b     # ~9 GB, entra en la Quadro RTX 5000 (16 GB)
```

Modelo y parámetros en `conf/base/agente.yaml::llm` (o `conf/local/agente.local.yaml`).
Después de instalado no vuelve a necesitar red. `llm.pensar: true` (Qwen3
razona antes de elegir herramienta: elige mejor, tarda 15–40 s por
pregunta; el resumen de turno siempre va sin pensar, ~15 s).

Consejos de uso con un modelo de 14B: una pregunta por vez, con fechas
explícitas si importan (`ayer 06:30`, `2026-09-17 06:30`); pedir "compara X
entre A y B" y no dos preguntas en una. El prompt de sistema lleva la fecha
actual (el modelo no la conoce) y un glosario de variables.

Herramientas que el modelo puede llamar (`herramientas.py`): `cobertura`,
`listar_variables`, `resumen`, `tendencia`, `anomalias`, `evaluar_reglas`,
`comparar_periodos`, `relaciones`, `episodios`, `listar_reglas`,
`proponer_regla`, `buscar_tags`. Todas devuelven JSON compacto (≤ 200
puntos por serie) y el prompt de sistema le prohíbe citar cifras que no
vengan de una herramienta.

## Límites conocidos
- El detector de escalones es un contraste de medianas (antes/después, 2 h)
  con piso de relevancia; señala dónde mirar, no es un CUSUM.
- `congelado` en señales de PLC con actualización gruesa (presión de cama)
  marca tramos de 1–3 h que pueden ser normales; subir `minutos_congelado`
  o la ventana en la regla si molesta.
- Los últimos minutos de una ventana "ahora" pueden venir NaN: PI aún no
  los archivó.
- Un modelo de 14B se equivoca más que Claude al elegir herramientas o al
  interpretar; por eso las alertas nunca dependen de él.
