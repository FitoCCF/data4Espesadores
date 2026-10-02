# -*- coding: utf-8 -*-
"""
onepager_recuperacion.py
================================================================================
One-pager "explicado simple": con qué valores de cada parámetro recupera MÁS
agua cada espesador, por tren (pedido del usuario 2026-09-17). Lee las
salidas de dominio/recuperacion_parametros.py (`pixi run recuperacion`) y
muestra, para cada parámetro, la ventana del tercio de recuperación ALTA
contra la mediana del tercio BAJA, seis filas (espesador × tren).

Incluye la fórmula del balance de agua con el NOMBRE DE CADA TAG tal como
está en tags.yaml (columna y tag PI), y una tabla de todos los tags usados.

Mismo lenguaje visual que onepager_flujo_piscinas.py (reutiliza sus SVG).

Uso:
    PYTHONPATH=src python -m espesadores.reportes.onepager_recuperacion
"""
import os
from datetime import datetime

import numpy as np
import pandas as pd

from espesadores.config import ESPESADORES, GLOBALES, PROCESO, RUTAS
from espesadores.dominio.recuperacion_parametros import COLUMNA_A_TAG, tags_usados
from espesadores.reportes.onepager_consolidado import CSS, INK, MAX, MIN, STEEL, _f
from espesadores.reportes.onepager_flujo_piscinas import (CSS_EXTRA, FILAS, PARAMETROS, _get, leyenda_svg,
                                                          svg_parametro)

CARPETA = os.path.join(RUTAS["salidas"], "recuperacion")
ESTADOS = ("ALTA", "BAJA", "MEDIA")
ETQ = ("ALTA", "BAJA")
BALANCE = [
    ("recuperacion", "Recuperación de agua", "fracción del agua que entra y sale por el rebose (0–1); es lo que ordena los tercios", "fracción"),
    ("rebose", "Rebose calculado", "agua que sale por arriba, en m³/h (depende del tonelaje)", "m³/h"),
    ("agua_alim", "Agua que entra", "agua de dilución + agua de la pulpa", "m³/h"),
    ("agua_descarga", "Agua que se va con el lodo", "menos agua aquí = más agua recuperada", "m³/h"),
    ("ton_espesador", "Tonelaje del espesador", "sólidos que le tocan a este espesador (ojo: si cambia, la recuperación cambia sola)", "t/h"),
]
PLANTA = [
    ("nivel_piscina", "Nivel de piscina", "cuánta agua hay en la piscina", "%"),
    ("flujo_piscinas", "Flujo hacia piscinas (FIT_114)", "el agua que vuelve a la piscina", "m³/h"),
    ("tanques_prom", "Tanques temporales (prom. TK001/TK002)", "nivel promedio de los dos tanques", "%"),
    ("molienda_total", "Molienda total", "cuánto muelen los dos molinos", "t/h"),
]


def cargar():
    ruta = os.path.join(CARPETA, "parametros_por_tren.csv")
    if not os.path.exists(ruta):
        raise SystemExit(f"Falta {ruta}: correr antes `pixi run recuperacion`")
    return pd.read_csv(ruta), pd.read_csv(os.path.join(CARPETA, "tercios.csv"))


def _tag(col):
    return COLUMNA_A_TAG.get(col, col)


# ------------------------------------------------------------------ bloques de texto
def formula_html():
    """La fórmula E05 con los tags de cada espesador, tal como están en tags.yaml."""
    filas = []
    for esp, cfg in ESPESADORES.items():
        t1, t2 = cfg["trenes"]
        filas.append(f"""<div class="form"><b>{esp}</b> (<code>{cfg['tag_equipo']}</code>)<br>
<code>parte</code> = <code>{cfg['flujo_alim']}</code> ÷ (<code>{cfg['flujos_todos'][0]}</code> + <code>{cfg['flujos_todos'][1]}</code> + <code>{cfg['flujos_todos'][2]}</code>)
&nbsp;→ tag PI <code>{_tag(cfg['flujo_alim'])}</code><br>
<code>ton</code> = <code>{GLOBALES['alim_total_molino']}</code> × <code>parte</code>
&nbsp;→ tag PI <code>{_tag(GLOBALES['alim_total_molino'])}</code><br>
<code>wt_activo</code> = <code>{t1['wt']}</code> si <code>{t1['descarga']}</code> &gt; {PROCESO['umbral_bomba_on']:g} (Tren 1) · <code>{t2['wt']}</code> si <code>{t2['descarga']}</code> &gt; {PROCESO['umbral_bomba_on']:g} (Tren 2)
&nbsp;→ tags PI <code>{_tag(t1['wt'])}</code> / <code>{_tag(t2['wt'])}</code>, <code>{_tag(t1['descarga'])}</code> / <code>{_tag(t2['descarga'])}</code><br>
<code>agua_entra</code> = <code>{cfg['agua_dilucion']}</code> × {PROCESO['factor_dilucion']:g} + <code>ton</code> × (100 ÷ {PROCESO['sol_alim_default']:g} − 1)
&nbsp;→ tag PI <code>{_tag(cfg['agua_dilucion'])}</code>; el {PROCESO['sol_alim_default']:g} % es fijo porque <code>{GLOBALES['sol_overflow']}</code> no existe en PI<br>
<code>agua_sale</code> = <code>ton</code> × (100 ÷ <code>wt_activo</code> − 1)<br>
<code>rebose</code> = <code>agua_entra</code> − <code>agua_sale</code> &nbsp;·&nbsp; <b><code>recuperacion</code> = <code>rebose</code> ÷ <code>agua_entra</code></b></div>""")
    return "".join(filas)


def tabla_tags():
    out = ['<table class="tb tags"><thead><tr><th>espesador</th><th>rol (nombre en el gráfico)</th><th>columna en tags.yaml</th><th>tag PI</th><th>qué es</th></tr></thead><tbody>']
    for esp in ESPESADORES:
        for rol, col, tag, desc in tags_usados(esp):
            out.append(f"<tr><td>{esp}</td><td>{rol}</td><td><code>{col}</code></td><td><code>{tag or '(derivado)'}</code></td><td>{desc[:90]}</td></tr>")
    out.append("</tbody></table>")
    return "".join(out)


def kpis(res, tercios):
    out = []
    for _, r in tercios.iterrows():
        esp = r.espesador
        a = [_get(res, esp, t, "recuperacion", "ALTA") for t in ("TREN 1", "TREN 2")]
        b = [_get(res, esp, t, "recuperacion", "BAJA") for t in ("TREN 1", "TREN 2")]
        ra = np.nanmean([x["p50"] for x in a if x is not None])
        rb = np.nanmean([x["p50"] for x in b if x is not None])
        out.append(f'<div class="kpi"><div class="kesp" style="border-color:{INK}">{esp} · RECUPERACIÓN</div>'
                   f'<div class="kv">{100*ra:.1f}<small>% tercio ALTA</small></div>'
                   f'<div class="kv2">{100*rb:.1f} % tercio BAJA · mediana {100*r.rec_mediana:.1f} % · cortes {100*r.corte_baja_media:.1f} / {100*r.corte_media_alta:.1f} %</div></div>')
    return "".join(out)


def conclusiones(res):
    nombres = {rol: n for rol, n, _f_, _u in PARAMETROS}
    por_rol = {}
    for rol, nombre, _fr, _u in PARAMETROS:
        for esp, tren in FILAS:
            a, b = _get(res, esp, tren, rol, "ALTA"), _get(res, esp, tren, rol, "BAJA")
            if a is None or b is None or b["p50"] == 0:
                continue
            d = 100 * (a["p50"] - b["p50"]) / abs(b["p50"])
            if abs(d) >= 3:
                por_rol.setdefault(rol, []).append((esp, tren, a["p50"], b["p50"], d))
    # consistentes: mismo signo en >= 4 de 6 trenes
    consist, mixtos = [], []
    for rol, v in por_rol.items():
        signos = [np.sign(x[4]) for x in v]
        if len(v) >= 4 and abs(sum(signos)) == len(v):
            consist.append((rol, v))
        else:
            mixtos.append((rol, v))
    def frase(rol, v):
        sube = v[0][4] > 0
        rango = f"{min(x[3] for x in v):.1f}–{max(x[3] for x in v):.1f} → {min(x[2] for x in v):.1f}–{max(x[2] for x in v):.1f}"
        return f"<b>{nombres[rol]}</b> {'más alto' if sube else 'más bajo'} en {len(v)} de 6 trenes (BAJA → ALTA: {rango})"
    f1 = ("Lo que se repite en casi todos los trenes cuando la recuperación es ALTA: " + "; ".join(frase(r, v) for r, v in consist) + ".") if consist else "Ningún parámetro se mueve en la misma dirección en la mayoría de los trenes."
    f2 = ("Cambia, pero no siempre en la misma dirección (depende del espesador/tren): " + "; ".join(
        f"<b>{nombres[r]}</b> (" + ", ".join(f"{e} T{t[-1]}: {_f(a)} vs {_f(b)} ({'+' if d > 0 else ''}{d:.0f} %)" for e, t, a, b, d in v) + ")" for r, v in mixtos) + ".") if mixtos else ""
    quietos = [nombres[r].lower() for r, _n, _fr, _u in PARAMETROS if r not in por_rol]
    f3 = ("No cambian (menos de 3 % en todos los trenes): " + ", ".join(quietos) + ".") if quietos else "Todos los parámetros cambian al menos 3 % en algún tren."
    # tonelaje
    ton = []
    for esp, tren in FILAS:
        a, b = _get(res, esp, tren, "ton_espesador", "ALTA"), _get(res, esp, tren, "ton_espesador", "BAJA")
        if a is not None and b is not None:
            ton.append(f"{esp} T{tren[-1]} {_f(a['p50'],0)} vs {_f(b['p50'],0)}")
    f4 = "Cuidado con el tonelaje (ALTA vs BAJA, t/h): " + "; ".join(ton) + ". Donde ALTA tiene mucho menos tonelaje, parte de la 'mejor recuperación' es solo que entra menos sólido, no que el espesador trabaje mejor."
    return f1, f2, f3, f4


CSS_REC = """
.form{font-family:var(--mono);font-size:10.5px;line-height:1.75;background:#EFEFEB;border-left:3px solid #6C757E;padding:8px 12px;margin:6px 0}
.form code{background:#E3E3DE;padding:0 3px;border-radius:2px}
.tb.tags td{text-align:left;font-size:9.5px}.tb.tags th{text-align:left}
"""


def generar(archivo=None):
    res, tercios = cargar()
    f1, f2, f3, f4 = conclusiones(res)
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M")
    kw = dict(sigla="recuperación", estados=ESTADOS, etq=ETQ)
    g_bal = "".join(svg_parametro(res, *p, **kw) for p in BALANCE)
    g_par = "".join(svg_parametro(res, *p, **kw) for p in PARAMETROS)
    g_pla = "".join(svg_parametro(res, *p, **kw) for p in PLANTA)
    html = f"""<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cómo recuperar más agua</title>
<meta name="description" content="Con qué valores de cada parámetro recupera más agua cada espesador (TH-001/002/003), por tren, con la fórmula y los tags de tags.yaml.">
<link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;600;700&family=IBM+Plex+Mono:wght@400;600&family=Inter:wght@400;600&display=swap" rel="stylesheet">
<style>{CSS}{CSS_EXTRA}{CSS_REC}</style></head><body><div class="sheet">
<header class="head"><h1><span>Explicado simple · todos los parámetros, por tren, con los tags de tags.yaml</span>
¿Con qué valores recupera más agua cada espesador?</h1>
<div class="meta">Generado {fecha}<br>Dataset <b>recorded</b>, grilla 1 min, 2024-07-14 → 2026-09-15<br>
● TH-001 &nbsp;■ TH-002 &nbsp;▲ TH-003 &nbsp;·&nbsp; liso = Tren 1, rayado = Tren 2 &nbsp;·&nbsp; <span style="color:{MAX}">▲ más alta</span> / <span style="color:{MIN}">▼ más baja</span></div></header>
<div class="kpis">{kpis(res, tercios)}</div>

<section class="sec"><h2>0 · Cómo medimos "recuperar agua", en simple</h2>
<div class="eli">Un espesador recibe pulpa (agua + sólidos) y la separa: el lodo espeso sale por abajo con las bombas y el agua limpia sale por arriba (rebose) hacia los tanques y la piscina.
<b>Recuperar agua = que salga la mayor parte del agua por arriba y la menor con el lodo.</b><br><br>
El tag del DCS que "mide" el rebose (<code>FLUJO_REBOSE_AGUA_TH*</code>) está congelado el 67 % del tiempo, así que <b>no lo usamos</b>: calculamos el rebose con un balance de agua
(lo que entra menos lo que se va con el lodo), minuto a minuto, a partir de tags que sí se miden. Cuanto más espeso sale el lodo (<code>wt_activo</code> alto), menos agua se va con él y más se recupera.<br><br>
Luego, para cada espesador, ordenamos todos los minutos por recuperación y los partimos en tres: <b>BAJA</b>, <b>MEDIA</b> y <b>ALTA</b>. Los gráficos muestran <b>en qué valor estaba cada parámetro en el tercio ALTA</b> (barra = donde estuvo casi siempre, raya negra = valor típico)
contra el valor típico del tercio <b>BAJA</b> (marcador hueco). Si la barra y el marcador están separados, ese parámetro acompaña la buena recuperación. Solo minutos con planta moliendo (&gt; 100 t/h) y un tren en servicio.</div>
<div class="leg">{leyenda_svg()}</div>
<div class="sub">La fórmula, con el nombre de cada tag (columna de tags.yaml → tag PI)</div>
{formula_html()}
<p class="nota-txt">Es la misma fórmula de E05 del pipeline. El % de sólidos de la alimentación se asume {PROCESO['sol_alim_default']:g} % (el DCS hace lo mismo) porque <code>{GLOBALES['sol_overflow']}</code> no existe en PI; eso mueve el nivel de la recuperación pero no cuál minuto es mejor que otro.
El tonelaje viene de <code>{GLOBALES['alim_total_molino']}</code> (Molino 1) repartido por flujo, igual que en el pipeline.</p></section>

<section class="sec"><h2>1 · El balance de agua en cada tercio</h2>
<p class="lead">Barra = p10–p90 en el tercio ALTA · raya negra = mediana ALTA · marcador hueco = mediana BAJA. Mira primero el tonelaje: si en ALTA es mucho menor, parte de la mejora es solo menos sólido entrando.</p>
{g_bal}</section>

<section class="sec"><h2>2 · Todos los parámetros de cada espesador, por tren: ALTA recuperación vs BAJA</h2>
<p class="lead">Seis filas por gráfico. En ámbar la mediana ALTA más alta de las seis y en azul la más baja; a la derecha, cuánto cambia ALTA respecto de BAJA.</p>
{g_par}</section>

<section class="sec"><h2>3 · Y la planta mientras tanto</h2>
<p class="lead">Las mismas seis filas: cómo estaban la piscina, FIT_114, los tanques y la molienda en los minutos de recuperación ALTA de cada espesador·tren, contra los de BAJA.</p>
{g_pla}</section>

<section class="sec"><h2>4 · Conclusión, en simple</h2>
<div class="eli">1. {f1}<br>2. {f2}<br>3. {f3}<br>4. {f4}</div></section>

<section class="sec"><h2>5 · Todos los tags que se usaron (como están en tags.yaml)</h2>
{tabla_tags()}</section>

<footer class="foot"><ul>
<li>Fuente: <code>pixi run recuperacion</code> → <code>data/06_reporting/recuperacion/parametros_por_tren.csv</code>, <code>tercios.csv</code>, <code>tags_usados.csv</code>. Ningún número está escrito a mano.</li>
<li>Tercios calculados por espesador sobre sus minutos válidos (balance coherente: recuperación entre 0 y 1, rebose entre 0 y 5 000 m³/h). Celdas fuera del rango físico de <code>calidad.yaml</code> anuladas (regla E03). A diferencia de E10, aquí no se parte por tipo de mineral.</li>
<li>Es una foto estadística: dice con qué valores coincide la buena recuperación, no prueba que moverlos la cause. Las ventanas por tipo de mineral y con prueba estadística están en el one-pager consolidado (sección 1).</li>
</ul></footer></div></body></html>"""
    archivo = archivo or os.path.join(CARPETA, "onepager_recuperacion.html")
    with open(archivo, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[one-pager recuperacion] {archivo}")
    return archivo


if __name__ == "__main__":
    generar()
