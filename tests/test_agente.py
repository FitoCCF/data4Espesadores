# -*- coding: utf-8 -*-
"""
Pruebas del agente offline (src/espesadores/agente/): motor de reglas,
estadística y despacho de herramientas, sin PI ni LLM (datos sintéticos).
"""
import numpy as np
import pandas as pd
import pytest

from espesadores.agente import estadistica as E
from espesadores.agente import reglas as R
from espesadores.agente.datos import enriquecer, variables_disponibles
from espesadores.config import ESPESADORES, PISCINAS_TAGS, GLOBALES


def _df_sintetico(horas=24, espesador="TH-001"):
    idx = pd.date_range("2026-01-01", periods=horas * 60, freq="min", tz="America/Lima")
    rng = np.random.default_rng(1)
    cfg = ESPESADORES[espesador]
    df = pd.DataFrame(index=idx)
    df[PISCINAS_TAGS["transmisor_a"]] = 90 + rng.normal(0, 0.2, len(idx))
    df[PISCINAS_TAGS["transmisor_b"]] = 90 + rng.normal(0, 0.2, len(idx))
    for m in GLOBALES["molinos"]:
        df[m] = 1300 + rng.normal(0, 20, len(idx))
    df[cfg["flujo_alim"]] = 1600 + rng.normal(0, 30, len(idx))
    df[cfg["valvula_alim"]] = 35.0
    df[cfg["presion_cama"]] = 55 + rng.normal(0, 0.5, len(idx))
    df[cfg["torque"]] = 30 + rng.normal(0, 1, len(idx))
    df[cfg["trenes"][0]["descarga"]] = 30 + rng.normal(0, 0.5, len(idx))
    df[cfg["trenes"][1]["descarga"]] = 0.0
    df[cfg["trenes"][0]["wt"]] = 59 + rng.normal(0, 0.2, len(idx))
    return df


def test_enriquecer_deriva_roles():
    df = enriquecer(_df_sintetico(), "TH-001")
    assert {"flujo_alim", "vel_descarga", "wt_activo", "nivel_piscina", "molienda_total"} <= set(df.columns)
    assert (df["trenes_activos"] == 1).all()
    assert abs(df["nivel_piscina"].median() - 90) < 1
    assert abs(df["molienda_total"].median() - 2600) < 100


def test_reglas_del_repo_validan():
    ids = []
    for r in R.cargar_reglas():
        assert R.validar_regla(r, ids) == [], r["id"]
        ids.append(r["id"])


def test_regla_detecta_episodio_con_duracion_minima():
    df = enriquecer(_df_sintetico(), "planta")
    # Piscina bajo 75 % durante 45 min a partir de las 10:00
    ini = df.index[10 * 60]
    df.loc[ini: ini + pd.Timedelta(minutes=44), "nivel_piscina"] = 70.0
    regla = R.nueva_regla("t_piscina", "nivel_piscina < 75", "piscina {nivel_piscina:.0f} % {duracion_min} min",
                          espesador="planta", duracion_min=30, severidad="alta")
    h = R.evaluar(df, "planta", [regla])
    assert len(h) == 1
    assert h[0]["minutos"] == 45 and h[0]["mensaje"] == "piscina 70 % 45 min"
    # Con duración mínima mayor que el episodio, no dispara
    regla["duracion_min"] = 60
    assert R.evaluar(df, "planta", [regla]) == []


def test_regla_con_funciones_y_derivadas_en_mensaje():
    df = enriquecer(_df_sintetico(), "TH-001")
    ini = df.index[12 * 60]
    df.loc[ini:, "presion_cama"] = df.loc[ini:, "presion_cama"] + np.arange((df.index >= ini).sum()) * 0.05
    regla = R.nueva_regla("t_cama", "pendiente(presion_cama, '1h') > 1.0",
                          "sube {pendiente_presion_cama_1h:.1f}/h", duracion_min=30)
    assert R.validar_regla(regla) == []
    h = R.evaluar(df, "TH-001", [regla])
    assert h and h[0]["mensaje"].startswith("sube ")


def test_regla_rechaza_construcciones_peligrosas():
    regla = R.nueva_regla("mala", "__import__('os').system('true')", "x")
    assert any("no permitida" in p for p in R.validar_regla(regla))
    regla = R.nueva_regla("desconocida", "variable_que_no_existe > 1", "x")
    assert any("no evalúa" in p for p in R.validar_regla(regla))


def test_variables_disponibles_incluyen_planta_y_espesador():
    assert "nivel_piscina" in variables_disponibles("planta")
    assert "valvula_alim" not in variables_disponibles("planta")
    assert "valvula_alim" in variables_disponibles("TH-002")


def test_estadistica_congelado_y_escalon():
    df = enriquecer(_df_sintetico(), "TH-001")
    ini = df.index[5 * 60]
    df.loc[ini: ini + pd.Timedelta(minutes=119), "torque"] = 31.0        # congelado 120 min
    df.loc[df.index[15 * 60]:, "flujo_alim"] += 600                       # escalón
    a = E.anomalias(df, "TH-001")
    assert any(c["variable"] == "torque" and c["minutos"] >= 120 for c in a["congelados"])
    assert any(c["variable"] == "flujo_alim" and c["despues_p50"] > c["antes_p50"] for c in a["cambios_de_regimen"])
    # La válvula (escalón por diseño) no se reporta como congelada
    assert not any(c["variable"] == "valvula_alim" for c in a["congelados"])


def test_comparar_periodos_marca_relevante():
    df = enriquecer(_df_sintetico(), "TH-001")
    a, b = df.iloc[: 12 * 60].copy(), df.iloc[12 * 60:].copy()
    b["flujo_alim"] += 400
    c = E.comparar(a, b, "TH-001", roles=["flujo_alim", "torque"])
    assert c["variables"]["flujo_alim"]["relevante"] is True
    assert c["variables"]["torque"]["relevante"] is False


def test_herramientas_esquemas_y_despacho_de_error():
    from espesadores.agente import herramientas as H
    nombres = {e["function"]["name"] for e in H.esquemas_ollama()}
    assert nombres == set(H.FUNCIONES)
    res = H.invocar("no_existe", {})
    assert "error" in res
    res = H.invocar("listar_variables", {"espesador": "E2"})
    assert '"TH-002"' in res


# ---------------------------------------------------------------------------
# Paquete `acquisition` (traído de data2TesisV2): debe ser autocontenido, es
# decir, importable sin ese proyecto en el PYTHONPATH y sin tocar `espesadores`.
# ---------------------------------------------------------------------------
def test_acquisition_es_autocontenido():
    import ast
    from pathlib import Path

    carpeta = Path(__file__).resolve().parents[1] / "src" / "acquisition"
    externos = []
    for archivo in sorted(carpeta.glob("*.py")):
        arbol = ast.parse(archivo.read_text(encoding="utf-8"))
        for nodo in ast.walk(arbol):
            modulos = []
            if isinstance(nodo, ast.Import):
                modulos = [a.name for a in nodo.names]
            elif isinstance(nodo, ast.ImportFrom) and not nodo.level:
                modulos = [nodo.module or ""]
            for m in modulos:
                raiz = m.split(".")[0]
                if raiz in ("src", "espesadores", "data2TesisV2", "data2Tesis"):
                    externos.append(f"{archivo.name}: {m}")
    assert not externos, (
        "acquisition no debe importar de otro proyecto ni del paquete espesadores "
        "(debe poder ejecutarse con PYTHONPATH=src python -m acquisition.<modulo>):\n"
        + "\n".join(externos))


def test_acquisition_from_pi_importa_y_tiene_los_tags_del_courier():
    from acquisition import from_pi
    assert set(from_pi.TAGS_COURIER.values()) == {"n1fe", "n2cu", "n3zn", "n4mo", "n6sc"}
    assert from_pi.FECHA_INICIO_COURIER.startswith("2025-07-13")
    # DATA_RAW apunta a la carpeta de datos crudos de ESTE repo, no a data/raw
    assert from_pi.DATA_RAW.name == "00_raw"


def test_agente_y_acquisition_comparten_un_solo_pi_client():
    from espesadores.agente.datos import _importar_pi_client
    assert _importar_pi_client().__module__ == "acquisition.pi_client"
