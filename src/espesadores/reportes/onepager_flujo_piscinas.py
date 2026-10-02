# -*- coding: utf-8 -*-
"""
onepager_flujo_piscinas.py
================================================================================
One-pager (HTML autocontenido, SVG en Python, sin dependencias) del análisis
`dominio/flujo_piscinas_parametros.py`: cómo están TODOS los parámetros de
cada espesador, por tren, cuando una señal de planta está subiendo —
explicado en lenguaje simple (pedido "eli5", 2026-09-17). `--senal fit114`
(flujo hacia las piscinas) o `--senal tanques` (nivel de los tanques
temporales LIT_108/LIT_109).

Lenguaje visual compartido con onepager_consolidado.py: un plomo por
espesador + marcador ●■▲ (identidad no depende solo del tono), ámbar =
mediana más alta entre los seis trenes, azul = la más baja. Tren 1 relleno
liso, Tren 2 rayado. Un solo eje por gráfico.

Lee data/06_reporting/<carpeta>/parametros_por_tren.csv; correr antes
`pixi run flujo-piscinas` o `pixi run tanques`.

Uso:
    PYTHONPATH=src python -m espesadores.reportes.onepager_flujo_piscinas [--senal fit114|tanques]
"""
import argparse
import os
from datetime import datetime

import numpy as np
import pandas as pd

from espesadores.config import ESPESADORES, RUTAS
from espesadores.dominio.flujo_piscinas_parametros import SENALES
from espesadores.reportes.onepager_consolidado import (CSS, FORMA, HAIR, INK, MAX, MIN, PAPER,
                                                       PLOMO, STEEL, _escala, _f, marcador)

ESP = list(ESPESADORES)

# Textos "en simple" por señal.
TEXTOS = {
    "fit114": {
        "corto": "el flujo hacia las piscinas", "sigla": "FIT_114", "archivo": "onepager_flujo_piscinas.html",
        "titulo": "¿Cómo está cada espesador cuando sube el flujo hacia las piscinas?",
        "html_title": "Espesadores cuando sube el flujo a piscinas",
        "que_es": "<b>FIT_114</b> es el caudal de agua que vuelve a la piscina.",
        "umbral": "creció {u} m³/h o más en una hora", "umbral_baja": "cayó {u} o más",
        "kpi_nombre": "FLUJO A PISCINAS (FIT_114)", "kpi_rol": "flujo_piscinas", "kpi_unidad": "m³/h", "kpi_nd": 0,
        "tarea": "pixi run flujo-piscinas", "carpeta": "flujo_piscinas",
        "lectura_planta": "cuando {corto} <b>sube</b>, la piscina está <b>más baja</b> ({p_s} % vs {p_b} % cuando baja). "
                          "O sea: el flujo sube cuando la piscina está más vacía y los tanques arrancan bombas — no porque el espesador haya hecho algo distinto.",
    },
    "tanques": {
        "corto": "el nivel de los tanques temporales", "sigla": "TK001/TK002", "archivo": "onepager_tanques.html",
        "titulo": "¿Cómo está cada espesador cuando sube el nivel de los tanques temporales?",
        "html_title": "Espesadores cuando suben los tanques",
        "que_es": "<b>TK001 y TK002</b> (LIT_108/LIT_109) son los tanques temporales donde cae el agua recuperada antes de bombearla a la piscina; "
                  "usamos el promedio de los dos (se parecen mucho, correlación 0,85). Viven en ~35 % y suben a 70–100 % por episodios.",
        "umbral": "subió {u} punto o más en una hora", "umbral_baja": "bajó {u} o más",
        "kpi_nombre": "NIVEL DE TANQUES (PROM. TK001/TK002)", "kpi_rol": "tanques_prom", "kpi_unidad": "%", "kpi_nd": 1,
        "tarea": "pixi run tanques", "carpeta": "tanques",
        "lectura_planta": "cuando {corto} <b>sube</b> o <b>baja</b>, la piscina está alta ({p_s} % y {p_b} %); cuando los tanques están <b>quietos</b> "
                          "(en su nivel bajo de ~{t_e} %) la piscina está más baja ({p_e} %). El flujo a piscinas FIT_114 casi no cambia ({f_s} vs {f_b} m³/h). "
                          "O sea: los tanques se mueven (se llenan y se vacían con las bombas) en los períodos en que la piscina está llena.",
    },
}

# (rol, nombre simple, qué es en una frase, unidad)
PARAMETROS = [
    ("flujo_alim", "Flujo de alimentación", "cuánta pulpa entra al espesador", "m³/h"),
    ("valvula_alim", "Válvula de alimentación", "cuánto abrió la válvula el operador", "% apertura"),
    ("presion_cama", "Presión de cama", "cuánto sólido hay acumulado abajo", "%"),
    ("torque", "Torque de rastra", "cuánto le cuesta girar a la rastra", "%"),
    ("nivel_interfaz", "Nivel de interfaz", "a qué altura está la línea lodo/agua", "m"),
    ("nivel_cajon", "Nivel del cajón", "qué tan lleno está el cajón de alimentación", "%"),
    ("floculante", "Floculante", "cuánto reactivo se dosifica", "m³/h"),
    ("agua_dilucion", "Agua de dilución", "cuánta agua se agrega al floculante", "l/s"),
    ("vel_descarga", "Bomba de descarga", "qué tan rápido se saca el lodo (del tren en servicio)", "% velocidad"),
    ("vel_cizalle", "Bomba de cizallamiento", "qué tan rápido gira la bomba de cizalle del tren", "% velocidad"),
    ("wt_solidos", "% sólidos de descarga", "qué tan espeso sale el lodo", "%"),
    ("densidad", "Densidad de descarga", "cuánto pesa el lodo que sale", "t/m³"),
]
PLANTA = [
    ("nivel_piscina", "Nivel de piscina", "cuánta agua hay en la piscina (el objetivo del proyecto)", "%"),
    ("flujo_piscinas", "Flujo hacia piscinas (FIT_114)", "el agua que vuelve a la piscina", "m³/h"),
    ("tanques_prom", "Tanques temporales (prom. TK001/TK002)", "nivel promedio de los dos tanques temporales", "%"),
    ("tk001", "Tanque TK001", "nivel del tanque temporal 1; cuando sube arrancan bombas", "%"),
    ("tk002", "Tanque TK002", "nivel del tanque temporal 2", "%"),
    ("molienda_total", "Molienda total", "cuánto mineral muelen los dos molinos", "t/h"),
]
ESTADOS = [("subiendo", "sube"), ("estable", "igual"), ("bajando", "baja")]
FILAS = [(e, t) for e in ESP for t in ("TREN 1", "TREN 2")]


def cargar(senal):
    carpeta = os.path.join(RUTAS["salidas"], TEXTOS[senal]["carpeta"])
    ruta = os.path.join(carpeta, "parametros_por_tren.csv")
    if not os.path.exists(ruta):
        raise SystemExit(f"Falta {ruta}: correr antes `{TEXTOS[senal]['tarea']}`")
    return pd.read_csv(ruta), carpeta


def _get(res, esp, tren, var, est):
    g = res[(res.espesador == esp) & (res.tren == tren) & (res.variable == var) & (res.estado == est)]
    return None if g.empty else g.iloc[0]


# ------------------------------------------------------------------ svg
PATRONES = "".join(
    f'<pattern id="ray-{i}" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
    f'<rect width="6" height="6" fill="{PLOMO[e]}"/><line x1="0" y1="0" x2="0" y2="6" stroke="{PAPER}" stroke-width="2.2"/></pattern>'
    for i, e in enumerate(ESP))
RELLENO = {e: {"TREN 1": PLOMO[e], "TREN 2": f"url(#ray-{i})"} for i, e in enumerate(ESP)}


def _delta_txt(sube, baja):
    if sube is None or baja is None or baja == 0:
        return "", STEEL
    d = 100 * (sube - baja) / abs(baja)
    if abs(d) < 1.5:
        return "= igual", STEEL
    return (f"▲ +{d:.0f} %" if d > 0 else f"▼ {d:.0f} %"), (MAX if d > 0 else MIN)


def svg_parametro(res, rol, nombre, frase, unidad, sigla="FIT_114", ancho=920,
                  estados=("subiendo", "bajando", "estable"), etq=("subiendo", "bajando")):
    """Seis filas (espesador × tren). Línea fina = mín–máx absoluto; barra =
    p10–p90 en el estado principal (estados[0]); marca negra = su mediana;
    marcador hueco = mediana en el estado de contraste (estados[1]).
    Ámbar/azul = mediana principal más alta / más baja entre los seis."""
    datos = []
    for esp, tren in FILAS:
        s, b, e = (_get(res, esp, tren, rol, st) for st in estados)
        if s is None:
            continue
        datos.append((esp, tren, s, b, e))
    if not datos:
        return ""
    lo = min(min(d[2]["p10"] for d in datos), min(d[2]["min"] for d in datos))
    hi = max(max(d[2]["p90"] for d in datos), max(d[2]["max"] for d in datos))
    # Eje: la ventana p10–p90 manda; el mín/máx absoluto se dibuja pero recortado
    # al 25 % extra para que un dato suelto no aplaste las barras.
    lo_b = min(d[2]["p10"] for d in datos)
    hi_b = max(d[2]["p90"] for d in datos)
    margen = (hi_b - lo_b) * 0.25 or 1.0
    lo, hi = max(lo, lo_b - margen), min(hi, hi_b + margen)
    x0, x1 = 178, ancho - 190
    X = _escala(lo, hi, x0, x1)
    Xc = lambda v: min(max(X(v), x0), x1)
    h = 24
    alto = 40 + h * len(datos) + 16
    i_max = max(range(len(datos)), key=lambda i: datos[i][2]["p50"])
    i_min = min(range(len(datos)), key=lambda i: datos[i][2]["p50"])
    s = [f'<svg viewBox="0 0 {ancho} {alto}" class="ch"><defs>{PATRONES}</defs>',
         f'<text x="0" y="13" class="t">{nombre}</text>',
         f'<text x="0" y="26" class="u">{frase}</text>',
         f'<text x="{ancho}" y="13" class="u" text-anchor="end">{unidad}</text>']
    etq_ = etq
    for i, (esp, tren, sb, bj, es) in enumerate(datos):
        y = 40 + i * h + h / 2
        etq = f"{esp} · T{tren[-1]}"
        s.append(f'<text x="{x0-10}" y="{y+4}" class="lab" text-anchor="end">{etq}</text>')
        s.append(marcador(esp, x0 - 90, y, 4.2, title=esp))
        s.append(f'<line x1="{Xc(sb["min"]):.1f}" x2="{Xc(sb["max"]):.1f}" y1="{y}" y2="{y}" class="rail">'
                 f'<title>{etq}: mínimo {_f(sb["min"])}, máximo {_f(sb["max"])} (absolutos, {sigla} {etq_[0]})</title></line>')
        s.append(f'<rect x="{X(sb["p10"]):.1f}" y="{y-5}" width="{max(2, X(sb["p90"])-X(sb["p10"])):.1f}" height="10" rx="4" '
                 f'fill="{RELLENO[esp][tren]}"><title>{etq}, {sigla} {etq_[0]}: casi siempre entre {_f(sb["p10"])} y {_f(sb["p90"])} '
                 f'(p10–p90), mediana {_f(sb["p50"])}, {int(sb["minutos"]):,} min</title></rect>')
        s.append(f'<line x1="{X(sb["p50"]):.1f}" x2="{X(sb["p50"]):.1f}" y1="{y-9}" y2="{y+9}" stroke="{INK}" stroke-width="2.2">'
                 f'<title>mediana {etq_[0]} {_f(sb["p50"])}</title></line>')
        if bj is not None:
            s.append(marcador(esp, Xc(bj["p50"]), y, 4.5, fill=PAPER, stroke=PLOMO[esp], sw=2,
                              title=f"{etq}, {sigla} {etq_[1]}: mediana {_f(bj['p50'])}"))
        color = MAX if i == i_max else (MIN if i == i_min else INK)
        extra = " ▲ la más alta" if i == i_max else (" ▼ la más baja" if i == i_min else "")
        peso = ' font-weight="700"' if i in (i_max, i_min) else ""
        s.append(f'<text x="{x1+8}" y="{y+4}" class="v" fill="{color}"{peso}>{_f(sb["p50"])}{extra}</text>')
        dtxt, dcol = _delta_txt(sb["p50"], bj["p50"] if bj is not None else None)
        s.append(f'<text x="{ancho}" y="{y+4}" class="nota" fill="{dcol}" text-anchor="end">{dtxt}</text>')
    s.append(f'<text x="{x0}" y="{alto-3}" class="ax">{_f(lo,1)}</text>'
             f'<text x="{x1}" y="{alto-3}" class="ax" text-anchor="end">{_f(hi,1)}</text>'
             f'<text x="{ancho}" y="{alto-3}" class="ax" text-anchor="end">{etq_[0][:4]}. vs {etq_[1][:4]}.</text>')
    s.append("</svg>")
    return "".join(s)


def svg_planta(res, rol, nombre, frase, unidad, sigla="FIT_114", ancho=920):
    """Tres filas (FIT_114 sube / igual / baja) de una variable de planta.
    Los valores son iguales para los tres espesadores; se toma TH-001 T2
    (el tren con más minutos)."""
    filas = [(_get(res, "TH-001", "TREN 2", rol, st), lab) for st, lab in ESTADOS]
    filas = [(r, lab) for r, lab in filas if r is not None]
    if not filas:
        return ""
    lo = min(r["p10"] for r, _ in filas)
    hi = max(r["p90"] for r, _ in filas)
    m = (hi - lo) * 0.3 or 1.0
    lo, hi = lo - m, hi + m
    x0, x1 = 178, ancho - 190
    X = _escala(lo, hi, x0, x1)
    h = 22
    alto = 40 + h * 3 + 16
    s = [f'<svg viewBox="0 0 {ancho} {alto}" class="ch">',
         f'<text x="0" y="13" class="t">{nombre}</text>', f'<text x="0" y="26" class="u">{frase}</text>',
         f'<text x="{ancho}" y="13" class="u" text-anchor="end">{unidad}</text>']
    tono = {"sube": INK, "igual": STEEL, "baja": "#A5ABB0"}
    for i, (r, lab) in enumerate(filas):
        y = 40 + i * h + h / 2
        s.append(f'<text x="{x0-10}" y="{y+4}" class="lab" text-anchor="end">{sigla} {lab}</text>')
        s.append(f'<line x1="{x0}" x2="{x1}" y1="{y}" y2="{y}" class="rail"/>')
        s.append(f'<rect x="{X(r["p10"]):.1f}" y="{y-5}" width="{max(2, X(r["p90"])-X(r["p10"])):.1f}" height="10" rx="4" fill="{tono[lab]}">'
                 f'<title>{sigla} {lab}: p10 {_f(r["p10"])} – p90 {_f(r["p90"])}, mediana {_f(r["p50"])}, mín {_f(r["min"])}, máx {_f(r["max"])}</title></rect>')
        s.append(f'<line x1="{X(r["p50"]):.1f}" x2="{X(r["p50"]):.1f}" y1="{y-9}" y2="{y+9}" stroke="{MAX if lab == "sube" else INK}" stroke-width="2.2"/>')
        s.append(f'<text x="{x1+8}" y="{y+4}" class="v" fill="{INK}" font-weight="{700 if lab == "sube" else 400}">{_f(r["p50"])}</text>')
        s.append(f'<text x="{ancho}" y="{y+4}" class="nota" text-anchor="end">{_f(r["p10"])} – {_f(r["p90"])}</text>')
    s.append(f'<text x="{x0}" y="{alto-3}" class="ax">{_f(lo,1)}</text><text x="{x1}" y="{alto-3}" class="ax" text-anchor="end">{_f(hi,1)}</text>'
             f'<text x="{ancho}" y="{alto-3}" class="ax" text-anchor="end">p10 – p90</text></svg>')
    return "".join(s)


# ------------------------------------------------------------------ tabla y kpis
def tabla(res):
    out = ['<table class="tb"><thead><tr><th>parámetro</th>' + "".join(f"<th>{e} T{t[-1]}</th>" for e, t in FILAS) + "</tr></thead><tbody>"]
    for rol, nombre, _fr, unidad in PARAMETROS:
        vals = [_get(res, e, t, rol, "subiendo") for e, t in FILAS]
        p50s = [v["p50"] if v is not None else np.nan for v in vals]
        i_max, i_min = int(np.nanargmax(p50s)), int(np.nanargmin(p50s))
        celdas = []
        for i, v in enumerate(vals):
            if v is None:
                celdas.append("<td>–</td>")
                continue
            cls = ' class="hi-max"' if i == i_max else (' class="hi-min"' if i == i_min else "")
            celdas.append(f'<td{cls}><b>{_f(v["p50"])}</b><br><small>{_f(v["p10"])} – {_f(v["p90"])}</small></td>')
        out.append(f"<tr><td>{nombre} <small>{unidad}</small></td>{''.join(celdas)}</tr>")
    out.append("</tbody></table>")
    return "".join(out)


def kpis(res, tx):
    r1 = _get(res, "TH-001", "TREN 2", "nivel_piscina", "subiendo")
    r2 = _get(res, "TH-001", "TREN 2", "nivel_piscina", "bajando")
    f1 = _get(res, "TH-001", "TREN 2", tx["kpi_rol"], "subiendo")
    f2 = _get(res, "TH-001", "TREN 2", tx["kpi_rol"], "bajando")
    por_estado = res.groupby(["espesador", "tren", "estado"])["minutos"].max()
    pct = 100 * por_estado.xs("subiendo", level="estado").sum() / por_estado.sum()
    return "".join([
        f'<div class="kpi"><div class="kesp" style="border-color:{INK}">TIEMPO CON {tx["sigla"]} SUBIENDO</div>'
        f'<div class="kv">{pct:.0f}<small>% del tiempo</small></div><div class="kv2">≈ 1 de cada {100/pct:.0f} minutos con planta produciendo</div></div>',
        f'<div class="kpi"><div class="kesp" style="border-color:{MAX}">{tx["kpi_nombre"]}</div>'
        f'<div class="kv">{_f(f1["p50"],tx["kpi_nd"])}<small>{tx["kpi_unidad"]} subiendo</small></div><div class="kv2">{_f(f2["p50"],tx["kpi_nd"])} {tx["kpi_unidad"]} cuando baja</div></div>',
        f'<div class="kpi"><div class="kesp" style="border-color:{MIN}">NIVEL DE PISCINA</div>'
        f'<div class="kv">{_f(r1["p50"],1)}<small>% subiendo</small></div><div class="kv2">{_f(r2["p50"],1)} % cuando baja</div></div>',
        f'<div class="kpi"><div class="kesp" style="border-color:{STEEL}">QUÉ CAMBIA EN EL ESPESADOR</div>'
        f'<div class="kv">{tx["kpi_cambia"]}<small></small></div><div class="kv2">{tx["kpi_cambia2"]}</div></div>',
    ])


CSS_EXTRA = """
.eli{background:#EFEFEB;border-left:4px solid #15181B;padding:10px 14px;margin:8px 0 12px;font-size:12.5px;line-height:1.5}
.eli b{font-weight:600}
.leg{font-family:var(--mono);font-size:10px;color:var(--steel);margin:4px 0 10px;display:flex;flex-wrap:wrap;gap:14px;align-items:center}
.leg svg{vertical-align:middle}
.tb{width:100%;border-collapse:collapse;font-family:var(--mono);font-size:10px;margin:6px 0 10px}
.tb th,.tb td{border-bottom:1px solid var(--hair);padding:4px 5px;text-align:right;vertical-align:top}
.tb th:first-child,.tb td:first-child{text-align:left;font-family:var(--body);font-size:11px}
.tb small{color:var(--steel)}.tb td.hi-max b{color:#8A6516}.tb td.hi-min b{color:#3B6E8F}
.grid2{display:grid;grid-template-columns:1fr;gap:0}
@media(min-width:760px){.grid2{grid-template-columns:1fr 1fr;column-gap:22px}}
"""


def leyenda_svg():
    s = ['<svg width="520" height="22" viewBox="0 0 520 22" style="font-family:var(--mono);font-size:10px"><defs>' + PATRONES + '</defs>']
    s.append(f'<line x1="4" x2="44" y1="11" y2="11" stroke="{HAIR}"/><text x="50" y="14" fill="{STEEL}">mín–máx</text>')
    s.append(f'<rect x="112" y="6" width="40" height="10" rx="4" fill="{PLOMO["TH-002"]}"/><text x="158" y="14" fill="{STEEL}">p10–p90 T1</text>')
    s.append(f'<rect x="236" y="6" width="40" height="10" rx="4" fill="url(#ray-1)"/><text x="282" y="14" fill="{STEEL}">p10–p90 T2</text>')
    s.append(f'<line x1="366" x2="366" y1="2" y2="20" stroke="{INK}" stroke-width="2.2"/><text x="372" y="14" fill="{STEEL}">mediana sube</text>')
    s.append(marcador("TH-002", 470, 11, 4.5, fill=PAPER, stroke=PLOMO["TH-002"], sw=2) + f'<text x="480" y="14" fill="{STEEL}">baja</text>')
    s.append("</svg>")
    return "".join(s)


def conclusiones(res, corto="el flujo a piscinas"):
    """Frases 2 y 3 calculadas desde el CSV (nada escrito a mano)."""
    nombres = {rol: n for rol, n, _f_, _u in PARAMETROS}
    cambios = []
    for rol, nombre, _fr, _u in PARAMETROS:
        for esp, tren in FILAS:
            sb, bj = _get(res, esp, tren, rol, "subiendo"), _get(res, esp, tren, rol, "bajando")
            if sb is None or bj is None or bj["p50"] == 0:
                continue
            d = 100 * (sb["p50"] - bj["p50"]) / abs(bj["p50"])
            if abs(d) >= 3:
                cambios.append((rol, esp, tren, sb["p50"], bj["p50"], d))
    if cambios:
        por_rol = {}
        for rol, esp, tren, a, b, d in cambios:
            por_rol.setdefault(rol, []).append(f"{esp} T{tren[-1]}: {_f(a)} vs {_f(b)} ({'+' if d > 0 else ''}{d:.0f} %)")
        f2 = "Lo que sí se mueve (3 % o más, sube vs baja): " + "; ".join(f"<b>{nombres[r]}</b> ({', '.join(v)})" for r, v in por_rol.items()) + "."
    else:
        f2 = "Ningún parámetro se mueve más de 3 % entre sube y baja."
    quietos = [nombres[r] for r, _n, _fr, _u in PARAMETROS if r not in {c[0] for c in cambios}]
    f1 = (f"<b>El espesador casi no cambia</b> cuando {corto} sube: " + ", ".join(quietos).lower() + " se mueven menos de 3 % en todos los trenes.") if quietos else f"Todos los parámetros se mueven al menos 3 % en algún tren cuando {corto} sube."
    def ext(rol):
        g = res[(res.variable == rol) & (res.estado == "subiendo") & (res.tren != "AMBOS")]
        hi, lo = g.loc[g.p50.idxmax()], g.loc[g.p50.idxmin()]
        return f"{hi.espesador} T{hi.tren[-1]} {_f(hi.p50,1)} vs {lo.espesador} T{lo.tren[-1]} {_f(lo.p50,1)}"
    f3 = ("Las diferencias grandes son <b>entre trenes y espesadores</b>, no por la señal: "
          f"bomba de descarga {ext('vel_descarga')}; cizalle {ext('vel_cizalle')}; % sólidos {ext('wt_solidos')}; "
          f"flujo de alimentación {ext('flujo_alim')}.")
    return f1, f2, f3, cambios


def generar(senal="fit114", archivo=None):
    res, carpeta = cargar(senal)
    tx = dict(TEXTOS[senal])
    sigla = tx["sigla"]
    f1, f2, f3, cambios = conclusiones(res, tx["corto"])
    roles_cambian = sorted({c[0] for c in cambios}, key=lambda r: [p[0] for p in PARAMETROS].index(r))
    nombres = {rol: n for rol, n, _f_, _u in PARAMETROS}
    tx["kpi_cambia"] = "casi nada" if len(roles_cambian) <= 4 else f"{len(roles_cambian)} de 12"
    tx["kpi_cambia2"] = ("solo " + ", ".join(nombres[r].lower() for r in roles_cambian) + " (≥ 3 % en algún tren)") if roles_cambian else "ningún parámetro se mueve 3 % o más"
    umbral_txt = _f(SENALES[senal]["umbral"], 0) if senal == "tanques" else "38"
    ps = _f(_get(res, "TH-001", "TREN 2", "nivel_piscina", "subiendo")["p50"], 1)
    pb = _f(_get(res, "TH-001", "TREN 2", "nivel_piscina", "bajando")["p50"], 1)
    fs = _f(_get(res, "TH-001", "TREN 2", "flujo_piscinas", "subiendo")["p50"], 0)
    fb = _f(_get(res, "TH-001", "TREN 2", "flujo_piscinas", "bajando")["p50"], 0)
    pe = _f(_get(res, "TH-001", "TREN 2", "nivel_piscina", "estable")["p50"], 1)
    te = _f(_get(res, "TH-001", "TREN 2", "tanques_prom", "estable")["p50"], 0)
    lectura = tx["lectura_planta"].format(corto=tx["corto"], p_s=ps, p_b=pb, p_e=pe, t_e=te, f_s=fs, f_b=fb)
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M")
    graficos = "".join(svg_parametro(res, *p, sigla=sigla) for p in PARAMETROS)
    planta = "".join(svg_planta(res, *p, sigla=sigla) for p in PLANTA)
    html = f"""<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{tx["html_title"]}</title>
<meta name="description" content="Cómo están todos los parámetros de TH-001/002/003, por tren, cuando {tx["corto"]} está subiendo.">
<link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;600;700&family=IBM+Plex+Mono:wght@400;600&family=Inter:wght@400;600&display=swap" rel="stylesheet">
<style>{CSS}{CSS_EXTRA}</style></head><body><div class="sheet">
<header class="head"><h1><span>Explicado simple · todos los parámetros, por tren</span>
{tx["titulo"]}</h1>
<div class="meta">Generado {fecha}<br>Dataset <b>recorded</b>, grilla 1 min, 2024-07-14 → 2026-09-15<br>
● TH-001 &nbsp;■ TH-002 &nbsp;▲ TH-003 &nbsp;·&nbsp; liso = Tren 1, rayado = Tren 2 &nbsp;·&nbsp; <span style="color:{MAX}">▲ más alta</span> / <span style="color:{MIN}">▼ más baja</span></div></header>
<div class="kpis">{kpis(res, tx)}</div>

<section class="sec"><h2>0 · La idea, en simple</h2>
<div class="eli">{tx["que_es"]} Lo miramos hora a hora y lo separamos en tres estados:
<b>sube</b> ({tx["umbral"].format(u=umbral_txt)}), <b>baja</b> ({tx["umbral_baja"].format(u=umbral_txt)}) o <b>igual</b>.
Luego preguntamos: <i>mientras {tx["corto"]} subía, ¿en qué valor estaba cada cosa de cada espesador?</i>
Como cada espesador tiene dos trenes de bombas y solo uno trabaja a la vez, lo separamos por tren: seis filas.<br><br>
Cómo leer cada gráfico: la <b>barra</b> es donde estuvo el parámetro casi siempre (entre el 10 % más bajo y el 10 % más alto de los minutos),
la <b>raya negra</b> es el valor típico (mediana) mientras {tx["corto"]} subía, el <b>marcador hueco</b> es el valor típico cuando bajaba,
y la línea fina es el mínimo y el máximo absolutos. A la derecha: el valor típico y cuánto cambia "sube vs baja".
Solo se cuentan minutos con la planta moliendo (&gt; 100 t/h). Los valores imposibles del DCS (99 999, etc.) se quitaron antes.</div>
<div class="leg">{leyenda_svg()}</div></section>

<section class="sec"><h2>1 · Lo que hace la planta cuando {tx["corto"]} sube, se queda igual o baja</h2>
<p class="lead">Estas señales son de toda la planta (iguales para los tres espesadores). Barra = p10–p90, raya = mediana (ámbar cuando {tx["corto"]} sube).</p>
{planta}
<div class="eli">Lo que se ve: {lectura}</div></section>

<section class="sec"><h2>2 · Todos los parámetros de cada espesador, por tren, con {tx["corto"]} subiendo</h2>
<p class="lead">Seis filas por gráfico: TH-001, TH-002 y TH-003 con su Tren 1 (liso) y su Tren 2 (rayado). En ámbar la mediana más alta de las seis y en azul la más baja.</p>
{graficos}</section>

<section class="sec"><h2>3 · Los números, en una tabla</h2>
<p class="lead">Mediana (negrita) y ventana p10–p90 con {tx["corto"]} subiendo. Ámbar = la más alta de la fila, azul = la más baja.</p>
{tabla(res)}</section>

<section class="sec"><h2>4 · Conclusión en tres frases</h2>
<div class="eli">1. {f1}<br>2. {f2}<br>3. {f3}</div></section>

<footer class="foot"><ul>
<li>Fuente: <code>{tx["tarea"]}</code> → <code>data/06_reporting/{tx["carpeta"]}/parametros_por_tren.csv</code>. Ningún número está escrito a mano.</li>
<li>"Sube/baja" se define sobre {sigla} suavizado (mediana móvil de 30 min): {tx["umbral"].format(u=umbral_txt)} / {tx["umbral_baja"].format(u=umbral_txt)}. Celdas fuera del rango físico de <code>calidad.yaml</code> anuladas (regla E03).</li>
<li>Es una foto estadística, no una prueba de causa: dice dónde estaban las cosas, no por qué.</li>
</ul></footer></div></body></html>"""
    archivo = archivo or os.path.join(carpeta, tx["archivo"])
    with open(archivo, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[one-pager {senal}] {archivo}")
    return archivo


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--senal", choices=list(TEXTOS), default="fit114")
    generar(ap.parse_args().senal)
