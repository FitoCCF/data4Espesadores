# ============================================================
# src/acquisition/database.py — conexión y consultas a Postgres
# ============================================================
# Portado desde data2TesisV2 (src/database/{connection,extractor}.py) a un
# solo módulo, para que `acquisition` sea autocontenido en este repo: mismas
# queries y mismo esquema, sin importar nada de aquel proyecto.
#
# Lee la tabla `works4cdp_assay`, que llena otro proceso (api2db.py en
# data4cdpv1_local) a partir de la API HTTP local del analizador (CLB). Este
# módulo SOLO lee.
#
# sqlalchemy y el driver de Postgres se importan de forma perezosa, dentro de
# DBManager: así `import acquisition` y la ruta de PI (from_pi.py) siguen
# funcionando en una máquina sin esas dependencias instaladas.
#
# Credenciales por variables de entorno (DB_USER, DB_PASSWORD, DB_HOST,
# DB_PORT, DB_NAME); los valores por defecto son los del contenedor local.
# El puerto por defecto es 5433, no 5432: el contenedor postgres_db publica
# 0.0.0.0:5433->5432/tcp (en V1 varios scripts lo tenían mal hardcodeado).
# ============================================================

import os

DB_CONFIG_DEFAULT = {
    "user": os.environ.get("DB_USER", "myuser"),
    "password": os.environ.get("DB_PASSWORD", "mypassword"),
    "host": os.environ.get("DB_HOST", "localhost"),
    "port": os.environ.get("DB_PORT", "5433"),
    "dbname": os.environ.get("DB_NAME", "mydb"),
}

_AYUDA_DEPS = (
    "Falta sqlalchemy o el driver de Postgres. En este repo la ruta de BD es "
    "opcional: instalarlos con `pixi add sqlalchemy psycopg2` (o usar la ruta "
    "de PI, src/acquisition/from_pi.py, que solo necesita requests + pandas)."
)


class DBManager:
    def __init__(self, user, password, host, port, dbname):
        try:
            from sqlalchemy import create_engine
        except ImportError as e:  # noqa: TRY003 — el mensaje es la ayuda útil
            raise RuntimeError(_AYUDA_DEPS) from e
        self.url = f"postgresql://{user}:{password}@{host}:{port}/{dbname}"
        self.engine = create_engine(self.url)

    def execute_query(self, query, params=None):
        import pandas as pd
        from sqlalchemy import text
        with self.engine.connect() as conn:
            # text() es necesario para que sqlalchemy acepte los parámetros
            # con nombre (:s_id) en vez de interpolarlos a mano.
            return pd.read_sql(text(query), conn, params=params)


class Extractor(DBManager):
    def __init__(self, table_name: str, **kwargs):
        super().__init__(**kwargs)
        self.table_name = table_name

    def get_head(self):
        query = """
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE lower(table_name) = lower(:t_name)
            AND table_schema = 'public'
            ORDER BY ordinal_position;
        """
        return self.execute_query(query, params={"t_name": self.table_name})

    def get_intensity(self, sample_id: int, desde: str | None = None, hasta: str | None = None):
        """Histórico completo de intensidades del sample_id.

        desde/hasta ('YYYY-MM-DD', opcionales) filtran por la columna `date`
        DESPUÉS de traer los datos, sin tocar la query original.
        """
        query = f"""
            SELECT date, time, instance, n1fe, n2cu, n3zn, n4mo, n5ech5, n6sc, n7ech7
            FROM {self.table_name}
            WHERE sample_id = :s_id
            ORDER BY date ASC, time ASC
        """
        df = self.execute_query(query, params={"s_id": sample_id})
        return _filtrar_por_fecha(df, desde, hasta)

    def get_assays(self, sample_id: int, desde: str | None = None, hasta: str | None = None):
        """Solo los ensayos de laboratorio (leyes) + `instance` como llave de
        fusión. No repite las intensidades crudas: duplicaría columnas al
        fusionar (n6sc_x / n6sc_y)."""
        query = f"""
            SELECT date, time, instance, "pFe", "pCu", "pZn", "pMo", "pIns", "pSol"
            FROM {self.table_name}
            WHERE sample_id = :s_id
            ORDER BY date ASC, time ASC
        """
        df = self.execute_query(query, params={"s_id": sample_id})
        return _filtrar_por_fecha(df, desde, hasta)


def _filtrar_por_fecha(df, desde, hasta):
    if desde is None and hasta is None:
        return df
    fechas = df["date"].astype(str)
    if desde is not None:
        df = df[fechas >= desde]
        fechas = df["date"].astype(str)
    if hasta is not None:
        df = df[fechas <= hasta]
    return df.reset_index(drop=True)
