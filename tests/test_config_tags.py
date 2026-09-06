# -*- coding: utf-8 -*-
"""
Prueba anti-regresión de H-A: el bug de la clave duplicada en `tags_config`
que hizo desaparecer `Alim_Total_PB01` y apuntó `Alim_Total_PB02` al tag del
Molino 1, en silencio, durante toda la historia del proyecto (ver
docs/inventario_proyecto.md y el hallazgo H-A del traspaso).

`TAGS_EXTRACCION_PI` en conf/base/tags.yaml es una LISTA (no un dict), así
que un tag_pi o una columna repetidos no se "pisan" solos como en el
diccionario original — pero nada impide que alguien reintroduzca la
duplicación al editar el YAML. Esta prueba es la guarda: si el criterio de
aceptación 6 de la migración ("un test que falla si se reintroduce una
clave de tag duplicada") deja de cumplirse, esta prueba lo detecta.
"""
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from espesadores.config import TAGS_EXTRACCION_PI, ESPESADORES


def test_no_hay_tag_pi_duplicado():
    tags_pi = [fila[0] for fila in TAGS_EXTRACCION_PI]
    repetidos = [t for t, n in Counter(tags_pi).items() if n > 1]
    assert not repetidos, (
        f"tag_pi duplicado en conf/base/tags.yaml::extraccion_pi: {repetidos}. "
        "Este es exactamente el bug de H-A: un tag_pi repetido hace que la "
        "columna de uno de los dos quede huérfana o que dos columnas terminen "
        "leyendo el mismo punto PI, en silencio."
    )


def test_no_hay_columna_duplicada():
    columnas = [fila[1] for fila in TAGS_EXTRACCION_PI]
    repetidas = [c for c, n in Counter(columnas).items() if n > 1]
    assert not repetidas, (
        f"columna duplicada en conf/base/tags.yaml::extraccion_pi: {repetidas}. "
        "Dos tag_pi distintos escribiendo la misma columna es la otra cara "
        "del bug de H-A (Alim_Total_PB02 quedó apuntando al tag del Molino 1)."
    )


def test_alim_total_pb01_y_pb02_son_tags_distintos():
    """Caso concreto de H-A: PB01 y PB02 deben ser columnas y tag_pi distintos."""
    por_columna = {fila[1]: fila[0] for fila in TAGS_EXTRACCION_PI}
    assert "Alim_Total_PB01" in por_columna
    assert "Alim_Total_PB02" in por_columna
    assert por_columna["Alim_Total_PB01"] != por_columna["Alim_Total_PB02"]
    assert por_columna["Alim_Total_PB01"] == "_293200_Alim_Total_PB01_ABB"
    assert por_columna["Alim_Total_PB02"] == "_293200_Alim_Total_PB02_ABB"


def test_espesadores_no_tienen_tag_repetido_dentro_de_si_mismos():
    """Un mismo espesador no debe repetir un tag entre sus propios campos."""
    for nombre, cfg in ESPESADORES.items():
        tags = []
        for campo, valor in cfg.items():
            if campo == "trenes":
                for tren in valor:
                    tags += [tren["descarga"], tren["wt"], tren["dit"], tren["cizalle"]]
            elif campo not in ("nombre_largo", "tag_equipo", "flujos_todos"):
                tags.append(valor)
        repetidos = [t for t, n in Counter(tags).items() if n > 1]
        assert not repetidos, f"{nombre} repite el tag {repetidos} entre sus propios campos"
