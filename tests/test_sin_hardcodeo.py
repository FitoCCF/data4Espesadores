# -*- coding: utf-8 -*-
"""
Prueba anti-regresión del criterio de aceptación 7 de la migración: "Ningún
módulo de src/ contiene rutas absolutas ni nombres de tag hardcodeados."

No intenta detectar CUALQUIER tag (imposible sin una lista cerrada y
propensa a falsos negativos); en cambio busca las dos formas concretas en
que esto ya ocurrió en el proyecto:
  1. Rutas absolutas de Windows (`C:\\...`) — antes en 4 scripts de extracción.
  2. Asignaciones de módulo tipo `COL_A = 'LIT_106'` con un valor que parece
     un tag PI (mayúsculas/dígitos/guiones bajos) — antes en
     `nivel_piscinas.py`.
"""
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SRC = RAIZ / "src" / "espesadores"

RUTA_ABSOLUTA_WINDOWS = re.compile(r"[A-Za-z]:\\\\|r'[A-Za-z]:\\\\|r\"[A-Za-z]:\\\\")
ASIGNACION_TAG_LITERAL = re.compile(
    r"^\s*[A-Z_][A-Z0-9_]*\s*=\s*['\"][A-Z]{2,}[A-Z0-9_]*['\"]\s*(#.*)?$"
)

# Los propios YAML citan tags dentro de comentarios/strings de Python en
# config.py (docstrings, no asignaciones) — se excluye ese único archivo
# porque es el loader declarativo, no un módulo con tags de negocio.
ARCHIVOS_EXCLUIDOS = {"config.py"}


def _archivos_fuente():
    return [f for f in sorted(SRC.rglob("*.py")) if f.name not in ARCHIVOS_EXCLUIDOS]


def test_sin_rutas_absolutas_windows():
    violaciones = []
    for archivo in _archivos_fuente():
        for i, linea in enumerate(archivo.read_text(encoding="utf-8").splitlines(), start=1):
            if RUTA_ABSOLUTA_WINDOWS.search(linea):
                violaciones.append(f"{archivo.relative_to(SRC)}:{i}: {linea.strip()}")
    assert not violaciones, (
        "Ruta absoluta de Windows hardcodeada en src/espesadores (debe salir "
        "de conf/local/*.yaml):\n" + "\n".join(violaciones)
    )


def test_sin_asignacion_de_tag_literal_a_constante():
    violaciones = []
    for archivo in _archivos_fuente():
        for i, linea in enumerate(archivo.read_text(encoding="utf-8").splitlines(), start=1):
            if ASIGNACION_TAG_LITERAL.match(linea):
                violaciones.append(f"{archivo.relative_to(SRC)}:{i}: {linea.strip()}")
    assert not violaciones, (
        "Constante con un tag PI escrito literalmente en el código (debe "
        "salir de conf/base/tags.yaml, como se corrigió en nivel_piscinas.py "
        "-> dominio/piscinas.py):\n" + "\n".join(violaciones)
    )
