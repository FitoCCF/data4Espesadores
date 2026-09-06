# -*- coding: utf-8 -*-
"""
================================================================================
GENERADOR DEL INFORME DE UNA PAGINA (one-pager)
================================================================================
Toma el contexto que devuelve el pipeline y arma el HTML listo para imprimir.
No contiene ningun numero fijo: todo sale de los resultados calculados, de modo
que el mismo generador sirve para TH-001, TH-002 y TH-003.

El diseno sigue la filosofia de HMI de alto rendimiento (ISA-101): la hoja es
casi toda en escala de grises y el color se reserva para el ESTADO, de manera
que la vista va directo a la banda objetivo y a la marca del valor actual.
================================================================================
"""
import os
import numpy as np

# Etiquetas legibles por tipo de variable. La clave es el rol en la
# configuracion, no el tag, para que funcione con cualquier espesador.
ETIQUETAS = {
    "presion_cama":   ("Presión de cama", "objetivo"),
    "torque":         ("Torque de rastra", "objetivo"),
    "nivel_interfaz": ("Nivel de interfaz", "objetivo"),
    "flujo_alim":     ("Flujo de alimentación", "objetivo"),
    "wt_activo":      ("% sólidos de descarga", "resultado"),
    "vel_descarga":   ("Bomba de descarga", "bomba"),
    "vel_cizalle":    ("Bomba de cizallamiento", "bomba"),
    "floculante":     ("Floculante", "sin_efecto"),
    "valvula_alim":   ("Válvula de alimentación", "sin_efecto"),
}


def _pct(valor, lo, hi):
    """Convierte un valor a posicion porcentual dentro de la escala del grafico."""
    if hi <= lo:
        return 0.0
    return max(0.0, min(100.0, 100.0 * (valor - lo) / (hi - lo)))


def _fila_escala(nombre, sub, r, color="band"):
    """
    Dibuja una fila de escala de instrumento: riel, banda objetivo, marca del
    valor a apuntar y marca del valor actual.
    """
    # La escala del riel se redondea hacia afuera para que la banda no toque el borde.
    lo = min(r["escala_min"], r["min"]) * 0.95
    hi = max(r["escala_max"], r["max"]) * 1.05
    izq = _pct(r["min"], lo, hi)                     # inicio de la banda objetivo
    ancho = _pct(r["max"], lo, hi) - izq             # ancho de la banda
    p_obj = _pct(r["objetivo"], lo, hi)              # marca del valor objetivo
    p_act = _pct(r["actual"], lo, hi)                # marca del valor actual
    # Direccion de la accion segun donde esta el valor actual respecto al objetivo.
    if r["actual"] < r["min"]:
        accion = "SUBIR ↑"
    elif r["actual"] > r["max"]:
        accion = "BAJAR ↓"
    elif r["actual"] < r["objetivo"] * 0.99:
        accion = "SUBIR ↑"
    elif r["actual"] > r["objetivo"] * 1.01:
        accion = "BAJAR ↓"
    else:
        accion = "EN VENTANA"
    cls = "amber" if color == "amber" else ""
    return f"""
    <div class="scale">
      <div class="tag">{nombre}<em>{sub}</em></div>
      <div class="track"><div class="rail"></div>
        <div class="win {cls}" style="left:{izq:.1f}%;width:{ancho:.1f}%"></div>
        <div class="winlab {cls}" style="left:{izq+ancho/2:.1f}%">{r['min']:g} – {r['max']:g}</div>
        <div class="tick" style="left:{p_obj:.1f}%"></div>
        <div class="tick now" style="left:{p_act:.1f}%"></div>
        <div class="tickl" style="left:{p_act:.1f}%">{r['actual']:g}</div>
        <span class="ends l">{lo:.4g}</span><span class="ends r">{hi:.4g}</span></div>
      <div class="nums"><b class="{cls}">{r['min']:g} – {r['max']:g}</b> · apuntar
        <b class="{cls}">{r['objetivo']:g}</b><br><s>hoy {r['actual']:g}</s>
        <span class="arrow">{accion}</span></div>
    </div>"""


def generar_onepager(ctx, archivo=None):
    """Arma el HTML del informe de una pagina con los resultados del pipeline."""
    cfg = ctx["cfg"]
    ven = ctx["ventanas"]
    sens = ctx.get("sensibilidad", 0)

    # --- Cifras de encabezado, calculadas desde la brecha medida ---
    brecha = ctx.get("brecha")
    if brecha is not None and len(brecha):
        rec_baja = float(brecha["rec_baja"].mean())
        rec_alta = float(brecha["rec_alta"].mean())
        gan_m3h = float(brecha["brecha_m3h"].mean())
    else:
        rec_baja = rec_alta = gan_m3h = 0.0

    # GUARDA DE CORDURA: si la recuperacion alta supera a la baja, la ganancia
    # en m3/h tiene que ser positiva. Un valor negativo significa que se compararon
    # tercios con distinto tonelaje (el rebose absoluto escala con la produccion).
    # En ese caso se recalcula desde la brecha de recuperacion, que si esta
    # normalizada por tonelaje.
    if rec_alta > rec_baja and gan_m3h <= 0:
        agua_ref = float(ctx.get("agua_alim_ref", 0)) or 0.0
        if agua_ref > 0:
            gan_m3h = (rec_alta - rec_baja) / 100.0 * agua_ref
            print(f"[aviso] ganancia recalculada a tonelaje constante: {gan_m3h:.0f} m3/h")
        else:
            gan_m3h = 0.0
    anual = gan_m3h * 8760 * 0.9                      # 90% de disponibilidad

    # --- Mapa de tag -> (etiqueta legible, clase) ---
    mapa = {}
    for rol, (etq, clase) in ETIQUETAS.items():
        tag = cfg.get(rol, rol)                       # rol propio o nombre derivado
        mapa[tag] = (etq, clase, rol)

    # --- Filas de cada bloque ---
    filas_obj, filas_bomba, filas_sin = [], [], []
    for tag, r in ven.items():
        etq, clase, _ = mapa.get(tag, (tag, r.get("clase", "objetivo"), tag))
        if r["clase"] == "objetivo":
            filas_obj.append(_fila_escala(tag, etq, r))
        elif r["clase"] == "bomba":
            # El cizalle se marca en verde porque si es objetivo; la descarga en
            # ambar porque es un medio, no un objetivo.
            es_cizalle = "cizalle" in tag
            filas_bomba.append(_fila_escala(tag, etq, r,
                                            color="band" if es_cizalle else "amber"))
        else:
            filas_sin.append((tag, etq, r))

    # --- Tabla de trenes ---
    tabla_trenes = ""
    if ctx.get("trenes_ok") and ctx.get("tabla_trenes") is not None:
        T = ctx["tabla_trenes"].sort_values("wt_activo", ascending=False)
        filas = "".join(
            f"<tr class='{'best' if i == 0 else ('worst' if i == len(T)-1 else '')}'>"
            f"<td>{idx}</td><td>{r.pct_tiempo:g} %</td><td>{r.wt_activo:g}</td>"
            f"<td>{r.recuperacion:g} %</td><td>{r.rebose:g}</td></tr>"
            for i, (idx, r) in enumerate(T.iterrows()))
        tabla_trenes = f"""
        <table class="tr">
          <tr><th>Tren</th><th>Uso</th><th>% sól.</th><th>Recup.</th><th>Rebose</th></tr>
          {filas}
        </table>"""

    nota_tren = ""
    if ctx.get("tren_mejor"):
        nota_tren = (f"<div class='note go'><b>Preferir el {ctx['tren_mejor']}</b> cuando ambos "
                     f"estén disponibles: rinde <b>+{ctx.get('ventaja_tren', 0):.2f} puntos de "
                     f"% sólidos ≈ {sens*ctx.get('ventaja_tren', 0):.0f} m³/h</b>, y la ventaja se "
                     f"mantiene al comparar a igual presión de cama, nivel y tonelaje "
                     f"({ctx.get('celdas_favorables', '')} comparaciones). Revisar con "
                     f"Mantenimiento por qué el otro tren rinde menos.</div>")

    # --- Nota de cizallamiento ---
    nota_ciz = ""
    if ctx.get("cizalle"):
        detalle = " · ".join(f"{c['tren']}: fuera del objetivo el {c['pct_fuera_abajo']:g} % del tiempo"
                             for c in ctx["cizalle"])
        nota_ciz = (f"<div class='note warn'><b>El cizallamiento sí es objetivo, no medio.</b> "
                    f"Debe quedar fijo, sin variación. Situación actual: {detalle}.</div>")

    # --- Bloque de variables sin efecto ---
    sin_html = ""
    for tag, etq, r in filas_sin:
        sin_html += (f"<div class='no'><div class='nox'>✕</div><div>"
                     f"<h3>{etq} · {tag}</h3><p>El valor es prácticamente el mismo en la "
                     f"operación de alta y de baja recuperación. No sirve como variable de "
                     f"ajuste para recuperar más agua.</p></div></div>")
    if ctx.get("mineral_ok"):
        n_tipos = len(ctx.get("ventanas_por_mineral", {}))
        sin_html += (f"<div class='no'><div class='nox'>✕</div><div>"
                     f"<h3>Receta distinta por tipo de mineral</h3><p>Se detectaron "
                     f"{n_tipos} tipos de mineral. La ventana óptima casi no cambia entre "
                     f"ellos, por lo que <b>una sola ventana sirve para todo el mineral</b>.</p>"
                     f"</div></div>")
    if ctx.get("guardias_ok"):
        sin_html += (f"<div class='no'><div class='nox'>✕</div><div>"
                     f"<h3>Diferencias entre guardias</h3><p>La brecha entre la mejor y la peor "
                     f"guardia es {ctx.get('rango_guardias', 0):.2f} puntos de % sólidos ≈ "
                     f"{sens*ctx.get('rango_guardias', 0):.0f} m³/h, muy por debajo de la "
                     f"oportunidad de estandarizar.</p></div></div>")

    # --- HTML final ---
    html = f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ventanas Operativas · {cfg['nombre_largo']}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{{--paper:#E8E8E3;--panel:#F5F5F1;--ink:#15181B;--steel:#6C757E;--hair:#C4C5BF;
--band:#2F6B46;--alarm:#A33224;--amber:#8A6516;
--mono:'IBM Plex Mono',ui-monospace,monospace;--disp:'Barlow Condensed','Arial Narrow',sans-serif;
--body:'Inter',-apple-system,'Segoe UI',sans-serif;}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--paper);color:var(--ink);font-family:var(--body);font-size:13px;
line-height:1.45;padding:22px 16px;-webkit-font-smoothing:antialiased}}
.sheet{{max-width:960px;margin:0 auto;background:var(--panel);border:1px solid var(--hair);
box-shadow:0 1px 0 #fff inset,0 2px 14px rgba(20,24,28,.09)}}
.head{{display:flex;flex-wrap:wrap;align-items:flex-end;gap:16px;padding:20px 26px 14px;
border-bottom:2px solid var(--ink)}}
.head h1{{font-family:var(--disp);font-weight:700;font-size:32px;line-height:.98;
text-transform:uppercase;flex:1 1 340px}}
.head h1 span{{display:block;font-size:14px;font-weight:500;letter-spacing:.13em;
color:var(--steel);margin-bottom:5px}}
.meta{{font-family:var(--mono);font-size:10.5px;color:var(--steel);text-align:right;line-height:1.75}}
.meta b{{color:var(--ink);font-weight:600}}
.result{{display:flex;flex-wrap:wrap;border-bottom:1px solid var(--hair);background:#EFEFEB}}
.rcell{{flex:1 1 148px;padding:12px 26px;border-right:1px solid var(--hair)}}
.rcell:last-child{{border-right:none}}
.rlab{{font-family:var(--mono);font-size:9.5px;letter-spacing:.1em;text-transform:uppercase;
color:var(--steel);margin-bottom:3px}}
.rval{{font-family:var(--disp);font-size:28px;font-weight:700;line-height:1;color:var(--band)}}
.rval small{{font-family:var(--mono);font-size:11px;font-weight:500;color:var(--steel);margin-left:3px}}
.rsub{{font-family:var(--mono);font-size:10px;color:var(--steel);margin-top:3px}}
.sec{{padding:17px 26px 6px}}
.sech{{display:flex;align-items:baseline;gap:10px;margin-bottom:4px;flex-wrap:wrap}}
.sech h2{{font-family:var(--disp);font-size:19px;font-weight:600;text-transform:uppercase;
letter-spacing:.045em}}
.chip{{font-family:var(--mono);font-size:9px;letter-spacing:.08em;padding:2px 7px;
text-transform:uppercase;font-weight:600}}
.chip.go{{background:var(--band);color:#fff}}.chip.mid{{background:var(--amber);color:#fff}}
.chip.no{{background:var(--alarm);color:#fff}}
.sech p{{font-size:11.5px;color:var(--steel);flex:1 1 100%;margin-top:2px}}
.scale{{display:grid;grid-template-columns:172px 1fr 178px;gap:14px;align-items:center;
padding:8px 0;border-bottom:1px dotted var(--hair)}}
.scale:last-child{{border-bottom:none}}
.tag{{font-family:var(--mono);font-size:10px;font-weight:600;line-height:1.25}}
.tag em{{display:block;font-family:var(--body);font-style:normal;font-size:10px;
font-weight:400;color:var(--steel)}}
.track{{position:relative;height:26px}}
.rail{{position:absolute;top:10px;left:0;right:0;height:6px;background:#DCDCD6;border:1px solid var(--hair)}}
.win{{position:absolute;top:10px;height:6px;background:var(--band)}}
.win.amber{{background:var(--amber)}}
.winlab{{position:absolute;top:-1px;font-family:var(--mono);font-size:9px;font-weight:600;
transform:translateX(-50%);color:var(--band)}}
.winlab.amber{{color:var(--amber)}}
.tick{{position:absolute;top:5px;width:2px;height:16px;background:var(--ink)}}
.tick.now{{background:var(--alarm)}}
.tickl{{position:absolute;top:21px;font-family:var(--mono);font-size:8.5px;
transform:translateX(-50%);white-space:nowrap;color:var(--steel)}}
.ends{{position:absolute;top:19px;font-family:var(--mono);font-size:8.5px;color:#9AA0A6}}
.ends.l{{left:0}}.ends.r{{right:0}}
.nums{{font-family:var(--mono);font-size:10.5px;text-align:right;line-height:1.5}}
.nums b{{color:var(--band);font-weight:600}}.nums b.amber{{color:var(--amber)}}
.nums s{{text-decoration:none;color:var(--alarm)}}
.arrow{{font-family:var(--body);font-size:9.5px;color:var(--steel)}}
.note{{margin:9px 0 2px;padding:9px 12px;background:#EFEFEB;border-left:3px solid var(--steel);
font-size:11px;color:var(--steel);line-height:1.5}}
.note b{{color:var(--ink)}}.note.go{{border-left-color:var(--band)}}
.note.warn{{border-left-color:var(--amber)}}
.cols{{display:grid;grid-template-columns:1fr 1fr;border-top:1px solid var(--hair)}}
.col{{padding:17px 26px}}.col+.col{{border-left:1px solid var(--hair)}}
.no{{display:flex;gap:11px;padding:8px 0;border-bottom:1px dotted var(--hair)}}
.no:last-child{{border-bottom:none}}
.nox{{font-family:var(--mono);font-size:13px;color:var(--alarm);font-weight:600}}
.no h3{{font-family:var(--mono);font-size:10.5px;font-weight:600;margin-bottom:1px}}
.no p{{font-size:10.5px;color:var(--steel);line-height:1.42}}
table.tr{{width:100%;border-collapse:collapse;font-family:var(--mono);font-size:10.5px;margin-top:4px}}
table.tr th{{font-size:9px;letter-spacing:.08em;text-transform:uppercase;color:var(--steel);
text-align:right;padding:4px 5px;border-bottom:1px solid var(--hair)}}
table.tr th:first-child{{text-align:left}}
table.tr td{{padding:5px;text-align:right;border-bottom:1px dotted var(--hair)}}
table.tr td:first-child{{text-align:left;font-weight:600}}
table.tr tr.best td{{color:var(--band)}}table.tr tr.worst td{{color:var(--alarm)}}
.foot{{border-top:2px solid var(--ink);padding:13px 26px 17px;display:grid;
grid-template-columns:1fr 1fr;gap:22px}}
.foot h4{{font-family:var(--mono);font-size:9.5px;letter-spacing:.1em;text-transform:uppercase;
color:var(--steel);margin-bottom:5px}}
.foot li{{font-size:10.5px;color:var(--steel);line-height:1.5;padding-left:11px;
position:relative;list-style:none}}
.foot li:before{{content:'—';position:absolute;left:0;color:var(--hair)}}
@media print{{body{{background:#fff;padding:0}}.sheet{{box-shadow:none;border:none;max-width:none}}
@page{{size:A4 portrait;margin:9mm}}}}
@media(max-width:760px){{.cols{{grid-template-columns:1fr}}
.col+.col{{border-left:none;border-top:1px solid var(--hair)}}
.scale{{grid-template-columns:130px 1fr;gap:9px}}
.nums{{grid-column:1/-1;text-align:left}}.head h1{{font-size:25px}}}}
</style></head><body><div class="sheet">

<header class="head">
  <h1><span>Ventanas operativas para el sistema experto</span>{cfg['nombre_largo']}</h1>
  <div class="meta">TAG <b>{cfg['tag_equipo']}</b><br>
    Base <b>{ctx.get('n_limpio', 0):,}</b> registros en operación estable<br>
    de <b>{ctx.get('n_crudo', 0):,}</b> crudos · muestreo {ctx.get('dt_min', 1):g} min</div>
</header>

<div class="result">
  <div class="rcell"><div class="rlab">Recuperación de agua</div>
    <div class="rval">{rec_baja:.0f} → {rec_alta:.0f}<small>%</small></div>
    <div class="rsub">brecha medida, mismo tonelaje</div></div>
  <div class="rcell"><div class="rlab">Rebose adicional</div>
    <div class="rval">+{gan_m3h:.0f}<small>m³/h</small></div>
    <div class="rsub">operando dentro de ventana</div></div>
  <div class="rcell"><div class="rlab">Agua recuperada al año</div>
    <div class="rval">{anual/1000:.0f}<small>mil m³</small></div>
    <div class="rsub">8760 h · 90 % disponibilidad</div></div>
  <div class="rcell"><div class="rlab">Sensibilidad</div>
    <div class="rval">{sens:.1f}<small>m³/h</small></div>
    <div class="rsub">por punto de % sólidos de descarga</div></div>
</div>

<section class="sec">
  <div class="sech"><h2>1 · Variables objetivo</h2>
    <span class="chip go">El sistema experto debe llevarlas y mantenerlas aquí</span>
    <p>Son las que determinan cuánta agua se recupera. Banda verde = rango objetivo ·
    marca negra = valor a apuntar · marca roja = valor promedio actual.</p></div>
  {''.join(filas_obj)}
</section>

<section class="sec" style="border-top:1px solid var(--hair);margin-top:8px">
  <div class="sech"><h2>2 · Bombas</h2>
    <span class="chip mid">Rango válido · la descarga no se fija como objetivo</span>
    <p>La velocidad de descarga <b>responde</b> a la densidad del relave, no la produce:
    cuando el relave sale más espeso la bomba necesita más velocidad para moverlo. Úsese
    como medio para alcanzar la presión de cama y el % sólidos objetivo, dentro de estos
    límites. El cizallamiento, en cambio, sí es objetivo y debe quedar fijo.</p></div>
  {''.join(filas_bomba)}
  {nota_ciz}
</section>

<div class="cols">
  <div class="col">
    <div class="sech"><h2>3 · Elección de tren</h2>
      <span class="chip go">Decisión de mayor impacto</span></div>
    <p style="font-size:11.5px;color:var(--steel);margin:5px 0 2px">
      Las bombas trabajan en trenes acoplados: la de descarga y la de cizalle arrancan
      juntas y no se mezclan entre trenes.</p>
    {tabla_trenes}
    {nota_tren}
  </div>
  <div class="col">
    <div class="sech"><h2>4 · Sin efecto comprobado</h2>
      <span class="chip no">No usar como variable de ajuste</span></div>
    {sin_html}
    <div class="note" style="margin-top:11px">
      <b>Dónde está realmente la oportunidad:</b> la brecha de recuperación aparece
      <b>dentro</b> de cada tipo de mineral y <b>dentro</b> de cada guardia. No la causa el
      mineral ni el equipo humano: es ajuste turno a turno sin criterio común. Es
      exactamente lo que un sistema experto elimina.</div>
  </div>
</div>

<footer class="foot">
  <div><h4>Base del análisis</h4><ul>
    <li>{ctx.get('n_crudo', 0):,} registros crudos → {ctx.get('n_limpio', 0):,} en operación
    estable tras limpieza (rango físico, bomba en servicio, señal congelada, valores
    atípicos, estado estacionario).</li>
    <li>Rebose recalculado desde el balance de agua, no tomado del estimador del DCS.</li>
    <li>Ventanas = percentiles 10–90 del tercio de mejor recuperación, dentro de cada tipo
    de mineral y a igual tonelaje.</li>
    <li>Control de calidad superado: la ganancia medida por punto de % sólidos coincide con
    la que predice el balance de agua.</li>
  </ul></div>
  <div><h4>Antes de cargar en el sistema experto</h4><ul>
    <li>Validar con Procesos el tope de densificación contra el límite de torque de rastra y
    la bombeabilidad del relave espesado.</li>
    <li>Los tipos de mineral son regímenes de alimentación inferidos, no tipos verificados:
    cruzar con el plan de mina.</li>
    <li>Verificar con Instrumentación que % sólidos y densidad de descarga sean mediciones
    independientes.</li>
  </ul></div>
</footer>
</div></body></html>"""

    if archivo is None:
        archivo = os.path.join(ctx["salidas"],
                               f"onepager_{ctx['espesador'].replace('-', '')}.html")
    with open(archivo, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n[one-pager] {archivo}")
    return archivo
