# -*- coding: utf-8 -*-
"""
config.py — carga la configuración declarativa de `conf/base/*.yaml` (y de
`conf/local/*.yaml` para lo específico de cada máquina) y la expone con los
mismos nombres que usaba el antiguo `config_espesadores.py`, para que los
módulos de `pipeline/`, `dominio/`, `calidad/` y `extraccion/` no tengan que
reescribirse función por función.

Ningún tag ni ruta absoluta vive en este archivo: todo sale de los YAML.
Ver docs/plan_migracion.md §6 y conf/base/*.yaml para el detalle de cada
sección.
"""
from pathlib import Path

import yaml

# Raíz del proyecto: src/espesadores/config.py -> src/espesadores -> src -> raíz.
RAIZ = Path(__file__).resolve().parents[2]
_CONF_BASE = RAIZ / "conf" / "base"
_CONF_LOCAL = RAIZ / "conf" / "local"


def _cargar_yaml(nombre, base=_CONF_BASE):
    with open(base / nombre, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _cargar_yaml_local(nombre, por_defecto=None):
    ruta = _CONF_LOCAL / nombre
    if not ruta.exists():
        return por_defecto or {}
    with open(ruta, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _hora_a_decimal(hhmm):
    """'07:30' -> 7.5"""
    h, m = str(hhmm).split(":")
    return int(h) + int(m) / 60


_tags = _cargar_yaml("tags.yaml")
_calidad = _cargar_yaml("calidad.yaml")
_reglas = _cargar_yaml("reglas_operativas.yaml")
_pipeline_conf = _cargar_yaml("pipeline.yaml")
_extraccion_conf = _cargar_yaml("extraccion.yaml")
_extraccion_local = _cargar_yaml_local("extraccion.local.yaml")

# ==============================================================================
# TAGS
# ==============================================================================
GLOBALES = _tags["globales"]

# Tags pendientes de confirmar con Instrumentación (marcados `completar: true`
# en tags.yaml, ex-comentario "# <<< COMPLETAR" de config_espesadores.py).
# Se completa al resolver ESPESADORES, abajo.
TAGS_A_COMPLETAR = []


def _resolver_tag(valor, espesador, campo):
    """Un campo de tags.yaml es un tag plano, o {tag, completar: true}."""
    if isinstance(valor, dict):
        if valor.get("completar"):
            TAGS_A_COMPLETAR.append((espesador, campo, valor["tag"]))
        return valor["tag"]
    return valor


def _resolver_espesador(nombre, bruto):
    cfg = {}
    for campo, valor in bruto.items():
        if campo == "trenes":
            cfg["trenes"] = [
                {k: _resolver_tag(v, nombre, f"trenes[{i}].{k}") for k, v in tren.items()}
                for i, tren in enumerate(valor)
            ]
        elif campo == "flujos_todos":
            cfg[campo] = list(valor)
        elif campo in ("nombre_largo", "tag_equipo"):
            cfg[campo] = valor
        else:
            cfg[campo] = _resolver_tag(valor, nombre, campo)
    return cfg


ESPESADORES = {nombre: _resolver_espesador(nombre, bruto)
               for nombre, bruto in _tags["espesadores"].items()}

# Tags de dominio/piscinas.py — antes hardcodeados como COL_A/COL_B en el script.
PISCINAS_TAGS = _tags["piscinas"]

# Tags confirmados por PI pero sin rol en el pipeline (bloque aparte, no entran
# al modelo sin decisión explícita — criterio de aceptación de la migración).
TAGS_NO_ASIGNADOS = _tags["no_asignados"]

# Variables de interés del diagnóstico de guardias (dominio/guardias.py).
VARIABLES_INTERES_GUARDIAS = _tags["diagnostico_guardias"]["variables_interes"]

# Lista maestra de extracción PI: 68 tags (tag_pi, columna, grupo, descripcion).
# Fuente única para src/espesadores/extraccion/extraer_pi.py.
TAGS_EXTRACCION_PI = [tuple(fila) for fila in _tags["extraccion_pi"]]
TAGS_DIGITALES = set(_tags["tags_digitales"])

# ==============================================================================
# CALIDAD
# ==============================================================================
RANGOS_POR_TIPO = {k: tuple(v) for k, v in _calidad["rangos_por_tipo"].items()}
DIAGNOSTICO = _calidad["diagnostico"]

# ==============================================================================
# REGLAS OPERATIVAS
# ==============================================================================
_t = _reglas["turnos"]
TURNOS = {
    "inicio_dia_h": _hora_a_decimal(_t["inicio_turno_a"]),
    "duracion_h": _t["duracion_h"],
    "codigo_dia": _t["codigo_dia"],
    "codigo_noche": _t["codigo_noche"],
    "codigo_descanso": _t["codigo_descanso"],
}
CICLO_GUARDIA_DIAS = _t["ciclo_dias"]
PROCESO = _reglas["proceso"]

# Reglas de piscinas.py: umbral de divergencia, horarios de cambio de guardia
# (07:30/19:30, coincide con `turnos` de arriba) y los dos umbrales R1/R2.
REGLAS_PISCINAS = dict(_reglas["piscinas"])
REGLAS_PISCINAS["horas_cambio_guardia_decimal"] = [
    _hora_a_decimal(h) for h in _reglas["piscinas"]["horas_cambio_guardia"]
]

# ==============================================================================
# PIPELINE
# ==============================================================================
VENTANAS_MIN = _pipeline_conf["ventanas_min"]
CV_ESTADO_ESTACIONARIO = _pipeline_conf["cv_estado_estacionario"]
RUTAS = {
    "entrada": str(RAIZ / _pipeline_conf["rutas"]["entrada"]),
    "roles_guardia": [str(RAIZ / p) for p in _pipeline_conf["rutas"]["roles_guardia"]],
    "salidas": str(RAIZ / _pipeline_conf["rutas"]["salidas"]),
}

# ==============================================================================
# EXTRACCIÓN PI (solo aplica en la máquina Windows con AF SDK)
# ==============================================================================
EXTRACCION = dict(_extraccion_conf)
EXTRACCION["af_sdk_path"] = _extraccion_local.get("af_sdk_path")
EXTRACCION["rutas"] = dict(_extraccion_conf["rutas"])
EXTRACCION["rutas"]["salida"] = str(RAIZ / _extraccion_conf["rutas"]["salida"])
EXTRACCION["rutas"]["chunks"] = str(RAIZ / _extraccion_conf["rutas"]["chunks"])
