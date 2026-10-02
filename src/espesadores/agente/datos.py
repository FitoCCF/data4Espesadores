# -*- coding: utf-8 -*-
"""
datos.py — fuente de datos del agente offline.

Entrega una ventana [inicio, fin) a grilla de 1 min con columnas nombradas
por ROL (flujo_alim, valvula_alim, nivel_piscina, ...) para un espesador, y
decide de dónde sacarla:

  1. Parquet canónico del pipeline (rutas.entrada) si la ventana ya está
     cubierta — 2024-07-14 -> 2026-09-15, sin volver a pedir nada a PI.
  2. Caché local por día (data/03_cache_agente/YYYY-MM-DD.parquet) para lo
     que ya se bajó en consultas anteriores.
  3. Pasarela PiGateway (método `recorded`, dato crudo archivado) para lo
     que falte, reconstruido a grilla con ZOH para tags `step` y NaN donde
     el hueco supera 1.5 x compmax — la misma regla de pi_tool.py.

Principios que hereda del proyecto: no rellena, no interpola consignas, y
una consulta nunca excede `max_dias_por_consulta` (el OOM de PROGRESO.md
§2.3 no se repite desde el agente).
"""
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from espesadores.config import (AGENTE, ESPESADORES, GLOBALES, PISCINAS_TAGS,
                                PROCESO, RUTAS, TAGS_DIGITALES,
                                TAGS_EXTRACCION_PI)
from espesadores.dominio.piscinas import derivar_nivel

_CFG = AGENTE["datos"]
TZ = _CFG["zona_horaria"]

# Columna -> tag PI y viceversa, desde la lista maestra de tags.yaml.
COLUMNA_A_TAG = {col: tag for tag, col, _g, _d in TAGS_EXTRACCION_PI}
TAG_A_COLUMNA = {tag: col for tag, col, _g, _d in TAGS_EXTRACCION_PI}
DESCRIPCION = {col: d for _t, col, _g, d in TAGS_EXTRACCION_PI}

# Roles de planta (comunes a los tres espesadores) -> columna del dataset.
# Los nombres son los que ven las reglas de operadores y el LLM.
ROLES_PLANTA = {
    "flujo_piscinas": "FIT_114",
    "tk001": "LIT_108",
    "tk002": "LIT_109",
    "agua_fresca": "FIT_123",
    "agua_qh": "FIT_601",
    "ley_rougher": GLOBALES["ley_rougher"],
    "ratio_cu": GLOBALES["ratio_cu"],
}
for _i, _m in enumerate(GLOBALES["molinos"], 1):
    ROLES_PLANTA[f"molino_{_i}"] = _m

# Roles por espesador que son una columna directa de tags.yaml.
ROLES_ESPESADOR_DIRECTOS = ["flujo_alim", "presion_cama", "torque", "nivel_interfaz",
                            "nivel_cajon", "valvula_alim", "floculante", "agua_dilucion"]
# Roles derivados (no son un tag): se calculan en `enriquecer`.
ROLES_DERIVADOS = ["vel_descarga", "vel_cizalle", "wt_activo", "dit_activo",
                   "trenes_activos", "nivel_piscina", "molienda_total"]


def log(msg):
    print(msg, flush=True)


# ============================================================================
# Roles <-> columnas
# ============================================================================
def columnas_de(espesador):
    """{rol: columna} de todo lo que ve una regla o el LLM para `espesador`.

    `espesador` puede ser 'planta' (solo roles comunes) o TH-00X.
    """
    roles = dict(ROLES_PLANTA)
    roles["piscina_a"] = PISCINAS_TAGS["transmisor_a"]
    roles["piscina_b"] = PISCINAS_TAGS["transmisor_b"]
    if espesador and espesador != "planta":
        cfg = ESPESADORES[espesador]
        for rol in ROLES_ESPESADOR_DIRECTOS:
            roles[rol] = cfg[rol]
        for i, tren in enumerate(cfg["trenes"], 1):
            roles[f"descarga_tren{i}"] = tren["descarga"]
            roles[f"cizalle_tren{i}"] = tren["cizalle"]
            roles[f"wt_tren{i}"] = tren["wt"]
            roles[f"dit_tren{i}"] = tren["dit"]
    return roles


def describir_roles(espesador):
    """[(rol, columna, tag_pi, descripcion)] para mostrar al operador / LLM."""
    out = []
    for rol, col in columnas_de(espesador).items():
        out.append((rol, col, COLUMNA_A_TAG.get(col, ""), DESCRIPCION.get(col, "")))
    for rol in ROLES_DERIVADOS:
        out.append((rol, "(derivado)", "", _DESC_DERIVADOS[rol]))
    return out


_DESC_DERIVADOS = {
    "vel_descarga": "Velocidad de la bomba de descarga del tren en servicio (regla E04)",
    "vel_cizalle": "Velocidad de la bomba de cizalla del tren en servicio",
    "wt_activo": "%sólidos de descarga del tren en servicio",
    "dit_activo": "Densidad de descarga del tren en servicio",
    "trenes_activos": "Nº de trenes con bomba de descarga sobre el umbral",
    "nivel_piscina": "Nivel de piscina derivado de LIT_106/LIT_107 (regla de piscinas.py)",
    "molienda_total": "Suma del tonelaje de los molinos (PB01 + PB02)",
}


# ============================================================================
# Fuente 1: parquet canónico
# ============================================================================
class _Parquet:
    def __init__(self, ruta):
        self.ruta = ruta
        self.t_min = self.t_max = None
        if ruta and os.path.exists(ruta):
            import pyarrow.parquet as pq
            md = pq.read_metadata(ruta)
            # Solo hace falta el índice para conocer la cobertura.
            idx = pd.read_parquet(ruta, columns=[]).index
            self.t_min = idx.min().tz_convert(TZ)
            self.t_max = idx.max().tz_convert(TZ)
            self.filas = md.num_rows

    def cubre(self, t0, t1):
        return self.t_min is not None and t0 >= self.t_min and t1 <= self.t_max + pd.Timedelta(minutes=1)

    def leer(self, t0, t1, columnas):
        import pyarrow.parquet as pq
        import pyarrow.compute as pc
        nombres = pq.read_schema(self.ruta).names
        cols = [c for c in columnas if c in nombres]
        # El índice se guardó como columna `timestamp`; al pedir columnas
        # explícitas hay que incluirla para que vuelva como índice.
        tabla = pq.read_table(self.ruta, columns=["timestamp"] + cols,
                              filters=[("timestamp", ">=", t0.tz_convert("UTC")),
                                       ("timestamp", "<", t1.tz_convert("UTC"))])
        df = tabla.to_pandas()
        if "timestamp" in df.columns:
            df = df.set_index("timestamp")
        df.index = df.index.tz_convert(TZ)
        return df


# ============================================================================
# Fuente 2: caché por día
# ============================================================================
class _Cache:
    def __init__(self, carpeta):
        self.carpeta = Path(carpeta)
        self.carpeta.mkdir(parents=True, exist_ok=True)

    def _ruta(self, dia):
        return self.carpeta / f"{dia:%Y-%m-%d}.parquet"

    def dias_faltantes(self, t0, t1):
        dias = pd.date_range(t0.normalize(), (t1 - pd.Timedelta(minutes=1)).normalize(), freq="D")
        return [d for d in dias if not self._ruta(d).exists()]

    def leer(self, t0, t1, columnas):
        partes = []
        for d in pd.date_range(t0.normalize(), (t1 - pd.Timedelta(minutes=1)).normalize(), freq="D"):
            r = self._ruta(d)
            if r.exists():
                partes.append(pd.read_parquet(r))
        if not partes:
            return pd.DataFrame()
        df = pd.concat(partes).sort_index()
        df = df[(df.index >= t0) & (df.index < t1)]
        cols = [c for c in columnas if c in df.columns]
        return df[cols]

    def guardar(self, df, completo_hasta):
        """Guarda por día. Un día se escribe solo si quedó completo (1440
        filas) o si su último instante es anterior a `completo_hasta`; el
        día en curso no se cachea para no fijar una versión parcial."""
        for d, g in df.groupby(df.index.normalize()):
            fin_dia = d + pd.Timedelta(days=1)
            if fin_dia <= completo_hasta:
                g.to_parquet(self._ruta(d))


# ============================================================================
# Fuente 3: pasarela PiGateway
# ============================================================================
def _importar_pi_client():
    carpeta = os.environ.get("PI_CLIENT_DIR") or _CFG["pi_client_dir"]
    carpeta = os.path.expanduser(carpeta)
    if carpeta not in sys.path:
        sys.path.insert(0, carpeta)
    try:
        from pi_client import PiGateway  # noqa: E402
    except ImportError as e:
        raise RuntimeError(
            f"No se encontró pi_client.py en {carpeta}. Ajustar datos.pi_client_dir "
            "en conf/base/agente.yaml o la variable PI_CLIENT_DIR.") from e
    return PiGateway


class _Pasarela:
    def __init__(self):
        self._pi = None
        self._attr = None

    @property
    def pi(self):
        if self._pi is None:
            PiGateway = _importar_pi_client()
            self._pi = PiGateway(zona_local=TZ, verbose=False)
        return self._pi

    def disponible(self):
        try:
            return bool(self.pi.health().get("ok"))
        except Exception:
            return False

    def atributos(self, tags):
        """step / compmax por tag, cacheado en memoria para la sesión."""
        if self._attr is None:
            self._attr = {}
        faltan = [t for t in tags if t not in self._attr]
        if faltan:
            df = self.pi.attributes(faltan, ["step", "compmax"])
            for _, fila in df.iterrows():
                self._attr[fila["tag"]] = {
                    "step": str(fila.get("step", "")).strip().lower() in ("1", "true", "yes", "on"),
                    "compmax": _float_o_none(fila.get("compmax")),
                }
            for t in faltan:
                self._attr.setdefault(t, {"step": False, "compmax": None})
        return self._attr

    def ventana(self, t0, t1, columnas, freq):
        """Eventos crudos -> grilla ancha por columna del dataset."""
        tags = [COLUMNA_A_TAG[c] for c in columnas if c in COLUMNA_A_TAG]
        largo = self.pi.recorded(tags, t0.strftime("%Y-%m-%d %H:%M:%S"),
                                 t1.strftime("%Y-%m-%d %H:%M:%S"),
                                 chunk_dias=_CFG["chunk_dias"])
        grilla = pd.date_range(t0, t1, freq=freq, inclusive="left")
        out = pd.DataFrame(index=grilla)
        out.index.name = "timestamp"
        if largo.empty:
            for c in columnas:
                out[c] = np.nan
            return out
        attrs = self.atributos(tags)
        largo["value"] = pd.to_numeric(largo["value"], errors="coerce")
        largo = largo[largo["good"].fillna(True).astype(bool)]
        for tag, g in largo.groupby("tag"):
            col = TAG_A_COLUMNA[tag]
            out[col] = _a_grilla(g, grilla, attrs[tag])
        for c in columnas:
            if c not in out.columns:
                out[c] = np.nan
        return out[columnas]


def _float_o_none(v):
    try:
        f = float(v)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def _a_grilla(g, grilla, attr):
    """Copia de ReconstructorGrilla.reconstruir (pi_tool.py) para un tag:
    ZOH si es step, lineal si es continuo, NaN si el hueco supera 1.5 compmax."""
    s = g.set_index("t")["value"].sort_index()
    s = s[~s.index.duplicated(keep="last")]
    if s.index.tz is None:
        s.index = s.index.tz_localize(TZ)
    else:
        s.index = s.index.tz_convert(TZ)
    union = s.index.union(grilla)
    if attr["step"]:
        v = s.reindex(union).ffill().reindex(grilla)
    else:
        v = s.reindex(union).interpolate(method="time", limit_area="inside").reindex(grilla)
    ult = pd.Series(s.index, index=s.index).reindex(union).ffill().reindex(grilla)
    edad_s = (pd.Series(grilla, index=grilla) - pd.to_datetime(ult)).dt.total_seconds()
    if attr["compmax"]:
        v = v.where(edad_s <= attr["compmax"] * 1.5)
    return v


# ============================================================================
# Fachada
# ============================================================================
class FuenteDatos:
    # Segundos que se reutiliza en memoria el día en curso (no cacheable en
    # disco): evita pedirlo a PI en cada herramienta de una misma pregunta.
    REUSO_DIA_EN_CURSO_S = 120

    def __init__(self):
        self.parquet = _Parquet(RUTAS["entrada"])
        self.cache = _Cache(_CFG["cache"])
        self.pasarela = _Pasarela()
        self.freq = _CFG["grilla"]
        self._reciente = None   # (instante de bajada, DataFrame del día en curso)

    # -------------------------------------------------------------- tiempo
    @staticmethod
    def ts(valor):
        """Texto o Timestamp -> Timestamp con zona America/Lima."""
        t = pd.Timestamp(valor)
        return t.tz_localize(TZ) if t.tz is None else t.tz_convert(TZ)

    def ahora(self):
        return pd.Timestamp.now(tz=TZ).floor("min")

    def cobertura(self):
        return {"parquet_desde": str(self.parquet.t_min), "parquet_hasta": str(self.parquet.t_max),
                "parquet_filas": getattr(self.parquet, "filas", 0),
                "pasarela": self.pasarela.disponible()}

    # -------------------------------------------------------------- lectura
    def ventana(self, inicio, fin, espesador=None, columnas=None):
        """DataFrame a grilla de 1 min con las columnas pedidas (o todas las
        del espesador + planta), ya enriquecido con los roles derivados."""
        t0, t1 = self.ts(inicio), self.ts(fin)
        if t1 <= t0:
            raise ValueError(f"Rango vacío: {t0} -> {t1}")
        max_d = _CFG["max_dias_por_consulta"]
        if (t1 - t0) > pd.Timedelta(days=max_d):
            raise ValueError(f"La consulta pide {(t1 - t0).days} días; el máximo por consulta es "
                             f"{max_d} (datos.max_dias_por_consulta). Partir el rango.")
        roles = columnas_de(espesador)
        if columnas is None:
            cols = sorted(set(roles.values()))
        else:
            cols = sorted(set(columnas))

        partes = []
        if self.parquet.t_min is not None and t0 < self.parquet.t_max:
            fin_pq = min(t1, self.parquet.t_max + pd.Timedelta(minutes=1))
            partes.append(self.parquet.leer(t0, fin_pq, cols))
            t0_resto = fin_pq
        else:
            t0_resto = t0
        if t0_resto < t1:
            partes.append(self._leer_reciente(t0_resto, t1, cols))

        df = pd.concat([p for p in partes if p is not None and not p.empty]).sort_index() if partes else pd.DataFrame()
        grilla = pd.date_range(t0, t1, freq=self.freq, inclusive="left")
        df = df.reindex(grilla)
        df.index.name = "timestamp"
        for c in cols:
            if c not in df.columns:
                df[c] = np.nan
        return enriquecer(df, espesador)

    def _leer_reciente(self, t0, t1, cols):
        faltan = self.cache.dias_faltantes(t0, t1)
        ahora = self.ahora()
        if faltan and self._reciente is not None:
            t_baj, df_rec = self._reciente
            if (ahora - t_baj).total_seconds() < self.REUSO_DIA_EN_CURSO_S and t1 <= t_baj + pd.Timedelta(minutes=1):
                # Solo falta el día en curso y ya se bajó hace un instante.
                if all(d >= df_rec.index[0].normalize() for d in faltan):
                    en_cache = self.cache.leer(t0, t1, cols)
                    rec = df_rec[(df_rec.index >= t0) & (df_rec.index < t1)][[c for c in cols if c in df_rec.columns]]
                    return en_cache.combine_first(rec) if not en_cache.empty else rec
        if faltan:
            if not self.pasarela.disponible():
                raise RuntimeError("La pasarela PiGateway no responde y la ventana pedida no está "
                                   "en el parquet ni en la caché. Levantarla en Windows o acotar el rango.")
            # Se bajan TODAS las columnas conocidas para que la caché sirva a
            # cualquier consulta posterior, no solo a la actual.
            todas = sorted(set(COLUMNA_A_TAG))
            d0 = min(faltan)
            d1 = min(max(faltan) + pd.Timedelta(days=1), ahora)
            log(f"  [PI] bajando {d0:%Y-%m-%d} -> {d1:%Y-%m-%d %H:%M} ({len(todas)} tags)")
            bajado = self.pasarela.ventana(d0, d1, todas, self.freq)
            self.cache.guardar(bajado, completo_hasta=ahora)
            dia_en_curso = bajado[bajado.index >= ahora.normalize()]
            self._reciente = (ahora, dia_en_curso) if not dia_en_curso.empty else None
            reciente = bajado[(bajado.index >= t0) & (bajado.index < t1)]
            en_cache = self.cache.leer(t0, t1, cols)
            df = reciente[[c for c in cols if c in reciente.columns]]
            if not en_cache.empty:
                df = en_cache.combine_first(df)
            return df
        return self.cache.leer(t0, t1, cols)


# ============================================================================
# Señales derivadas (misma regla que dominio/atoro_alimentacion.senales_activas
# y dominio/piscinas.derivar_nivel)
# ============================================================================
def enriquecer(df, espesador=None):
    """Agrega columnas por ROL al DataFrame de columnas crudas."""
    df = df.copy()
    roles = columnas_de(espesador)
    for rol, col in roles.items():
        if col in df.columns and rol not in df.columns:
            df[rol] = df[col]

    molinos = [m for m in GLOBALES["molinos"] if m in df.columns]
    df["molienda_total"] = df[molinos].sum(axis=1, min_count=1) if molinos else np.nan

    a, b = PISCINAS_TAGS["transmisor_a"], PISCINAS_TAGS["transmisor_b"]
    if a in df.columns and b in df.columns:
        df["nivel_piscina"] = derivar_nivel(df)["nivel_piscina"]
    else:
        df["nivel_piscina"] = np.nan

    for c in ("vel_descarga", "vel_cizalle", "wt_activo", "dit_activo"):
        df[c] = np.nan
    df["trenes_activos"] = 0
    if espesador and espesador != "planta":
        umbral = PROCESO["umbral_bomba_on"]
        asignado = pd.Series(False, index=df.index)
        for tren in ESPESADORES[espesador]["trenes"]:
            if tren["descarga"] not in df.columns:
                continue
            on = df[tren["descarga"]] > umbral
            df["trenes_activos"] += on.astype(int)
            activo = on & ~asignado
            df.loc[activo, "vel_descarga"] = df.loc[activo, tren["descarga"]]
            for rol, campo in (("vel_cizalle", "cizalle"), ("wt_activo", "wt"), ("dit_activo", "dit")):
                if tren[campo] in df.columns:
                    df.loc[activo, rol] = df.loc[activo, tren[campo]]
            asignado |= activo
    return df


def variables_disponibles(espesador):
    """Nombres de rol que una regla puede usar para `espesador`."""
    return sorted(set(columnas_de(espesador)) | set(ROLES_DERIVADOS))
