# -*- coding: utf-8 -*-
"""
================================================================================
ONE-PAGER CONSOLIDADO — TH-001 / TH-002 / TH-003 EN UNA SOLA HOJA
================================================================================
Une los tres one-pagers en uno, organizado alrededor de lo que el usuario
señaló como eje del proyecto (2026-09-16): el nivel de piscina, la válvula y
el flujo de alimentación, y las métricas de rebose. Gráficos (SVG embebido,
sin dependencias externas) en vez de texto.

No recalcula nada: lee las salidas E09-E11 de `data/06_reporting/TH00X/` y
los análisis por episodios de `data/01_interim/` (atoro_alimentacion.py,
piscina_episodios.py). Si un archivo falta, la sección se omite.

Diseño: tonos plomos (un plomo por espesador, con marcador distinto ●■▲
como codificación secundaria, para que la identidad no dependa solo del
tono); dos acentos reservados para resaltar el máximo (ámbar) y el mínimo
(azul) entre los tres espesadores en cada parámetro. Paleta validada con
el validador de la guía de visualización (separación ΔE ≥ 15 entre plomos
y contraste ≥ 3:1 sobre el papel).

Uso:
    PYTHONPATH=src python -m espesadores.reportes.onepager_consolidado
"""
import json
import os
from datetime import datetime

import numpy as np
import pandas as pd

from espesadores.config import ESPESADORES, RUTAS

ESP = ["TH-001", "TH-002", "TH-003"]
PLOMO = {"TH-001": "#1F2326", "TH-002": "#5C646C", "TH-003": "#8C939A"}
FORMA = {"TH-001": "circulo", "TH-002": "cuadrado", "TH-003": "triangulo"}
MAX, MIN = "#8A6516", "#3B6E8F"
INK, STEEL, HAIR, PAPER = "#15181B", "#6C757E", "#C4C5BF", "#F5F5F1"

ROLES = [
    ("presion_cama", "Presión de cama"), ("torque", "Torque de rastra"),
    ("nivel_interfaz", "Nivel de interfaz"), ("flujo_alim", "Flujo de alimentación"),
    ("wt_activo", "% sólidos de descarga"), ("vel_descarga", "Bomba de descarga"),
    ("vel_cizalle", "Bomba de cizallamiento"), ("floculante", "Floculante"),
    ("valvula_alim", "Válvula de alimentación"),
]


# ------------------------------------------------------------------ carga
def _carp(esp):
    return os.path.join(RUTAS["salidas"], esp.replace("-", ""))


def _csv(esp, nombre, carpeta=None, index_col=0):
    ruta = os.path.join(carpeta or _carp(esp), nombre)
    return pd.read_csv(ruta, index_col=index_col) if os.path.exists(ruta) else None


def _interim(nombre):
    ruta = os.path.join(os.path.dirname(RUTAS["salidas"]), "01_interim", nombre)
    return pd.read_csv(ruta, index_col=0) if os.path.exists(ruta) else None


def _json(esp, nombre):
    ruta = os.path.join(_carp(esp), nombre)
    return json.load(open(ruta, encoding="utf-8")) if os.path.exists(ruta) else {}


def _tag(esp, rol):
    return ESPESADORES[esp].get(rol, rol)


def _f(v, nd=2):
    try:
        return f"{float(v):.{nd}f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return "–"


# ------------------------------------------------------------------ svg
def marcador(esp, x, y, r=5, fill=None, stroke=None, sw=1.5, title=""):
    fill = fill or PLOMO[esp]
    stroke = stroke or PAPER
    t = f"<title>{title}</title>" if title else ""
    forma = FORMA[esp]
    if forma == "circulo":
        return f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}">{t}</circle>'
    if forma == "cuadrado":
        return (f'<rect x="{x-r:.1f}" y="{y-r:.1f}" width="{2*r}" height="{2*r}" fill="{fill}" '
                f'stroke="{stroke}" stroke-width="{sw}">{t}</rect>')
    return (f'<polygon points="{x:.1f},{y-r-1:.1f} {x+r+1:.1f},{y+r:.1f} {x-r-1:.1f},{y+r:.1f}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}">{t}</polygon>')


def leyenda(x, y, extra=None):
    out, dx = [], x
    for esp in ESP:
        out.append(marcador(esp, dx + 5, y, 4.5))
        out.append(f'<text x="{dx+14}" y="{y+3.5}" class="lg">{esp}</text>')
        dx += 68
    for color, txt in (extra or []):
        out.append(f'<rect x="{dx}" y="{y-4}" width="9" height="9" fill="{color}"/>')
        out.append(f'<text x="{dx+13}" y="{y+3.5}" class="lg">{txt}</text>')
        dx += 14 + 7 * len(txt)
    return "".join(out)


def _escala(lo, hi, x0, x1):
    span = (hi - lo) or 1.0
    return lambda v: x0 + (v - lo) / span * (x1 - x0)


def svg_rangos(titulo, filas, unidad="", resaltar=True, ancho=920):
    """
    Barras de rango horizontales: una fila por espesador.
    filas: [{esp, min, max, objetivo, actual, escala_min, escala_max, nota}]
    Resalta el mayor `max` (ámbar) y el menor `min` (azul) entre espesadores.
    """
    filas = [f for f in filas if f is not None]
    if not filas:
        return ""
    lo = min(min(f["escala_min"], f["min"]) for f in filas)
    hi = max(max(f["escala_max"], f["max"]) for f in filas)
    pad = (hi - lo) * 0.06
    lo, hi = lo - pad, hi + pad
    x0, x1 = 150, ancho - 150
    X = _escala(lo, hi, x0, x1)
    h = 26
    alto = 30 + h * len(filas) + 14
    i_max = max(range(len(filas)), key=lambda i: filas[i]["max"]) if resaltar else -1
    i_min = min(range(len(filas)), key=lambda i: filas[i]["min"]) if resaltar else -1
    s = [f'<svg viewBox="0 0 {ancho} {alto}" class="ch">',
         f'<text x="0" y="14" class="t">{titulo}</text>',
         f'<text x="{ancho}" y="14" class="u" text-anchor="end">{unidad}</text>']
    for i, f in enumerate(filas):
        y = 30 + i * h + h / 2
        esp = f["esp"]
        s.append(f'<line x1="{x0}" x2="{x1}" y1="{y}" y2="{y}" class="rail"/>')
        s.append(f'<text x="{x0-8}" y="{y+4}" class="lab" text-anchor="end">{esp}</text>')
        s.append(f'<rect x="{X(f["min"]):.1f}" y="{y-4}" width="{max(2, X(f["max"])-X(f["min"])):.1f}" '
                 f'height="8" rx="4" fill="{PLOMO[esp]}"><title>{esp}: ventana {_f(f["min"])} – {_f(f["max"])}, '
                 f'apuntar {_f(f["objetivo"])}, hoy {_f(f["actual"])}</title></rect>')
        s.append(f'<line x1="{X(f["objetivo"]):.1f}" x2="{X(f["objetivo"]):.1f}" y1="{y-9}" y2="{y+9}" '
                 f'stroke="{INK}" stroke-width="2"/>')
        s.append(marcador(esp, X(f["actual"]), y, 5, fill=PAPER, stroke=PLOMO[esp], sw=2,
                          title=f"{esp} hoy {_f(f['actual'])}"))
        etq_min = f'<text x="{X(f["min"])-6:.1f}" y="{y+4}" class="v" text-anchor="end">{_f(f["min"])}</text>'
        etq_max = f'<text x="{X(f["max"])+6:.1f}" y="{y+4}" class="v">{_f(f["max"])}</text>'
        if i == i_max:
            etq_max = (f'<text x="{X(f["max"])+6:.1f}" y="{y+4}" class="v hi" fill="{MAX}">'
                       f'{_f(f["max"])} ▲máx</text>')
        if i == i_min:
            etq_min = (f'<text x="{X(f["min"])-6:.1f}" y="{y+4}" class="v hi" fill="{MIN}" '
                       f'text-anchor="end">mín▼ {_f(f["min"])}</text>')
        s.append(etq_min + etq_max)
        if f.get("nota"):
            s.append(f'<text x="{ancho}" y="{y+4}" class="nota" text-anchor="end">{f["nota"]}</text>')
    s.append(f'<text x="{x0}" y="{alto-2}" class="ax">{_f(lo,1)}</text>'
             f'<text x="{x1}" y="{alto-2}" class="ax" text-anchor="end">{_f(hi,1)}</text>')
    s.append("</svg>")
    return "".join(s)


def svg_lineas(titulo, series, xs, ylab="", ref=None, ref_lab="referencia", ancho=920,
               alto=230, ymin=None, ymax=None, xlab="minutos"):
    """Líneas: series = {esp: [y...]} sobre xs comunes. Un solo eje y."""
    series = {k: v for k, v in series.items() if v is not None and len(v)}
    if not series:
        return ""
    vals = [v for ys in series.values() for v in ys if pd.notna(v)]
    if ref is not None:
        vals.append(ref)
    lo = ymin if ymin is not None else min(vals)
    hi = ymax if ymax is not None else max(vals)
    pad = (hi - lo) * 0.12 or 1
    lo, hi = lo - pad, hi + pad
    x0, x1, y0, y1 = 56, ancho - 80, 28, alto - 30
    X = _escala(min(xs), max(xs), x0, x1)
    Y = _escala(lo, hi, y1, y0)
    s = [f'<svg viewBox="0 0 {ancho} {alto}" class="ch">',
         f'<text x="0" y="14" class="t">{titulo}</text>', leyenda(ancho - 300, 11)]
    for g in np.linspace(lo, hi, 4):
        s.append(f'<line x1="{x0}" x2="{x1}" y1="{Y(g):.1f}" y2="{Y(g):.1f}" class="grid"/>'
                 f'<text x="{x0-6}" y="{Y(g)+3.5:.1f}" class="ax" text-anchor="end">{_f(g,1)}</text>')
    if ref is not None:
        s.append(f'<line x1="{x0}" x2="{x1}" y1="{Y(ref):.1f}" y2="{Y(ref):.1f}" stroke="{INK}" '
                 f'stroke-width="1"/><text x="{x1+4}" y="{Y(ref)+3.5:.1f}" class="ax">{ref_lab}</text>')
    for esp, ys in series.items():
        pts = [(X(x), Y(y)) for x, y in zip(xs, ys) if pd.notna(y)]
        if not pts:
            continue
        s.append(f'<polyline points="{" ".join(f"{a:.1f},{b:.1f}" for a, b in pts)}" fill="none" '
                 f'stroke="{PLOMO[esp]}" stroke-width="2"/>')
        for (a, b), x, y in zip(pts, xs, ys):
            s.append(marcador(esp, a, b, 3.5, title=f"{esp} · min {x}: {_f(y)}"))
        a, b = pts[-1]
        s.append(f'<text x="{a+8:.1f}" y="{b+4:.1f}" class="lab" fill="{PLOMO[esp]}">{esp}</text>')
    s.append(f'<text x="{x0}" y="{alto-8}" class="ax">{_f(min(xs),0)}</text>'
             f'<text x="{x1}" y="{alto-8}" class="ax" text-anchor="end">{_f(max(xs),0)} {xlab}</text>'
             f'<text x="{x0-6}" y="{y0-8}" class="ax" text-anchor="end">{ylab}</text></svg>')
    return "".join(s)


def svg_barras(titulo, categorias, series, ylab="", ancho=920, alto=220, etiquetas=True,
               por_categoria=False):
    """
    Barras agrupadas: series = {esp: [v por categoria]}. Resalta máx/mín global.
    por_categoria=True: una sola barra por categoría, coloreada por la
    categoría misma (cuando la categoría ES el espesador).
    """
    if por_categoria:
        series = {"_": [series[c][0] for c in categorias]}
    series = {k: v for k, v in series.items() if v is not None}
    if not series or not categorias:
        return ""
    vals = [v for ys in series.values() for v in ys if pd.notna(v)]
    lo, hi = min(0, min(vals)), max(0, max(vals))
    hi = hi + (hi - lo) * 0.15
    lo = lo - (hi - lo) * 0.05 if lo < 0 else lo
    x0, x1, y0, y1 = 56, ancho - 20, 28, alto - 34
    Y = _escala(lo, hi, y1, y0)
    n_c, n_s = len(categorias), len(series)
    gw = (x1 - x0) / n_c
    bw = min(26, (gw * 0.7) / n_s)
    vmax, vmin = max(vals), min(vals)
    s = [f'<svg viewBox="0 0 {ancho} {alto}" class="ch">',
         f'<text x="0" y="14" class="t">{titulo}</text>', leyenda(ancho - 300, 11)]
    for g in np.linspace(lo, hi, 4):
        s.append(f'<line x1="{x0}" x2="{x1}" y1="{Y(g):.1f}" y2="{Y(g):.1f}" class="grid"/>'
                 f'<text x="{x0-6}" y="{Y(g)+3.5:.1f}" class="ax" text-anchor="end">{_f(g,1)}</text>')
    if lo < 0:
        s.append(f'<line x1="{x0}" x2="{x1}" y1="{Y(0):.1f}" y2="{Y(0):.1f}" stroke="{INK}" stroke-width="1"/>')
    for ci, cat in enumerate(categorias):
        gx = x0 + ci * gw + (gw - bw * n_s - 2 * (n_s - 1)) / 2
        for si, (esp, ys) in enumerate(series.items()):
            v = ys[ci] if ci < len(ys) else np.nan
            if pd.isna(v):
                continue
            bx = gx + si * (bw + 2)
            top, bot = Y(max(v, 0)), Y(min(v, 0))
            color = PLOMO.get(cat if por_categoria else esp, STEEL)
            quien = cat if por_categoria else esp
            s.append(f'<rect x="{bx:.1f}" y="{top:.1f}" width="{bw:.1f}" height="{max(1, bot-top):.1f}" '
                     f'rx="3" fill="{color}"><title>{quien} · {cat}: {_f(v)}</title></rect>')
            if etiquetas and (v == vmax or v == vmin):
                col = MAX if v == vmax else MIN
                ty = top - 4 if v >= 0 else bot + 11
                s.append(f'<text x="{bx+bw/2:.1f}" y="{ty:.1f}" class="v hi" fill="{col}" '
                         f'text-anchor="middle">{_f(v)}</text>')
        s.append(f'<text x="{x0+ci*gw+gw/2:.1f}" y="{alto-12}" class="ax" text-anchor="middle">{cat}</text>')
    s.append(f'<text x="{x0-6}" y="{y0-8}" class="ax" text-anchor="end">{ylab}</text></svg>')
    return "".join(s)


def svg_dumbbell(titulo, filas, ancho=920, lab_a="tercio ALTA", lab_b="tercio BAJA"):
    """filas: [{esp, etiqueta, a, b, nota}] — a (relleno) vs b (hueco) por fila."""
    filas = [f for f in filas if f and pd.notna(f.get("a")) and pd.notna(f.get("b"))]
    if not filas:
        return ""
    vals = [f["a"] for f in filas] + [f["b"] for f in filas]
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.15 or 1
    lo, hi = lo - pad, hi + pad
    x0, x1 = 220, ancho - 230
    X = _escala(lo, hi, x0, x1)
    h = 26
    alto = 30 + h * len(filas) + 8
    s = [f'<svg viewBox="0 0 {ancho} {alto}" class="ch">',
         f'<text x="0" y="14" class="t">{titulo}</text>',
         f'<text x="{ancho}" y="14" class="u" text-anchor="end">● {lab_a} · ○ {lab_b}</text>']
    for i, f in enumerate(filas):
        y, esp = 30 + i * h + h / 2, f["esp"]
        s.append(f'<line x1="{x0}" x2="{x1}" y1="{y}" y2="{y}" class="rail"/>')
        s.append(f'<text x="{x0-8}" y="{y+4}" class="lab" text-anchor="end">{f["etiqueta"]}</text>')
        s.append(f'<line x1="{X(f["b"]):.1f}" x2="{X(f["a"]):.1f}" y1="{y}" y2="{y}" '
                 f'stroke="{PLOMO[esp]}" stroke-width="3"/>')
        s.append(marcador(esp, X(f["b"]), y, 5, fill=PAPER, stroke=PLOMO[esp], sw=2,
                          title=f"{esp} {lab_b}: {_f(f['b'])}"))
        s.append(marcador(esp, X(f["a"]), y, 5, title=f"{esp} {lab_a}: {_f(f['a'])}"))
        izq, der = (f["b"], f["a"]) if f["b"] <= f["a"] else (f["a"], f["b"])
        s.append(f'<text x="{X(izq)-8:.1f}" y="{y+4}" class="v" text-anchor="end">{_f(izq)}</text>'
                 f'<text x="{X(der)+8:.1f}" y="{y+4}" class="v">{_f(der)}</text>')
        if f.get("nota"):
            s.append(f'<text x="{ancho}" y="{y+4}" class="nota" text-anchor="end">{f["nota"]}</text>')
    s.append("</svg>")
    return "".join(s)


# ------------------------------------------------------------------ secciones
def sec_ventanas():
    out = []
    for rol, nombre in ROLES:
        filas = []
        for esp in ESP:
            C = _csv(esp, "E10c_ventana_consolidada.csv")
            tag = _tag(esp, rol)
            if C is None or tag not in C.index:
                continue
            r = C.loc[tag]
            filas.append({"esp": esp, "min": r["min"], "max": r["max"], "objetivo": r["objetivo"],
                          "actual": r["actual"], "escala_min": r["escala_min"],
                          "escala_max": r["escala_max"],
                          "nota": f"{tag} · {r['clase'].replace('_', ' ')}"})
        out.append(svg_rangos(nombre, filas))
    return "".join(out)


def sec_mineral():
    tipos = set()
    for esp in ESP:
        A = _csv(esp, "E10a_brecha_por_mineral.csv")
        if A is not None:
            tipos.update(int(t) for t in A.index)
    tipos = sorted(tipos)
    cats = [f"mineral {t}" for t in tipos]
    alta, baja, gan = {}, {}, {}
    for esp in ESP:
        A = _csv(esp, "E10a_brecha_por_mineral.csv")
        if A is None:
            continue
        alta[esp] = [float(A.loc[t, "rec_alta"]) if t in A.index else np.nan for t in tipos]
        baja[esp] = [float(A.loc[t, "rec_baja"]) if t in A.index else np.nan for t in tipos]
        gan[esp] = [float(A.loc[t, "brecha_m3h"]) if t in A.index else np.nan for t in tipos]
    html = svg_barras("Recuperación en el tercio ALTA por tipo de mineral (%)", cats, alta, "% recup.")
    html += svg_barras("Recuperación en el tercio BAJA por tipo de mineral (%)", cats, baja, "% recup.")
    html += svg_barras("Ganancia a tonelaje constante entre ALTA y BAJA (m³/h)", cats, gan, "m³/h")
    # eta2 mineral vs guardia sobre el resultado
    filas = []
    for esp in ESP:
        G = _csv(esp, "E09b_guardia_vs_mineral.csv")
        if G is None:
            continue
        for var, etq in (("recuperacion", "Recuperación"), ("wt_activo", "% sólidos")):
            if var in G.index:
                r = G.loc[var]
                filas.append({"esp": esp, "etiqueta": f"{esp} · {etq}", "a": r["eta2_mineral"],
                              "b": r["eta2_guardia"], "nota": f"pesa más: {r['domina']}"})
    html += svg_dumbbell("¿Manda el mineral o la guardia? Varianza explicada (η²) del resultado",
                         filas, lab_a="mineral", lab_b="guardia")
    return html


def sec_piscina():
    html = ""
    # E10e: nivel de piscina y FIT_114 en tercio ALTA vs BAJA de recuperación
    filas_n, filas_f = [], []
    for esp in ESP:
        M = _csv(esp, "E10e_metricas_secundarias_recuperacion.csv")
        if M is None:
            continue
        if "nivel_piscina" in M.index:
            r = M.loc["nivel_piscina"]
            filas_n.append({"esp": esp, "etiqueta": f"{esp} · nivel piscina %", "a": r["mediana_a"],
                            "b": r["mediana_b"], "nota": "relevante" if r["relevante"] else "no relevante"})
        if "FIT_114" in M.index:
            r = M.loc["FIT_114"]
            filas_f.append({"esp": esp, "etiqueta": f"{esp} · FIT_114", "a": r["mediana_a"],
                            "b": r["mediana_b"], "nota": "relevante" if r["relevante"] else "no relevante"})
    html += svg_dumbbell("Nivel de piscina cuando ESTE espesador recupera más (ALTA) vs menos (BAJA)", filas_n)
    html += svg_dumbbell("FIT_114 (flujo hacia piscinas) cuando ESTE espesador recupera más vs menos", filas_f)

    # Episodios de piscina baja: vel_descarga indexada a piscina sana = 100
    xs, vel, niv = None, {}, {}
    for esp in ESP:
        P = _interim(f"piscina_baja_{esp.replace('-', '')}_perfil.csv")
        B = _interim(f"piscina_baja_{esp.replace('-', '')}_base.csv")
        if P is None or B is None or "vel_descarga" not in P.columns:
            continue
        xs = list(P.index)
        sana = float(B.loc["vel_descarga", "sana"])
        vel[esp] = [100 * v / sana for v in P["vel_descarga"]]
        if "nivel_piscina" in P.columns:
            niv[esp] = list(P["nivel_piscina"])
    if xs:
        html += svg_lineas("Velocidad de descarga tras cruzar la piscina bajo 75 % (índice: piscina sana = 100)",
                           vel, xs, "índice", ref=100, ref_lab="piscina sana", xlab="min desde el cruce")
        html += svg_lineas("Nivel de piscina en esos mismos episodios (%)", niv, xs, "%",
                           ref=75, ref_lab="R1 = 75 %", xlab="min desde el cruce", alto=180)

    # Ventana cuando la piscina / FIT_114 están en su tercio alto (E10f)
    for clave, tit in (("ventana_piscina_alta", "cuando la piscina está en su tercio ALTO"),
                       ("ventana_fit114_alta", "cuando FIT_114 está en su tercio ALTO")):
        for rol, nombre in (("flujo_alim", "Flujo de alimentación"),
                            ("valvula_alim", "Válvula de alimentación"),
                            ("vel_descarga", "Bomba de descarga")):
            filas = []
            for esp in ESP:
                H = _json(esp, "E10f_hipotesis_piscina_valvula.json").get(clave, {})
                v = H.get(_tag(esp, rol))
                if v:
                    filas.append({"esp": esp, "min": v["min"], "max": v["max"], "objetivo": v["mediana"],
                                  "actual": v["mediana"], "escala_min": v["min"], "escala_max": v["max"],
                                  "nota": _tag(esp, rol)})
            html += svg_rangos(f"{nombre} {tit}", filas)
    return html


def sec_valvula():
    html = ""
    # E10d: válvula / floculante / presión de cama en tercio ALTA vs BAJA
    filas = []
    for esp in ESP:
        D = _csv(esp, "E10d_prueba_variables_candidatas.csv")
        if D is None:
            continue
        for rol, etq in (("valvula_alim", "válvula"), ("floculante", "floculante"),
                         ("presion_cama", "presión de cama")):
            tag = _tag(esp, rol)
            if tag in D.index:
                r = D.loc[tag]
                nota = ("→ objetivo" if r["clase_nueva"] == "objetivo" else "sin efecto") + \
                       (" (relevante)" if r["relevante"] else "")
                filas.append({"esp": esp, "etiqueta": f"{esp} · {etq}", "a": r["mediana_a"],
                              "b": r["mediana_b"], "nota": nota})
    html += svg_dumbbell("Válvula, floculante y presión de cama en el tercio de mejor (●) vs peor (○) recuperación",
                         filas)

    # Episodios de molienda: válvula absoluta y flujo indexado a base = 100
    for tipo, tit in (("parada_parcial", "parada PARCIAL de molienda (un molino cae, el otro sigue)"),
                      ("parada_total", "parada TOTAL de molienda")):
        xs, valv, flujo, moli = None, {}, {}, {}
        for esp in ESP:
            P = _interim(f"atoro_{tipo}_{esp.replace('-', '')}_perfil.csv")
            B = _interim(f"atoro_{tipo}_{esp.replace('-', '')}_base.csv")
            if P is None or B is None:
                continue
            xs = list(P.index)
            tv, tf = _tag(esp, "valvula_alim"), _tag(esp, "flujo_alim")
            if tv in P.columns:
                valv[esp] = list(P[tv])
            if tf in P.columns:
                flujo[esp] = [100 * v / float(B.loc[tf, "base"]) for v in P[tf]]
            if "_molienda_total" in P.columns and esp == ESP[0]:
                moli["molienda"] = [100 * v / float(B.loc["_molienda_total", "base"])
                                    for v in P["_molienda_total"]]
        if not xs:
            continue
        html += svg_lineas(f"Apertura de válvula tras {tit} (%)", valv, xs, "% apertura",
                           xlab="min desde que vuelve la molienda")
        html += svg_lineas(f"Flujo de alimentación tras {tit} (índice: operación estable = 100)",
                           flujo, xs, "índice", ref=100, ref_lab="estable",
                           xlab="min desde que vuelve la molienda")
    # correlación parcial válvula~flujo
    cats, vals = [], {}
    for esp in ESP:
        cp = _json(esp, "E10f_hipotesis_piscina_valvula.json").get("corr_parcial_valvula_flujo_alim")
        if cp is not None:
            cats.append(esp)
    if cats:
        serie = {esp: [_json(esp, "E10f_hipotesis_piscina_valvula.json")["corr_parcial_valvula_flujo_alim"]]
                 for esp in cats}
        html += svg_barras("Correlación parcial válvula ~ flujo de alimentación (controlando tonelaje de molino; "
                           "negativa = compatible con atoro compensado)",
                           cats, serie, "corr. parcial", alto=170, por_categoria=True)
    return html


def sec_trenes():
    cats, wt, rec = ["TREN 1", "TREN 2"], {}, {}
    notas = []
    for esp in ESP:
        T = _csv(esp, "E11a_trenes_crudo.csv")
        if T is None:
            continue
        wt[esp] = [float(T.loc[c, "wt_activo"]) if c in T.index else np.nan for c in cats]
        rec[esp] = [float(T.loc[c, "recuperacion"]) if c in T.index else np.nan for c in cats]
        E = _csv(esp, "E11b_trenes_emparejado.csv")
        if E is not None and "gana" in E.columns:
            g = E["gana"].value_counts()
            notas.append(f"{esp}: gana {g.idxmax()} en {g.max()}/{g.sum()} celdas emparejadas")
    html = svg_barras("% sólidos de descarga por tren", cats, wt, "% sólidos", alto=190)
    html += svg_barras("Recuperación por tren (%)", cats, rec, "% recup.", alto=190)
    html += "<p class='nota-txt'>" + " · ".join(notas) + "</p>" if notas else ""
    return html


def kpis():
    celdas = []
    for esp in ESP:
        A = _csv(esp, "E10a_brecha_por_mineral.csv")
        E = _csv(esp, "E11b_trenes_emparejado.csv")
        if A is None:
            continue
        rb, ra, gm = A["rec_baja"].mean(), A["rec_alta"].mean(), A["brecha_m3h"].mean()
        tren = ""
        if E is not None and "gana" in E.columns:
            g = E["gana"].value_counts()
            tren = f"{g.idxmax()} · {g.max()}/{g.sum()}"
        celdas.append(f"""<div class="kpi"><div class="kesp" style="border-color:{PLOMO[esp]}">
          <svg width="16" height="16" viewBox="0 0 16 16" style="vertical-align:middle">{marcador(esp, 8, 8, 5)}</svg> {esp}</div>
          <div class="kv">{rb:.0f} → {ra:.0f}<small>% recup.</small></div>
          <div class="kv2">+{gm:.0f}<small>m³/h</small> · {tren}</div></div>""")
    return "".join(celdas)


CSS = """
:root{--paper:#E8E8E3;--panel:#F5F5F1;--ink:#15181B;--steel:#6C757E;--hair:#C4C5BF;
--mono:'IBM Plex Mono',ui-monospace,monospace;--disp:'Barlow Condensed','Arial Narrow',sans-serif;
--body:'Inter',-apple-system,'Segoe UI',sans-serif}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--paper);color:var(--ink);font-family:var(--body);font-size:13px;line-height:1.45;padding:22px 16px}
.sheet{max-width:980px;margin:0 auto;background:var(--panel);border:1px solid var(--hair);box-shadow:0 2px 14px rgba(20,24,28,.09)}
.head{padding:20px 26px 14px;border-bottom:2px solid var(--ink);display:flex;flex-wrap:wrap;gap:16px;align-items:flex-end}
.head h1{font-family:var(--disp);font-weight:700;font-size:30px;line-height:.98;text-transform:uppercase;flex:1 1 340px}
.head h1 span{display:block;font-size:13px;font-weight:500;letter-spacing:.13em;color:var(--steel);margin-bottom:5px}
.meta{font-family:var(--mono);font-size:10.5px;color:var(--steel);text-align:right;line-height:1.7}
.kpis{display:flex;flex-wrap:wrap;border-bottom:1px solid var(--hair);background:#EFEFEB}
.kpi{flex:1 1 200px;padding:12px 26px;border-right:1px solid var(--hair)}.kpi:last-child{border-right:none}
.kesp{font-family:var(--mono);font-size:10px;letter-spacing:.08em;color:var(--steel);border-left:3px solid;padding-left:8px;margin-bottom:4px}
.kesp svg,.kesp circle,.kesp rect,.kesp polygon{vertical-align:middle}
.kv{font-family:var(--disp);font-size:26px;font-weight:700;line-height:1}
.kv small,.kv2 small{font-family:var(--mono);font-size:10px;font-weight:500;color:var(--steel);margin-left:3px}
.kv2{font-family:var(--mono);font-size:11px;color:var(--steel);margin-top:3px}
.sec{padding:16px 26px 8px;border-top:1px solid var(--hair)}
.sec h2{font-family:var(--disp);font-size:19px;font-weight:600;text-transform:uppercase;letter-spacing:.045em}
.sec .lead{font-size:11px;color:var(--steel);margin:2px 0 8px}
.ch{width:100%;height:auto;display:block;margin:6px 0 10px;font-family:var(--mono)}
.ch .t{font-size:11.5px;font-weight:600;fill:var(--ink)}.ch .u,.ch .lg{font-size:9.5px;fill:var(--steel)}
.ch .lab{font-size:10px;font-weight:600;fill:var(--ink)}.ch .v{font-size:9.5px;fill:var(--steel)}
.ch .v.hi{font-weight:700}.ch .ax{font-size:9px;fill:#9AA0A6}.ch .nota{font-size:9px;fill:var(--steel)}
.ch .rail{stroke:#DCDCD6;stroke-width:1}.ch .grid{stroke:#DCDCD6;stroke-width:1}
.nota-txt{font-family:var(--mono);font-size:10px;color:var(--steel);margin:0 0 8px}
.foot{border-top:2px solid var(--ink);padding:12px 26px 16px;font-size:10.5px;color:var(--steel);line-height:1.5}
.foot li{margin-left:14px}
@media print{body{background:#fff;padding:0}.sheet{box-shadow:none;border:none;max-width:none}@page{size:A4 portrait;margin:9mm}}
"""


def generar(archivo=None):
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M")
    html = f"""<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ventanas operativas consolidadas · Espesadores C2</title>
<link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;600;700&family=IBM+Plex+Mono:wght@400;600&family=Inter:wght@400;600&display=swap" rel="stylesheet">
<style>{CSS}</style></head><body><div class="sheet">
<header class="head"><h1><span>Ventanas operativas para el sistema experto · consolidado</span>
Espesadores de relaves C2 · TH-001 / TH-002 / TH-003</h1>
<div class="meta">Generado {fecha}<br>Dataset <b>recorded</b>, grilla 1 min, 2024-07-14 → 2026-09-15<br>
● TH-001 &nbsp;■ TH-002 &nbsp;▲ TH-003 &nbsp;·&nbsp; <span style="color:{MAX}">▲máx</span> / <span style="color:{MIN}">mín▼</span> entre espesadores</div></header>
<div class="kpis">{kpis()}</div>

<section class="sec"><h2>1 · Ventanas operativas — todos los parámetros, los tres espesadores</h2>
<p class="lead">Barra = rango objetivo (p10–p90 del tercio de mejor recuperación, dentro de cada tipo de mineral) ·
marca negra = valor a apuntar · marcador hueco = valor actual · a la derecha, el tag y su clase (objetivo / bomba / sin efecto, decidida con datos en E10).</p>
{sec_ventanas()}</section>

<section class="sec"><h2>2 · Nivel de piscina y rebose</h2>
<p class="lead">La piscina y FIT_114 son de planta (reciben rebose de los tres espesadores más agua externa FIT_123/FIT_601): corroboran, no se atribuyen en exclusiva.
Los episodios de piscina baja (&lt; 75 %, R1) se alinean en el minuto en que cruzan el umbral.</p>
{sec_piscina()}</section>

<section class="sec"><h2>3 · Válvula y flujo de alimentación</h2>
<p class="lead">Arriba: ¿la válvula y el floculante se mueven entre el tercio de mejor y peor recuperación? (prueba por permutación con piso de relevancia).
Abajo: qué hacen la válvula y el flujo en las 3 h siguientes a que vuelve la molienda, alineando todos los episodios (10–240 min) en t = 0.</p>
{sec_valvula()}</section>

<section class="sec"><h2>4 · Influencia del tipo de mineral</h2>
<p class="lead">Tipos de mineral = regímenes de alimentación inferidos (E08), no tipos verificados con el plan de mina. La brecha ALTA–BAJA existe dentro de cada tipo.</p>
{sec_mineral()}</section>

<section class="sec"><h2>5 · Trenes de bombeo</h2>
{sec_trenes()}</section>

<footer class="foot"><ul>
<li>Todo sale de las salidas E09–E11 de cada espesador (<code>data/06_reporting/TH00X/</code>) y de los análisis por episodios (<code>src/espesadores/dominio/atoro_alimentacion.py</code>, <code>piscina_episodios.py</code>). Ningún número está escrito a mano.</li>
<li>Rebose recalculado desde el balance de agua (E05), no del estimador del DCS. Los one-pagers individuales conservan el detalle de cada espesador.</li>
<li>Pruebas de válvula/piscina son correlacionales y contemporáneas; no establecen causalidad. Ver <code>docs/bitacora_hallazgos.md</code> N-12 y N-13.</li>
</ul></footer></div></body></html>"""
    archivo = archivo or os.path.join(RUTAS["salidas"], "onepager_consolidado.html")
    with open(archivo, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[one-pager consolidado] {archivo}")
    return archivo


if __name__ == "__main__":
    generar()
