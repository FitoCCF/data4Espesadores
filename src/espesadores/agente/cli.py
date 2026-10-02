# -*- coding: utf-8 -*-
"""
cli.py — punto de entrada del agente offline.

  pixi run agente estado
  pixi run agente preguntar "¿qué pasó con la piscina anoche?"
  pixi run agente chat                          # conversación interactiva
  pixi run agente informe --inicio -24h [--fin ahora] [--espesador TH-001]
  pixi run agente vigilar [--una-vez]           # ciclo cada N min (agente.yaml)
  pixi run agente reglas listar|validar|probar|proponer|pendientes|aprobar|rechazar
  pixi run agente herramienta <nombre> '{"json": "args"}'

`informe` y `vigilar` son determinísticos (reglas + estadística); si el LLM
local está disponible, agregan una redacción al final. `preguntar` y `chat`
requieren el LLM.
"""
import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from espesadores.config import AGENTE, ESPESADORES
from espesadores.agente import estadistica as E
from espesadores.agente import herramientas as H
from espesadores.agente import reglas as R


def log(msg=""):
    print(msg, flush=True)


# ============================================================================
# Informe determinístico
# ============================================================================
def informe(inicio, fin="ahora", espesadores=None, con_llm=True):
    """Reglas + resumen + anomalías + episodios para cada espesador y la
    planta. Devuelve dict serializable; imprime texto."""
    esps = espesadores or ["planta"] + list(ESPESADORES)
    out = {"generado": datetime.now().isoformat(timespec="minutes"), "inicio": inicio, "fin": fin,
           "hallazgos": [], "por_espesador": {}}
    for e in esps:
        bloque = {}
        ev = H.evaluar_reglas(e, inicio, fin)
        out["hallazgos"] += ev["hallazgos"]
        bloque["reglas"] = ev["texto"]
        bloque["resumen"] = H.resumen(e, inicio, fin)
        bloque["anomalias"] = H.anomalias(e, inicio, fin, max_items=8)
        if e == "planta":
            bloque["paradas_molienda"] = H.episodios("parada_molienda", inicio, fin)
            bloque["piscina_baja"] = H.episodios("piscina_baja", inicio, fin)
        else:
            bloque["valvula_movida"] = H.episodios("valvula_movida", inicio, fin, e)
            bloque["tren_cambio"] = H.episodios("tren_cambio", inicio, fin, e)
        out["por_espesador"][e] = bloque

    texto = [f"INFORME {inicio} -> {fin}  (generado {out['generado']})", ""]
    texto.append("HALLAZGOS DE REGLAS")
    texto.append(R.resumen_hallazgos(out["hallazgos"]))
    for e, b in out["por_espesador"].items():
        texto += ["", f"== {e} =="]
        r = b["resumen"]
        if r.get("planta_produciendo_pct") is not None:
            texto.append(f"planta produciendo {r['planta_produciendo_pct']} % del tiempo"
                         + (f", trenes activos (moda) {r['trenes_activos_moda']}" if e != "planta" and r.get("trenes_activos_moda") is not None else ""))
        for v, s in r["variables"].items():
            # Las variables de planta se listan una sola vez, bajo "planta".
            if e != "planta" and v in E.ROLES_PLANTA and "planta" in out["por_espesador"]:
                continue
            if s.get("p50") is None:
                texto.append(f"  {v:16s} sin dato")
                continue
            texto.append(f"  {v:16s} p50 {s['p50']:>9} [{s['p10']} – {s['p90']}]  inicio→fin {s['inicio_p50']} → {s['fin_p50']}  último {s['ultimo']}")
        a = b["anomalias"]
        if a["congelados"]:
            texto.append("  congelados: " + "; ".join(f"{x['variable']} {x['minutos']} min desde {x['inicio'][5:16]}" for x in a["congelados"][:5]))
        if a["cambios_de_regimen"]:
            texto.append("  escalones: " + "; ".join(f"{x['variable']} {x['antes_p50']}→{x['despues_p50']} @{x['instante'][5:16]}" for x in a["cambios_de_regimen"][:5]))
        for k in ("paradas_molienda", "piscina_baja", "valvula_movida", "tren_cambio"):
            if k in b and b[k]["n"]:
                texto.append(f"  {k}: {b[k]['n']} episodios ({b[k]['pct_tiempo']} % del tiempo)")
    out["texto"] = "\n".join(texto)

    if con_llm:
        from espesadores.agente.llm import LLMLocal
        llm = LLMLocal()
        if llm.disponible() and llm.modelo_cargado():
            try:
                out["redaccion"] = llm.redactar(f"Ventana: {inicio} -> {fin}.", out["texto"])
            except Exception as e:  # noqa: BLE001
                out["redaccion"] = f"(LLM no respondió: {e})"
        else:
            out["redaccion"] = None
    return out


def guardar_informe(out, carpeta):
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    marca = datetime.now().strftime("%Y%m%d_%H%M")
    (carpeta / f"informe_{marca}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    txt = out["texto"] + ("\n\nRESUMEN (LLM local)\n" + out["redaccion"] if out.get("redaccion") else "")
    (carpeta / f"informe_{marca}.txt").write_text(txt, encoding="utf-8")
    (carpeta / "ultimo_informe.txt").write_text(txt, encoding="utf-8")
    return carpeta / f"informe_{marca}.txt"


# ============================================================================
# Vigilancia
# ============================================================================
def vigilar(una_vez=False):
    cfg = AGENTE["vigilancia"]
    carpeta = Path(cfg["salidas"])
    carpeta.mkdir(parents=True, exist_ok=True)
    alertas = carpeta / "alertas.jsonl"
    vistas = set()
    if alertas.exists():
        for linea in alertas.read_text(encoding="utf-8").splitlines():
            try:
                h = json.loads(linea)
                vistas.add((h["regla"], h["espesador"], h["inicio"]))
            except (json.JSONDecodeError, KeyError):
                pass
    while True:
        t0 = time.time()
        log(f"[{datetime.now():%Y-%m-%d %H:%M}] ciclo de vigilancia, ventana {cfg['ventana_horas']} h")
        try:
            out = informe(f"-{cfg['ventana_horas']}h", "ahora", con_llm=cfg.get("resumen_llm", True))
            nuevas = []
            with open(alertas, "a", encoding="utf-8") as f:
                for h in out["hallazgos"]:
                    if "error" in h:
                        continue
                    clave = (h["regla"], h["espesador"], h["inicio"])
                    if clave in vistas:
                        continue
                    vistas.add(clave)
                    h["detectada"] = datetime.now().isoformat(timespec="minutes")
                    f.write(json.dumps(h, ensure_ascii=False) + "\n")
                    nuevas.append(h)
            ruta = guardar_informe(out, carpeta)
            log(f"  {len(nuevas)} alertas nuevas, informe en {ruta}")
            for h in nuevas:
                log(f"  ▲ [{h['severidad'].upper()}] {h['espesador']} {h['inicio'][:16]}: {h['mensaje']}")
        except Exception as e:  # noqa: BLE001 — el ciclo no debe morir por un error puntual
            log(f"  ERROR en el ciclo: {type(e).__name__}: {e}")
        if una_vez:
            break
        espera = max(cfg["cada_min"] * 60 - (time.time() - t0), 5)
        time.sleep(espera)


# ============================================================================
# Reglas
# ============================================================================
def cmd_reglas(args):
    ruta = AGENTE["reglas_operadores"]
    pend = AGENTE["reglas_pendientes"]
    if args.accion == "listar":
        for r in R.cargar_reglas(ruta):
            act = "" if r.get("activa", True) else " (inactiva)"
            log(f"{r['id']:34s} [{r['severidad']}] {r.get('espesador', '*'):7s} {r['duracion_min']:>4} min{act}")
            log(f"    {r['condicion']}")
        return
    if args.accion == "validar":
        ids, ok = [], True
        for r in R.cargar_reglas(ruta):
            p = R.validar_regla(r, ids)
            ids.append(r.get("id"))
            log(f"{r.get('id'):34s} {'OK' if not p else 'ERROR: ' + '; '.join(p)}")
            ok = ok and not p
        sys.exit(0 if ok else 1)
    if args.accion == "probar":
        if not args.id:
            sys.exit("falta --id")
        esps = [args.espesador] if args.espesador else None
        reglas = [r for r in R.cargar_reglas(ruta) if r["id"] == args.id]
        if not reglas:
            sys.exit(f"no existe la regla {args.id}")
        for e in esps or R.espesadores_de(reglas[0]):
            res = H.evaluar_reglas(e, args.inicio, args.fin, solo_ids=[args.id])
            log(f"== {e}: {res['n']} hallazgos")
            log(res["texto"])
        return
    if args.accion == "proponer":
        res = H.proponer_regla(args.id, args.condicion, args.mensaje, args.espesador or "*",
                               args.duracion or 30, args.severidad or "media", args.nombre, autor="operador")
        log(json.dumps(res, ensure_ascii=False, indent=1))
        return
    if args.accion == "pendientes":
        try:
            for r in R.cargar_reglas(pend):
                log(f"{r['id']:34s} [{r['severidad']}] {r.get('espesador', '*')} · {r['condicion']}  (autor {r.get('autor')}, {r.get('creada')})")
        except FileNotFoundError:
            log("sin reglas pendientes")
        return
    if args.accion in ("aprobar", "rechazar"):
        if not args.id:
            sys.exit("falta --id")
        try:
            pendientes = R.cargar_reglas(pend)
        except FileNotFoundError:
            sys.exit("sin reglas pendientes")
        sel = [r for r in pendientes if r["id"] == args.id]
        if not sel:
            sys.exit(f"no hay regla pendiente {args.id}")
        resto = [r for r in pendientes if r["id"] != args.id]
        if args.accion == "aprobar":
            vigentes = R.cargar_reglas(ruta)
            p = R.validar_regla(sel[0], [r["id"] for r in vigentes])
            if p:
                sys.exit("no se puede aprobar: " + "; ".join(p))
            sel[0]["aprobada"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            R.guardar_reglas(vigentes + sel, ruta)
            log(f"regla {args.id} aprobada y agregada a {ruta}")
        else:
            log(f"regla {args.id} rechazada")
        R.guardar_reglas(resto, pend)
        return


# ============================================================================
# main
# ============================================================================
def main(argv=None):
    p = argparse.ArgumentParser(prog="agente", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("estado", help="cobertura de datos, pasarela PI y LLM local")

    q = sub.add_parser("preguntar", help="una pregunta al agente (requiere LLM local)")
    q.add_argument("pregunta")
    q.add_argument("--silencioso", action="store_true")

    sub.add_parser("chat", help="conversación interactiva (requiere LLM local)")

    i = sub.add_parser("informe", help="informe determinístico de una ventana")
    i.add_argument("--inicio", default="-24h")
    i.add_argument("--fin", default="ahora")
    i.add_argument("--espesador", action="append")
    i.add_argument("--sin-llm", action="store_true")
    i.add_argument("--guardar", action="store_true")

    v = sub.add_parser("vigilar", help="ciclo de vigilancia continua")
    v.add_argument("--una-vez", action="store_true")

    r = sub.add_parser("reglas", help="gestión de reglas de operadores")
    r.add_argument("accion", choices=["listar", "validar", "probar", "proponer", "pendientes", "aprobar", "rechazar"])
    r.add_argument("--id")
    r.add_argument("--espesador")
    r.add_argument("--inicio", default="-7d")
    r.add_argument("--fin", default="ahora")
    r.add_argument("--condicion")
    r.add_argument("--mensaje")
    r.add_argument("--duracion", type=int)
    r.add_argument("--severidad", choices=list(R.SEVERIDADES))
    r.add_argument("--nombre")

    h = sub.add_parser("herramienta", help="invocar una herramienta directamente")
    h.add_argument("nombre", choices=list(H.FUNCIONES))
    h.add_argument("args", nargs="?", default="{}", help="JSON con los argumentos")

    args = p.parse_args(argv)

    if args.cmd == "estado":
        from espesadores.agente.llm import LLMLocal
        log(json.dumps(H.cobertura(), ensure_ascii=False, indent=1))
        llm = LLMLocal()
        if llm.disponible():
            log(f"LLM local: Ollama en {llm.host}, modelo {llm.modelo} "
                f"{'cargado' if llm.modelo_cargado() else 'NO descargado (ollama pull ' + llm.modelo + ')'}; "
                f"disponibles: {llm.modelos()}")
        else:
            log(f"LLM local: Ollama no responde en {llm.host} (modo determinístico)")
        n = len(R.cargar_reglas())
        log(f"reglas de operadores: {n} en {AGENTE['reglas_operadores']}")
        return

    if args.cmd in ("preguntar", "chat"):
        from espesadores.agente.llm import LLMLocal
        llm = LLMLocal()
        if not llm.disponible():
            sys.exit(f"Ollama no responde en {llm.host}. Levantarlo con `ollama serve` "
                     "o usar `agente informe` (modo sin LLM).")
        if not llm.modelo_cargado():
            sys.exit(f"El modelo {llm.modelo} no está descargado: ollama pull {llm.modelo}")
        if args.cmd == "preguntar":
            texto, _ = llm.preguntar(args.pregunta, verbose=not args.silencioso)
            log("\n" + texto)
            return
        historial = None
        log(f"Agente offline ({llm.modelo}). Escribe 'salir' para terminar.")
        while True:
            try:
                pregunta = input("\n> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not pregunta or pregunta.lower() in ("salir", "exit", "quit"):
                break
            texto, historial = llm.preguntar(pregunta, historial)
            log("\n" + texto)
        return

    if args.cmd == "informe":
        out = informe(args.inicio, args.fin, args.espesador, con_llm=not args.sin_llm)
        log(out["texto"])
        if out.get("redaccion"):
            log("\nRESUMEN (LLM local)\n" + out["redaccion"])
        if args.guardar:
            log(f"\nguardado en {guardar_informe(out, AGENTE['vigilancia']['salidas'])}")
        return

    if args.cmd == "vigilar":
        vigilar(una_vez=args.una_vez)
        return

    if args.cmd == "reglas":
        cmd_reglas(args)
        return

    if args.cmd == "herramienta":
        log(H.invocar(args.nombre, json.loads(args.args)))
        return


if __name__ == "__main__":
    main()
