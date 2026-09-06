# -*- coding: utf-8 -*-
"""
Prueba anti-regresión de H-B / Principio #1: "Nunca ffill() ni bfill() sobre
datos del historiador. Los huecos se preservan como NaN en su posición
correcta."

El script original rellenaba con `df.ffill().bfill()` y esa serie plana se
interpretó durante meses como una constante de respaldo real del PLC en los
tags de rebose — cuando en realidad los tags casi no tenían dato. Costó una
sesión completa de re-análisis desenredarlo (ver docs/inventario_proyecto.md,
hallazgo H-B).

Esta prueba tokeniza el código fuente de `src/espesadores/` (ignorando
comentarios, docstrings y strings — donde el propio código documenta en
prosa por qué NO se usa `ffill`/`bfill`, y esas menciones no deben contar
como violación) y busca llamadas reales a `.ffill(`/`.bfill(`/
`fillna(..., method=...)` sobre series del historiador.

NO prohíbe todo uso de la palabra "ffill": `e08_mineral.py` usa legítimamente
`reindex(df.index, method="ffill")` para propagar una ETIQUETA DE CLUSTER ya
calculada (categórica, agregada a 1 hora) a la grilla de 1 minuto — eso no
es enmascarar un hueco de sensor, es una decisión de modelado explícita y
documentada. Esa única línea está en el allowlist, con su justificación.
"""
import io
import re
import tokenize
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SRC = RAIZ / "src" / "espesadores"

PATRON_PROHIBIDO = re.compile(r"\.ffill\(|\.bfill\(|fillna\([^)]*method\s*=")

# (archivo relativo a src/espesadores, línea de código real —sin comentarios
# ni strings— tal como queda tras la tokenización) -> motivo aceptado.
ALLOWLIST = {
    ("pipeline/e08_mineral.py", 'df = df.join(A[["mineral"]].reindex(df.index, method="ffill"))'):
        "Propaga una etiqueta de cluster categórica (agregada a 1h) a la grilla "
        "de 1min. No enmascara huecos de sensor: el mineral no tiene dato propio "
        "de 1 minuto, es una agregación deliberada, documentada en el propio "
        "docstring de E08.",
}


def _archivos_fuente():
    return sorted(SRC.rglob("*.py"))


def _codigo_sin_comentarios_ni_strings(texto):
    """Reconstruye el archivo línea por línea, reemplazando el contenido de
    strings y comentarios por espacios (conserva números de línea), para que
    una mención en prosa ("se eliminó `df.ffill()`") no cuente como código."""
    lineas = texto.splitlines()
    lineas_out = [list(l) for l in lineas]
    try:
        tokens = tokenize.generate_tokens(io.StringIO(texto).readline)
        for tok in tokens:
            if tok.type in (tokenize.STRING, tokenize.COMMENT, tokenize.FSTRING_MIDDLE
                             if hasattr(tokenize, "FSTRING_MIDDLE") else tokenize.STRING):
                (sr, sc), (er, ec) = tok.start, tok.end
                for ln in range(sr, er + 1):
                    if ln - 1 >= len(lineas_out):
                        continue
                    fila = lineas_out[ln - 1]
                    ini = sc if ln == sr else 0
                    fin = ec if ln == er else len(fila)
                    for c in range(ini, min(fin, len(fila))):
                        fila[c] = " "
    except tokenize.TokenError:
        pass
    return ["".join(l) for l in lineas_out]


def test_sin_ffill_bfill_fuera_del_allowlist():
    permitidas = {(archivo, linea) for archivo, linea in ALLOWLIST}
    violaciones = []
    for archivo in _archivos_fuente():
        rel = str(archivo.relative_to(SRC))
        texto = archivo.read_text(encoding="utf-8")
        for i, linea in enumerate(_codigo_sin_comentarios_ni_strings(texto), start=1):
            if PATRON_PROHIBIDO.search(linea):
                # La línea ORIGINAL (con strings intactos) es la que se
                # compara contra el allowlist y se muestra en el error.
                original = texto.splitlines()[i - 1].strip()
                if (rel, original) not in permitidas:
                    violaciones.append(f"{rel}:{i}: {original}")
    assert not violaciones, (
        "Se encontró ffill/bfill/fillna(method=...) fuera del allowlist — "
        "esto reintroduce el bug de H-B (constante fabricada interpretada "
        "como comportamiento real del PLC durante meses):\n" + "\n".join(violaciones)
    )


def test_el_allowlist_sigue_vigente():
    """Si la línea permitida cambia o se borra, el allowlist queda obsoleto:
    mejor que la prueba lo señale explícitamente en vez de quedar en silencio
    permitiendo cualquier otra cosa."""
    for (archivo_rel, linea_esperada), _motivo in ALLOWLIST.items():
        archivo = SRC / archivo_rel
        assert archivo.exists(), f"{archivo_rel} ya no existe; actualizar el allowlist"
        contenido = archivo.read_text(encoding="utf-8")
        assert linea_esperada in contenido, (
            f"La línea permitida en {archivo_rel} cambió o se borró; "
            "revisar y actualizar ALLOWLIST en este archivo de test."
        )
