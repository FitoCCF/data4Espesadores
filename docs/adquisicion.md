# `src/acquisition` — adquisición desde otras fuentes

Paquete traído de `data2TesisV2` y **hecho autocontenido en este repo**: ningún
módulo importa de aquel proyecto ni del paquete `espesadores`, así que se
ejecuta tal cual desde `data4Espesadores` (`tests/test_agente.py` lo verifica).

Cubre fuentes **distintas** a las de los espesadores: el **courier de
concentrado final de cobre** (leyes/intensidades Cu-Fe-Mo-Sc-Zn). Para los 68
tags de espesadores de relaves la ruta es el agente
(`src/espesadores/agente/datos.py`), que además reconstruye la grilla de 1 min
y cachea; ver `docs/agente_offline.md`.

| Módulo | Qué hace | Necesita |
|---|---|---|
| `from_pi.py` | 5 tags del courier (o tags arbitrarios con `--tags`) desde PI por la pasarela PiGateway. **Ruta vigente.** | `requests`, `pandas` |
| `from_pi_afsdk.py` | Lo mismo con AF SDK directo (pythonnet). **Referencia**, solo Windows con PI AF Client. | Windows + `clr` |
| `from_db.py` | Intensidades y ensayos de la tabla Postgres `works4cdp_assay` | `sqlalchemy` + driver Postgres |
| `database.py` | `DBManager` / `Extractor` (portado de `src/database` de data2TesisV2) | ídem, import perezoso |
| `pi_client.py` | Cliente HTTP de la pasarela. **Copia única del repo**: es la que usa también el agente | `requests` |
| `config.py` | `DATA_RAW = data/00_raw` de este repo (en el original era `data/raw`) | — |

## Uso

```bash
# Courier: 5 tags, interpolado cada 15 min (igual criterio que el script AF SDK)
pixi run adquirir-pi --out data/00_raw/Intensidades_nuevo.csv
pixi run adquirir-pi --hasta 2026-09-21 --metodo recorded --out data/00_raw/Intensidades_crudo.csv

# Tags arbitrarios (dato crudo archivado, formato ancho sin relleno)
pixi run adquirir-pi --tags _294100_LIT_1011_ABB --desde 2026-08-01 --hasta 2026-09-21 \
    --out data/00_raw/pi_espesadores.csv

# Postgres (courier)
pixi run adquirir-db --sample-id 24 --tabla assays --hasta 2026-08-31 \
    --out data/00_raw/assays_cobre.csv
```

Equivalente sin pixi: `PYTHONPATH=src python -m acquisition.from_pi …`.

## Pasarela PiGateway: host y token

- **Host**: se autodetecta desde WSL2 (loopback en modo espejo, gateway por
  defecto en modo NAT). Si no lo encuentra: `export PI_GATEWAY_HOST=<ip_windows>`
  o `--host`.
- **Token**: desde 2026-10 la pasarela exige la cabecera `X-PI-Token`. Sin él
  responde `401` y el cliente lanza `PiAuthError` con el motivo. Hay que
  exportar el mismo valor que usa la pasarela:
  ```bash
  export PI_TOKEN='...'          # misma frase con la que se arrancó proxy_pi.py
  ```
  Para el agente también sirve `datos.pi_token` en `conf/local/agente.local.yaml`
  (esa carpeta está en `.gitignore`). **El token nunca va en el repo.**
  `pixi run agente estado` dice explícitamente si el problema es el token.

## Notas de la adaptación

- `pi_client.py` se unificó: antes había dos copias distintas en la máquina
  (la vieja que traía `acquisition`, sin la API cruda `*_raw`, y la de
  `data4cdpv1_local/scripts`). Ahora el repo tiene **una sola** y el agente la
  usa; `datos.pi_client_dir` queda solo como respaldo.
- `from_db.py` y `from_pi.py` importaban `..database` y `..pipeline.config`,
  que no existen aquí. Se reemplazaron por `.database` y `.config` locales.
- `__init__.py` ahora importa de forma perezosa: `import acquisition` ya no
  exige `sqlalchemy` (que `from_db` sí necesita) ni Windows (que `from_pi_afsdk`
  necesita).
- Los tags del courier (`_296290_ConcFinal_Canal*_ABB`) viven en `from_pi.py`,
  no en `conf/base/tags.yaml`: no son tags de espesadores y `tags.yaml` sigue
  siendo la fuente única **para el pipeline de espesadores**. Si en algún
  momento se cruzan leyes de concentrado con la recuperación de agua, ahí sí
  conviene declararlos en `tags.yaml`.
