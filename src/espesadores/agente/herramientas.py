# -*- coding: utf-8 -*-
"""
herramientas.py — lo que el agente puede hacer, con o sin LLM.

Cada herramienta es una función `nombre(**kwargs) -> dict/list` serializable
a JSON, más su esquema (para el tool calling del LLM y para `--help`). La
CLI las invoca directo; el LLM las invoca a través de llm.py. Ninguna
devuelve series completas: resúmenes, episodios y tendencias reducidas,
para que quepan en el contexto del modelo local.

Todas reciben fechas como texto ('2026-03-01', '2026-03-01 08:00',
'ahora', '-6h' relativo a ahora) en hora local America/Lima.
"""
import json
import re

import pandas as pd

from espesadores.config import AGENTE, ESPESADORES, PROCESO, REGLAS_PISCINAS
from espesadores.agente import estadistica as E
from espesadores.agente import reglas as R
from espesadores.agente.datos import FuenteDatos, describir_roles, variables_disponibles
from espesadores.dominio.atoro_alimentacion import detectar_episodios

_FUENTE = None
_REL = re.compile(r"^-(\d+)(min|h|d)(?:\s+(\d{1,2}:\d{2}))?$")
_DIA = re.compile(r"^(hoy|ayer|anteayer)(?:\s+(\d{1,2}:\d{2}))?$", re.I)


def fuente():
    global _FUENTE
    if _FUENTE is None:
        _FUENTE = FuenteDatos()
    return _FUENTE


def _t(valor):
    """'ahora' | '-6h' | '-1d 06:30' | 'ayer 06:30' | 'hoy' | '2026-03-01 08:00' -> Timestamp local."""
    f = fuente()
    txt = str(valor).strip() if valor is not None else ""
    if txt.lower() in ("ahora", "now", ""):
        return f.ahora()
    m = _DIA.match(txt)
    if m:
        dias = {"hoy": 0, "ayer": 1, "anteayer": 2}[m.group(1).lower()]
        base = f.ahora().normalize() - pd.Timedelta(days=dias)
        return base + pd.Timedelta(m.group(2) + ":00") if m.group(2) else base
    m = _REL.match(txt)
    if m:
        n, u = int(m.group(1)), m.group(2)
        t = f.ahora() - pd.Timedelta(**{{"min": "minutes", "h": "hours", "d": "days"}[u]: n})
        if m.group(3):   # '-1d 06:30' = ese día a esa hora
            t = t.normalize() + pd.Timedelta(m.group(3) + ":00")
        return t
    return f.ts(txt)


def _esp(espesador):
    e = (espesador or "planta").strip()
    if e.lower() in ("planta", "plant", "todos", "*"):
        return "planta"
    e = e.upper().replace("TH00", "TH-00").replace("TH_", "TH-")
    if e in ("E1", "E2", "E3"):
        e = "TH-00" + e[1]
    if e not in ESPESADORES:
        raise ValueError(f"espesador desconocido {espesador!r}; usar uno de {list(ESPESADORES)} o 'planta'")
    return e


# ============================================================================
# Herramientas
# ============================================================================
def listar_variables(espesador="planta"):
    """Variables (por rol) que existen para un espesador o para la planta."""
    e = _esp(espesador)
    return {"espesador": e,
            "variables": [{"rol": r, "columna": c, "tag_pi": t, "descripcion": d}
                          for r, c, t, d in describir_roles(e)]}


def cobertura():
    """Rango cubierto por el parquet histórico y estado de la pasarela PI."""
    c = fuente().cobertura()
    c["max_dias_por_consulta"] = AGENTE["datos"]["max_dias_por_consulta"]
    return c


def resumen(espesador, inicio, fin="ahora", variables=None):
    """Percentiles, cobertura y tendencia de cada variable en la ventana."""
    e = _esp(espesador)
    df = fuente().ventana(_t(inicio), _t(fin), e)
    return E.resumen(df, e, variables)


def tendencia(espesador, variable, inicio, fin="ahora"):
    """Serie reducida (<=200 puntos, mediana por bloque) de una variable."""
    e = _esp(espesador)
    df = fuente().ventana(_t(inicio), _t(fin), e)
    if variable not in df.columns:
        raise ValueError(f"variable {variable!r} no existe; ver listar_variables")
    return E.tendencia(df, variable)


def anomalias(espesador, inicio, fin="ahora", minutos_congelado=60, max_items=15):
    """Señales congeladas, atípicos (Hampel) y cambios de régimen."""
    e = _esp(espesador)
    df = fuente().ventana(_t(inicio), _t(fin), e)
    a = E.anomalias(df, e, minutos_congelado=minutos_congelado)
    a["cambios_de_regimen"] = sorted(a["cambios_de_regimen"], key=lambda x: -abs(x["z"] or 0))[:max_items]
    a["congelados"] = sorted(a["congelados"], key=lambda x: -x["minutos"])[:max_items]
    a["atipicos"] = sorted(a["atipicos"], key=lambda x: -x["n_atipicos"])[:max_items]
    return a


def evaluar_reglas(espesador, inicio, fin="ahora", solo_ids=None):
    """Aplica las reglas de operadores sobre la ventana y devuelve hallazgos."""
    e = _esp(espesador)
    df = fuente().ventana(_t(inicio), _t(fin), e)
    h = R.evaluar(df, e, solo_ids=solo_ids)
    return {"espesador": e, "n": len(h), "hallazgos": h, "texto": R.resumen_hallazgos(h)}


def comparar_periodos(espesador, inicio_a, fin_a, inicio_b, fin_b, variables=None):
    """Mediana A vs B por variable, con p-valor y piso de relevancia."""
    e = _esp(espesador)
    f = fuente()
    ta0, ta1, tb0, tb1 = _t(inicio_a), _t(fin_a), _t(inicio_b), _t(fin_b)
    da = f.ventana(ta0, ta1, e)
    db = f.ventana(tb0, tb1, e)
    # Las etiquetas llevan las fechas reales: con "A"/"B" el modelo cruza el signo.
    la = f"periodo[{ta0:%Y-%m-%d %H:%M}→{ta1:%Y-%m-%d %H:%M}]"
    lb = f"periodo[{tb0:%Y-%m-%d %H:%M}→{tb1:%Y-%m-%d %H:%M}]"
    out = E.comparar(da, db, e, variables, la, lb)
    out["nota"] = "Cada 'lectura' ya dice cuál período es mayor; cítala tal cual."
    return out


def relaciones(espesador, objetivo, inicio, fin="ahora", variables=None):
    """Correlación simple y parcial (controlando molienda) de `objetivo`
    contra las demás variables, solo con planta produciendo."""
    e = _esp(espesador)
    df = fuente().ventana(_t(inicio), _t(fin), e)
    if objetivo not in df.columns:
        raise ValueError(f"objetivo {objetivo!r} no existe; ver listar_variables")
    return E.relaciones(df, objetivo, e, variables)


def episodios(tipo, inicio, fin="ahora", espesador="planta", min_min=10, max_min=None):
    """Episodios en la ventana: 'parada_molienda' (molienda_total bajo el
    umbral de producción), 'piscina_baja' (nivel < R1), 'tren_cambio'
    (cambia el nº de trenes en servicio) o 'valvula_movida' (el operador
    movió la válvula)."""
    e = _esp(espesador)
    df = fuente().ventana(_t(inicio), _t(fin), e)
    if tipo == "parada_molienda":
        cond = df["molienda_total"] < PROCESO["tonelaje_min_produccion"]
    elif tipo == "piscina_baja":
        cond = df["nivel_piscina"] < REGLAS_PISCINAS["nivel_minimo_pct"]
    elif tipo == "tren_cambio":
        cond = df["trenes_activos"].diff().fillna(0) != 0
        min_min = 1
    elif tipo == "valvula_movida":
        if "valvula_alim" not in df:
            raise ValueError("valvula_movida requiere un espesador")
        cond = df["valvula_alim"].diff().fillna(0) != 0
        min_min = 1
    else:
        raise ValueError("tipo debe ser parada_molienda | piscina_baja | tren_cambio | valvula_movida")
    ep = detectar_episodios(cond, min_min, max_min)
    filas = []
    for _, x in ep.iterrows():
        ini, fin_, dur = x["inicio"], x["fin"], x["duracion_min"]
        fila = {"inicio": pd.Timestamp(ini).isoformat(), "fin": pd.Timestamp(fin_).isoformat(),
                "minutos": int(dur)}
        if tipo == "valvula_movida":
            fila["de"] = E._f(df["valvula_alim"].shift(1).loc[ini])
            fila["a"] = E._f(df["valvula_alim"].loc[ini])
        if tipo == "tren_cambio":
            fila["trenes"] = int(df["trenes_activos"].loc[ini])
        if tipo == "piscina_baja":
            fila["nivel_min"] = E._f(df["nivel_piscina"].loc[ini:fin_].min())
        filas.append(fila)
    return {"tipo": tipo, "espesador": e, "n": len(filas), "episodios": filas[:60],
            "pct_tiempo": E._f(100 * cond.fillna(False).mean(), 1)}


def listar_reglas():
    """Reglas de operadores vigentes."""
    return {"reglas": [{k: r.get(k) for k in ("id", "nombre", "espesador", "condicion",
                                               "duracion_min", "severidad", "activa", "autor")}
                       for r in R.cargar_reglas()],
            "variables_planta": variables_disponibles("planta"),
            "variables_espesador": variables_disponibles("TH-001")}


def proponer_regla(id, condicion, mensaje, espesador="*", duracion_min=30, severidad="media",
                   nombre=None, autor="agente"):
    """Valida y deja una regla nueva en la cola de pendientes. NO entra en
    vigor hasta que un operador la apruebe con `agente reglas aprobar`."""
    regla = R.nueva_regla(id, condicion, mensaje, espesador, duracion_min, severidad, nombre, autor)
    existentes = {r["id"] for r in R.cargar_reglas()}
    problemas = R.validar_regla(regla, existentes)
    if problemas:
        return {"aceptada": False, "problemas": problemas, "regla": regla}
    ruta = AGENTE["reglas_pendientes"]
    try:
        pendientes = R.cargar_reglas(ruta)
    except FileNotFoundError:
        pendientes = []
    pendientes = [p for p in pendientes if p["id"] != regla["id"]] + [regla]
    R.guardar_reglas(pendientes, ruta)
    return {"aceptada": True, "pendiente_en": ruta, "regla": regla,
            "nota": "Un operador debe aprobarla: pixi run agente reglas aprobar " + regla["id"]}


def buscar_tags(patron, limite=30):
    """Busca puntos en PI por patrón (p. ej. '*294100*FIT*')."""
    pi = fuente().pasarela.pi
    df = pi.search(patron)
    if df.empty:
        return {"patron": patron, "n": 0, "puntos": []}
    cols = [c for c in ("tag", "descriptor", "engunits", "pointtype", "step") if c in df.columns]
    return {"patron": patron, "n": int(len(df)), "puntos": df[cols].head(limite).to_dict("records")}


# ============================================================================
# Registro para el LLM
# ============================================================================
_FECHA = {"type": "string", "description": "Fecha-hora local 'YYYY-MM-DD HH:MM', 'ahora', relativa '-6h' / '-2d', o 'hoy 08:00' / 'ayer 06:30'"}
_ESP = {"type": "string", "description": "TH-001, TH-002, TH-003 o 'planta'"}
_VARS = {"type": "array", "items": {"type": "string"}, "description": "Roles a incluir (opcional; ver listar_variables)"}

ESQUEMAS = [
    ("cobertura", "Rango de datos disponible y estado de la pasarela PI", {}, []),
    ("listar_variables", "Variables (rol, tag PI, descripción) disponibles para un espesador o la planta",
     {"espesador": _ESP}, []),
    ("resumen", "Percentiles p10/p50/p90, mínimo, máximo, cobertura y tendencia de cada variable en una ventana",
     {"espesador": _ESP, "inicio": _FECHA, "fin": _FECHA, "variables": _VARS}, ["espesador", "inicio"]),
    ("tendencia", "Serie reducida (<=200 puntos) de UNA variable para ver su forma en el tiempo",
     {"espesador": _ESP, "variable": {"type": "string"}, "inicio": _FECHA, "fin": _FECHA},
     ["espesador", "variable", "inicio"]),
    ("anomalias", "Señales congeladas, valores atípicos y cambios de régimen (escalones) en la ventana",
     {"espesador": _ESP, "inicio": _FECHA, "fin": _FECHA,
      "minutos_congelado": {"type": "integer", "description": "minutos sin cambio para declarar congelado (60)"}},
     ["espesador", "inicio"]),
    ("evaluar_reglas", "Aplica las reglas definidas por los operadores y devuelve los hallazgos (alertas) en la ventana",
     {"espesador": _ESP, "inicio": _FECHA, "fin": _FECHA}, ["espesador", "inicio"]),
    ("comparar_periodos", "Compara la mediana de cada variable entre dos ventanas A y B con prueba de permutación",
     {"espesador": _ESP, "inicio_a": _FECHA, "fin_a": _FECHA, "inicio_b": _FECHA, "fin_b": _FECHA, "variables": _VARS},
     ["espesador", "inicio_a", "fin_a", "inicio_b", "fin_b"]),
    ("relaciones", "Correlación simple y parcial (controlando molienda) de una variable objetivo contra el resto",
     {"espesador": _ESP, "objetivo": {"type": "string"}, "inicio": _FECHA, "fin": _FECHA, "variables": _VARS},
     ["espesador", "objetivo", "inicio"]),
    ("episodios", "Episodios en la ventana: parada_molienda, piscina_baja, tren_cambio o valvula_movida",
     {"tipo": {"type": "string", "enum": ["parada_molienda", "piscina_baja", "tren_cambio", "valvula_movida"]},
      "inicio": _FECHA, "fin": _FECHA, "espesador": _ESP,
      "min_min": {"type": "integer", "description": "duración mínima en minutos"}},
     ["tipo", "inicio"]),
    ("listar_reglas", "Reglas de operadores vigentes y variables que pueden usar", {}, []),
    ("proponer_regla", "Propone una regla nueva (queda pendiente de aprobación por un operador)",
     {"id": {"type": "string"}, "condicion": {"type": "string", "description": "expresión con variables por rol, p. ej. (torque > 40) & (vel_descarga < 20)"},
      "mensaje": {"type": "string"}, "espesador": {"type": "string", "description": "'*', 'planta' o TH-00X"},
      "duracion_min": {"type": "integer"}, "severidad": {"type": "string", "enum": ["alta", "media", "baja"]},
      "nombre": {"type": "string"}},
     ["id", "condicion", "mensaje"]),
    ("buscar_tags", "Busca puntos en el historiador PI por patrón con comodines", {"patron": {"type": "string"}}, ["patron"]),
]

FUNCIONES = {n: globals()[n] for n, *_ in ESQUEMAS}


def esquemas_ollama():
    """Formato `tools` de la API de Ollama (compatible con OpenAI)."""
    out = []
    for nombre, desc, props, req in ESQUEMAS:
        out.append({"type": "function", "function": {
            "name": nombre, "description": desc,
            "parameters": {"type": "object", "properties": props, "required": req}}})
    return out


def invocar(nombre, argumentos):
    """Ejecuta una herramienta y devuelve texto JSON (o el error, como texto)."""
    fn = FUNCIONES.get(nombre)
    if fn is None:
        return json.dumps({"error": f"herramienta desconocida: {nombre}"}, ensure_ascii=False)
    try:
        args = dict(argumentos or {})
        # El modelo a veces manda 'fin': null o cadenas vacías.
        args = {k: v for k, v in args.items() if v not in (None, "")}
        res = fn(**args)
        return json.dumps(res, ensure_ascii=False, default=str)
    except Exception as e:  # noqa: BLE001 — el error vuelve al modelo como dato
        return json.dumps({"error": f"{type(e).__name__}: {e}"}, ensure_ascii=False)
