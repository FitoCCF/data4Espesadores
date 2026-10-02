# ============================================================
# src/acquisition — fuentes de adquisición de datos
# ============================================================
# Paquete traído de data2TesisV2 y hecho autocontenido para este repo:
# ninguno de sus módulos importa de data2TesisV2 ni de `espesadores`.
#
#   from_pi.py        PI OSIsoft vía la pasarela PiGateway (ruta vigente)
#   from_pi_afsdk.py  PI OSIsoft con AF SDK directo (solo Windows, referencia)
#   from_db.py        Postgres `works4cdp_assay` (courier de cobre)
#   pi_client.py      cliente HTTP de la pasarela (copia única del repo; es la
#                     misma que usa src/espesadores/agente/datos.py)
#   database.py       conexión y consultas a Postgres (requiere sqlalchemy)
#
# Las importaciones son perezosas a propósito: `from_db` necesita sqlalchemy y
# `from_pi_afsdk` necesita pythonnet/Windows, y ninguno de los dos debe
# impedir usar `from_pi` (que solo necesita requests + pandas).
# ============================================================

__all__ = ["extraer_courier", "extraer_generico", "extraer_intensidades", "extraer_assays", "PiGateway"]


def __getattr__(nombre):
    if nombre in ("extraer_courier", "extraer_generico"):
        from . import from_pi
        return getattr(from_pi, nombre)
    if nombre in ("extraer_intensidades", "extraer_assays"):
        from . import from_db
        return getattr(from_db, nombre)
    if nombre == "PiGateway":
        from .pi_client import PiGateway
        return PiGateway
    raise AttributeError(nombre)
