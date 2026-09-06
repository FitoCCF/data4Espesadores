"""
io_espesador.py — carga con caché parquet para las series del espesador TH-001.

Acepta CSV o parquet indistintamente. Si recibe un CSV:
  1. Busca un parquet gemelo al lado (mismo nombre, extensión .parquet)
  2. Si existe y es más nuevo que el CSV -> lo usa
  3. Si no -> convierte, guarda, y usa el resultado

Además hace la higiene mínima que el historian no garantiza:
  - índice temporal ordenado
  - timestamps duplicados eliminados (los exports de PI suelen traerlos)
  - float32 (mitad de RAM; la precisión de un transmisor de campo no justifica
    float64 — son ~3-4 dígitos significativos reales)

Uso:
    from io_espesador import cargar_datos
    d, info = cargar_datos("Data_Esp1_20260714_0921.csv")
"""

import io
from pathlib import Path

import pandas as pd


TAGS_ESPERADOS = [
    "x1", "x2", "x3", "x4", "x5", "x6", "x7", "x8", "x9", "x10",
    "y1", "y2", "y3", "y4", "y5", "y6", "y7", "y8",
]


def _leer_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    num = df.select_dtypes("number").columns
    df[num] = df[num].astype("float32")
    return df


# ----------------------------------------------------------------------------
# Caché: parquet si el entorno lo soporta, pickle si no.
#
# pandas trae un hotfix (CVE-2023-47248) que intenta desregistrar el tipo
# 'arrow.py_extension_type'. Con pandas viejo + pyarrow nuevo ese tipo ya no
# existe y el hotfix revienta con ArrowKeyError.
#
# El caché es una OPTIMIZACIÓN, no un requisito. Nunca debe tumbar el pipeline.
# Si parquet no está disponible, se usa pickle: nativo, rápido, sin dependencias.
# (Contrapartida: el pickle no es portable entre versiones de pandas. Para un
# caché local es aceptable; para intercambiar datos, no.)
# ----------------------------------------------------------------------------

def _motor_cache() -> str:
    """Devuelve 'parquet' o 'pickle' según lo que el entorno soporte de verdad."""
    try:
        pd.DataFrame({"a": [1.0]}).to_parquet(io.BytesIO())
        return "parquet"
    except Exception:
        return "pickle"


def _ruta_cache(p: Path, motor: str) -> Path:
    return p.with_suffix(".parquet" if motor == "parquet" else ".pkl")


def _escribir_cache(df: pd.DataFrame, ruta: Path, motor: str) -> None:
    if motor == "parquet":
        df.to_parquet(ruta, compression="snappy")
    else:
        df.to_pickle(ruta, compression="infer")


def _leer_cache(ruta: Path, motor: str) -> pd.DataFrame:
    return pd.read_parquet(ruta) if motor == "parquet" else pd.read_pickle(ruta)


def _higiene(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    rep = {"filas_leidas": len(df)}

    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)

    df = df.sort_index()

    dup = df.index.duplicated(keep="first")
    rep["timestamps_duplicados"] = int(dup.sum())
    df = df.loc[~dup]

    rep["filas_finales"] = len(df)
    rep["rango"] = f"{df.index.min()} -> {df.index.max()}"
    rep["dias"] = round((df.index.max() - df.index.min()).total_seconds() / 86400, 1)

    paso = pd.Series(df.index).diff().median()
    rep["paso_min"] = max(1, int(round(paso.total_seconds() / 60)))

    # huecos: el historian puede haber estado caído
    esperadas = int((df.index.max() - df.index.min()).total_seconds() / 60 / rep["paso_min"]) + 1
    rep["cobertura_%"] = round(100 * len(df) / esperadas, 1)

    rep["ram_mb"] = round(df.memory_usage(deep=True).sum() / 1e6, 1)

    faltantes = [t for t in TAGS_ESPERADOS if t not in df.columns]
    extras = [c for c in df.columns if c not in TAGS_ESPERADOS]
    if faltantes:
        rep["TAGS_FALTANTES"] = faltantes
    if extras:
        rep["TAGS_NUEVOS"] = extras   # <-- ojo: ¿llegó el turbidímetro?

    return df, rep


def cargar_datos(path, forzar_reconversion: bool = False, verbose: bool = True):
    """Devuelve (DataFrame, dict con el reporte de carga)."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"No existe: {p.resolve()}\n"
            f"CSVs en {p.parent.resolve()}: "
            f"{sorted(x.name for x in p.parent.glob('*.csv'))}"
        )

    if p.suffix.lower() in (".parquet", ".pkl"):
        motor = "parquet" if p.suffix.lower() == ".parquet" else "pickle"
        df = _leer_cache(p, motor)
        origen = f"{motor} (directo)"
    else:
        motor = _motor_cache()
        cache = _ruta_cache(p, motor)
        usar_cache = (
            cache.exists()
            and not forzar_reconversion
            and cache.stat().st_mtime >= p.stat().st_mtime
        )
        if usar_cache:
            df = _leer_cache(cache, motor)
            origen = f"cache {motor}: {cache.name}"
        else:
            df = _leer_csv(p)
            df, _ = _higiene(df)
            try:
                _escribir_cache(df, cache, motor)
                origen = f"CSV convertido -> {cache.name}"
                if verbose:
                    mb_csv = p.stat().st_size / 1e6
                    mb_ca = cache.stat().st_size / 1e6
                    print(f"  cache ({motor}): {mb_csv:.0f} MB CSV -> {mb_ca:.0f} MB "
                          f"({mb_csv / max(mb_ca, 0.01):.1f}x mas compacto)")
            except Exception as e:
                origen = f"CSV directo (cache deshabilitado: {type(e).__name__})"
                if verbose:
                    print(f"  AVISO: no se pudo escribir cache -> {e}")
                    print("  El analisis sigue igual, solo sera mas lento al recargar.")

        if verbose and motor == "pickle" and not usar_cache:
            print("  NOTA: parquet no disponible en este entorno (choque")
            print("        pandas/pyarrow). Usando pickle como cache local.")
            print("        Para arreglarlo:  pixi add \"pandas>=2.2.3\"")

    df, rep = _higiene(df)
    rep["origen"] = origen

    if verbose:
        print("=" * 72)
        print("CARGA DE DATOS")
        print("=" * 72)
        for k, v in rep.items():
            marca = ""
            if k == "TAGS_NUEVOS":
                marca = "   <-- REVISAR: tags nuevos en el export"
            if k == "TAGS_FALTANTES":
                marca = "   <-- el analisis va a fallar"
            if k == "cobertura_%" and isinstance(v, float) and v < 95:
                marca = "   <-- huecos en el historian"
            print(f"  {k}: {v}{marca}")

    return df, rep


if __name__ == "__main__":
    import sys
    en_nb = "ipykernel" in sys.modules
    p = ("Data_Esp1_20260714_0921.csv"
         if en_nb or len(sys.argv) < 2 or sys.argv[1].startswith("-")
         else sys.argv[1])
    cargar_datos(p)
