# -*- coding: utf-8 -*-
"""
reglas.py — motor de reglas declaradas por operadores.

Una regla (conf/base/reglas_operadores.yaml) es una expresión sobre
variables por ROL evaluada minuto a minuto en la ventana de datos. La
expresión se evalúa con `eval` sobre un espacio de nombres cerrado: solo
Series del DataFrame, las funciones de abajo y unos pocos builtins; no hay
acceso a módulos ni a atributos dunder. Los operadores son personal de
confianza y el archivo vive en el repo, pero igual se rechaza cualquier
expresión con `__`, `import` o `lambda`.

Cuando la condición es True de forma continua `duracion_min` minutos, se
emite un hallazgo. Un hallazgo trae el instante de inicio, la duración y
los valores de las variables al inicio (para el `mensaje`).
"""
import re
from datetime import datetime

import numpy as np
import pandas as pd
import yaml

from espesadores.config import AGENTE, ESPESADORES
from espesadores.agente.datos import variables_disponibles

SEVERIDADES = ("alta", "media", "baja")
CAMPOS_OBLIGATORIOS = ("id", "condicion", "duracion_min", "severidad", "mensaje")
_PROHIBIDO = re.compile(r"__|\bimport\b|\blambda\b|\bexec\b|\beval\b|\bopen\b")


# ============================================================================
# Funciones disponibles en las expresiones
# ============================================================================
def _nombre(x):
    return getattr(x, "name", "x") or "x"


class _Funciones:
    """Las funciones registran sus resultados en `derivadas` para que el
    mensaje pueda citarlos (p. ej. {pendiente_nivel_piscina_2h})."""

    def __init__(self, df):
        self.df = df
        self.derivadas = {}

    def _guardar(self, prefijo, x, ventana, s):
        clave = f"{prefijo}_{_nombre(x)}_{str(ventana).replace('min', 'min')}"
        s.name = clave
        self.derivadas[clave] = s
        return s

    def media(self, x, ventana):
        return self._guardar("media", x, ventana, x.rolling(ventana, min_periods=1).mean())

    def mediana(self, x, ventana):
        return self._guardar("mediana", x, ventana, x.rolling(ventana, min_periods=1).median())

    def minimo(self, x, ventana):
        return self._guardar("minimo", x, ventana, x.rolling(ventana, min_periods=1).min())

    def maximo(self, x, ventana):
        return self._guardar("maximo", x, ventana, x.rolling(ventana, min_periods=1).max())

    def delta(self, x, ventana):
        n = int(pd.Timedelta(ventana) / pd.Timedelta(minutes=1))
        return self._guardar("delta", x, ventana, x - x.shift(n))

    def pendiente(self, x, ventana):
        """Cambio por hora: (x(t) - x(t - ventana)) / horas. Robusto y barato;
        no es una regresión, pero para una regla de operador basta."""
        n = int(pd.Timedelta(ventana) / pd.Timedelta(minutes=1))
        horas = n / 60.0
        return self._guardar("pendiente", x, ventana, (x - x.shift(n)) / horas)

    def congelado(self, x, ventana):
        n = int(pd.Timedelta(ventana) / pd.Timedelta(minutes=1))
        sin_cambio = (x.diff() == 0)
        s = sin_cambio.rolling(n, min_periods=n).sum() == n
        return self._guardar("congelado", x, ventana, s)

    def hora_entre(self, desde, hasta):
        h = self.df.index.hour * 60 + self.df.index.minute
        d = _hhmm(desde)
        f = _hhmm(hasta)
        if d <= f:
            s = pd.Series((h >= d) & (h < f), index=self.df.index)
        else:  # cruza medianoche
            s = pd.Series((h >= d) | (h < f), index=self.df.index)
        s.name = f"hora_entre_{desde}_{hasta}"
        return s

    def espacio(self):
        return {
            "media": self.media, "mediana": self.mediana, "minimo": self.minimo,
            "maximo": self.maximo, "delta": self.delta, "pendiente": self.pendiente,
            "congelado": self.congelado, "hora_entre": self.hora_entre,
            "abs": np.abs, "min": np.minimum, "max": np.maximum,
            "True": True, "False": False, "nan": np.nan,
        }


def _hhmm(txt):
    h, m = str(txt).split(":")
    return int(h) * 60 + int(m)


# ============================================================================
# Carga y validación
# ============================================================================
def cargar_reglas(ruta=None):
    ruta = ruta or AGENTE["reglas_operadores"]
    with open(ruta, encoding="utf-8") as f:
        doc = yaml.safe_load(f) or {}
    return [r for r in (doc.get("reglas") or [])]


def guardar_reglas(reglas, ruta):
    """Reescribe la lista de reglas de `ruta` manteniendo el encabezado
    comentado (todo lo que precede a la clave `reglas:`)."""
    encabezado = ""
    try:
        with open(ruta, encoding="utf-8") as f:
            texto = f.read()
        pos = texto.find("\nreglas:")
        encabezado = texto[:pos + 1] if pos >= 0 else ""
    except FileNotFoundError:
        pass
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(encabezado)
        yaml.safe_dump({"reglas": reglas}, f, allow_unicode=True, sort_keys=False, width=120)


def espesadores_de(regla):
    e = regla.get("espesador", "*")
    if e in (None, "*", "todos"):
        return list(ESPESADORES)
    if e == "planta":
        return ["planta"]
    if e not in ESPESADORES:
        raise ValueError(f"Regla {regla.get('id')}: espesador desconocido {e!r}")
    return [e]


def validar_regla(regla, existentes=()):
    """Lista de problemas (vacía si la regla es válida). Compila la
    expresión contra un DataFrame sintético para detectar nombres
    desconocidos y errores de sintaxis sin tocar datos reales."""
    problemas = []
    for c in CAMPOS_OBLIGATORIOS:
        if c not in regla or regla[c] in (None, ""):
            problemas.append(f"falta el campo '{c}'")
    if problemas:
        return problemas
    if regla["id"] in existentes:
        problemas.append(f"id duplicado: {regla['id']}")
    if not re.fullmatch(r"[a-zA-Z0-9_]+", str(regla["id"])):
        problemas.append("id solo admite letras, números y guion bajo")
    if regla["severidad"] not in SEVERIDADES:
        problemas.append(f"severidad debe ser una de {SEVERIDADES}")
    try:
        if int(regla["duracion_min"]) < 1:
            problemas.append("duracion_min debe ser >= 1")
    except (TypeError, ValueError):
        problemas.append("duracion_min debe ser entero (minutos)")
    if _PROHIBIDO.search(str(regla["condicion"])):
        problemas.append("la condición contiene una construcción no permitida")
    try:
        esps = espesadores_de(regla)
    except ValueError as e:
        problemas.append(str(e))
        return problemas
    for esp in esps:
        df = _df_sintetico(esp)
        try:
            _cond, derivadas = evaluar_condicion(regla["condicion"], df)
        except Exception as e:  # noqa: BLE001 — se reporta el error tal cual
            problemas.append(f"[{esp}] la condición no evalúa: {type(e).__name__}: {e}")
            return problemas
        try:
            deriv = {k: float(s.iloc[-1]) for k, s in derivadas.items()}
            formatear_mensaje(regla["mensaje"], df.iloc[-1].to_dict(), 0, deriv)
        except (KeyError, ValueError) as e:
            problemas.append(f"el mensaje cita una variable desconocida o formato inválido: {e}")
            return problemas
    return problemas


def _df_sintetico(espesador):
    idx = pd.date_range("2026-01-01", periods=24 * 60, freq="min", tz="America/Lima")
    rng = np.random.default_rng(0)
    return pd.DataFrame({v: rng.normal(50, 5, len(idx)) for v in variables_disponibles(espesador)},
                        index=idx)


# ============================================================================
# Evaluación
# ============================================================================
def evaluar_condicion(condicion, df):
    """Series booleana con el mismo índice de df, más las series derivadas."""
    if _PROHIBIDO.search(condicion):
        raise ValueError("condición con construcción no permitida")
    fn = _Funciones(df)
    espacio = {c: df[c] for c in df.columns}
    espacio.update(fn.espacio())
    resultado = eval(compile(condicion, "<regla>", "eval"), {"__builtins__": {}}, espacio)  # noqa: S307
    if isinstance(resultado, (bool, np.bool_)):
        resultado = pd.Series(bool(resultado), index=df.index)
    if not isinstance(resultado, pd.Series):
        raise TypeError("la condición debe producir una Series booleana")
    return resultado.fillna(False).astype(bool), fn.derivadas


def episodios_de(cond, duracion_min):
    """[(inicio, fin, minutos)] de los tramos True contiguos de al menos
    `duracion_min` minutos."""
    if not cond.any():
        return []
    cambio = cond.ne(cond.shift(fill_value=False))
    grupo = cambio.cumsum()
    out = []
    for _, g in cond[cond].groupby(grupo[cond]):
        minutos = len(g)
        if minutos >= duracion_min:
            out.append((g.index[0], g.index[-1] + pd.Timedelta(minutes=1), minutos))
    return out


class _Seguro(dict):
    def __missing__(self, k):
        raise KeyError(k)


def formatear_mensaje(plantilla, valores, duracion_min, derivadas):
    ns = _Seguro()
    for k, v in valores.items():
        ns[k] = v
    for k, v in derivadas.items():
        ns[k] = v
    ns["duracion_min"] = duracion_min
    try:
        return plantilla.format_map(ns)
    except (ValueError, TypeError):
        # Un NaN con formato ':.0f' no falla, pero un None sí: se degrada a texto.
        return plantilla.format_map(_Seguro({k: (v if isinstance(v, (int, float)) else str(v))
                                             for k, v in ns.items()}))


def evaluar(df, espesador, reglas=None, solo_ids=None):
    """Aplica las reglas que correspondan a `espesador` sobre `df` (ya
    enriquecido). Devuelve una lista de hallazgos (dicts)."""
    reglas = reglas if reglas is not None else cargar_reglas()
    hallazgos = []
    for r in reglas:
        if r.get("activa", True) is False:
            continue
        if solo_ids and r["id"] not in solo_ids:
            continue
        if espesador not in espesadores_de(r):
            continue
        try:
            cond, derivadas = evaluar_condicion(r["condicion"], df)
        except Exception as e:  # noqa: BLE001
            hallazgos.append({"regla": r["id"], "espesador": espesador, "error": f"{type(e).__name__}: {e}"})
            continue
        for ini, fin, minutos in episodios_de(cond, int(r["duracion_min"])):
            fila = df.loc[ini]
            valores = {k: (float(v) if isinstance(v, (int, float, np.floating, np.integer)) else v)
                       for k, v in fila.items()}
            deriv = {k: float(s.loc[ini]) for k, s in derivadas.items() if pd.notna(s.loc[ini])}
            hallazgos.append({
                "regla": r["id"], "nombre": r.get("nombre", r["id"]),
                "espesador": espesador, "severidad": r["severidad"],
                "inicio": ini.isoformat(), "fin": fin.isoformat(), "minutos": int(minutos),
                "abierto": bool(fin >= df.index[-1]),
                "mensaje": formatear_mensaje(r["mensaje"], valores, minutos, deriv),
            })
    return hallazgos


def resumen_hallazgos(hallazgos):
    """Texto compacto para consola / LLM."""
    if not hallazgos:
        return "Sin hallazgos de reglas en la ventana."
    orden = {s: i for i, s in enumerate(SEVERIDADES)}
    lineas = []
    for h in sorted(hallazgos, key=lambda h: (orden.get(h.get("severidad"), 9), h.get("inicio", ""))):
        if "error" in h:
            lineas.append(f"[ERROR] {h['regla']} ({h['espesador']}): {h['error']}")
            continue
        estado = " (en curso)" if h["abierto"] else ""
        lineas.append(f"[{h['severidad'].upper()}] {h['espesador']} {h['inicio'][:16]} "
                      f"+{h['minutos']} min{estado} · {h['nombre']}: {h['mensaje']}")
    return "\n".join(lineas)


def nueva_regla(id_, condicion, mensaje, espesador="*", duracion_min=30, severidad="media",
                nombre=None, autor="operador"):
    return {"id": id_, "nombre": nombre or id_, "espesador": espesador, "condicion": condicion,
            "duracion_min": int(duracion_min), "severidad": severidad, "mensaje": mensaje,
            "autor": autor, "creada": datetime.now().strftime("%Y-%m-%d %H:%M")}
