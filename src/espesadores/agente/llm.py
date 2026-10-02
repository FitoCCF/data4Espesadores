# -*- coding: utf-8 -*-
"""
llm.py — capa de lenguaje del agente: modelo local servido por Ollama.

El modelo no ve datos crudos. Recibe la pregunta del operador, decide qué
herramientas llamar (herramientas.py), recibe sus resultados como JSON y
redacta la respuesta. Si Ollama no está levantado, `disponible()` es False
y la CLI sigue funcionando en modo determinístico.

API de Ollama usada: POST {host}/api/chat con `tools` (formato OpenAI),
`stream: false`. Los tool calls vuelven en message.tool_calls y el resultado
se devuelve con role "tool". Sin dependencias fuera de `requests`.
"""
import json
import time

import pandas as pd
import requests

from espesadores.config import AGENTE, REGLAS_PISCINAS, PROCESO
from espesadores.agente import herramientas as H

_CFG = AGENTE["llm"]

SISTEMA = f"""Eres el asistente de análisis de los espesadores de relaves TH-001, TH-002 y TH-003
de la Concentradora 2. Trabajas SOLO con las herramientas: nunca inventes cifras; toda cifra que
menciones debe salir de un resultado de herramienta. Responde en español, breve y con números.

Conocimiento operativo (confirmado por operaciones):
- El indicador principal de recuperación de agua es el NIVEL DE PISCINA (nivel_piscina). Mínimo
  operativo {REGLAS_PISCINAS['nivel_minimo_pct']} % (R1); al cierre de guardia (07:30 y 19:30) debe
  quedar en {REGLAS_PISCINAS['nivel_cierre_guardia_pct']} % o más (R2).
- flujo_piscinas (FIT_114) es un indicador INDIRECTO: sube cuando los tanques tk001/tk002 suben y
  arrancan bombas. agua_fresca y agua_qh entran a la piscina y NO son rebose de espesadores.
- La válvula de alimentación (valvula_alim) la mueve el operador a mano. El torque es respuesta del
  proceso, no una consigna.
- La planta produce cuando molienda_total > {PROCESO['tonelaje_min_produccion']} t/h. Compara
  siempre en condiciones comparables (misma molienda, mismo nº de trenes).
- Hipótesis en estudio: (1) con piscina baja se reduce la descarga a propósito; (2) tras una parada
  aguas arriba el mineral grueso se apelmaza en la válvula y el operador la abre. Los análisis
  históricos no mostraron la firma de atoro; (1) solo aparece como corrección lenta.
- Un resultado "significativo" con N grande no es relevante por sí solo: usa el campo "relevante".
- En los resultados, p50 es la MEDIANA (valor típico), no el promedio; p10–p90 es la ventana habitual;
  min/max son extremos absolutos que pueden ser un dato suelto.

Variables (por rol, iguales para los tres espesadores): flujo_alim = flujo de ALIMENTACIÓN al
espesador; valvula_alim = válvula de alimentación; presion_cama; torque; nivel_interfaz;
nivel_cajon; floculante; agua_dilucion; vel_descarga y vel_cizalle = bombas del tren en servicio;
wt_activo = % sólidos de descarga; dit_activo = densidad. De planta: nivel_piscina,
flujo_piscinas (FIT_114, agua hacia la piscina — NO es la alimentación), tk001, tk002,
molino_1, molino_2, molienda_total, ley_rougher, ratio_cu, agua_fresca, agua_qh.

Cómo trabajar:
1. Si la pregunta no fija fechas, usa las últimas 24 h ('-24h' a 'ahora'). Un día completo es
   'YYYY-MM-DD 00:00' a 'YYYY-MM-DD+1 00:00'.
2. Empieza por evaluar_reglas y resumen; usa anomalias, episodios, tendencia o relaciones según
   haga falta. Para comparar dos períodos usa SIEMPRE comparar_periodos (una sola llamada con A y
   B); nunca compares cifras que no hayas obtenido. No pidas más de
   {AGENTE['datos']['max_dias_por_consulta']} días por llamada.
3. Si un operador describe una condición que quiere vigilar, redáctala como regla con
   proponer_regla (usa variables por rol y las funciones media/mediana/delta/pendiente/congelado)
   y dile que queda pendiente de aprobación.
4. Termina con una respuesta clara: qué pasó, con qué cifras, y qué conviene revisar."""


class LLMLocal:
    def __init__(self, host=None, modelo=None):
        self.host = (host or _CFG["host"]).rstrip("/")
        self.modelo = modelo or _CFG["modelo"]
        self.timeout = _CFG.get("timeout_s", 600)
        self.trazas = []

    # ---------------------------------------------------------------- estado
    def disponible(self):
        try:
            r = requests.get(self.host + "/api/tags", timeout=3)
            return r.ok
        except requests.RequestException:
            return False

    def modelos(self):
        try:
            r = requests.get(self.host + "/api/tags", timeout=3)
            return [m["name"] for m in r.json().get("models", [])]
        except requests.RequestException:
            return []

    def modelo_cargado(self):
        nombres = self.modelos()
        return any(n == self.modelo or n.split(":")[0] == self.modelo.split(":")[0] for n in nombres)

    # ---------------------------------------------------------------- chat
    def _chat(self, mensajes, tools, pensar=None):
        cuerpo = {
            "model": self.modelo, "messages": mensajes, "stream": False,
            "options": {"num_ctx": _CFG["num_ctx"], "temperature": _CFG["temperatura"]},
        }
        if tools:
            cuerpo["tools"] = tools
        pensar = _CFG.get("pensar") if pensar is None else pensar
        if pensar is not None:
            cuerpo["think"] = bool(pensar)
        r = requests.post(self.host + "/api/chat", json=cuerpo, timeout=self.timeout)
        r.raise_for_status()
        return r.json()["message"]

    @staticmethod
    def sistema():
        """Prompt de sistema + fecha actual: el modelo no sabe qué día es y
        sin esto inventa fechas para 'ayer' o 'esta semana'."""
        ahora = pd.Timestamp.now(tz=AGENTE["datos"]["zona_horaria"])
        return (SISTEMA + f"\n\nFecha y hora actual: {ahora:%Y-%m-%d %H:%M} (hora local). "
                f"Hoy es {ahora:%Y-%m-%d}; ayer fue {ahora - pd.Timedelta(days=1):%Y-%m-%d}. "
                "Para fechas usa 'YYYY-MM-DD HH:MM' o las formas 'ayer 06:30', 'hoy 08:00', '-6h', '-2d'.")

    def preguntar(self, pregunta, historial=None, verbose=True):
        """Loop pregunta -> tool calls -> respuesta. Devuelve (texto, historial)."""
        mensajes = list(historial) if historial else [{"role": "system", "content": self.sistema()}]
        mensajes.append({"role": "user", "content": pregunta})
        tools = H.esquemas_ollama()
        for i in range(_CFG["max_iteraciones"]):
            t0 = time.time()
            msg = self._chat(mensajes, tools)
            llamadas = msg.get("tool_calls") or []
            mensajes.append({"role": "assistant", "content": msg.get("content", ""),
                             **({"tool_calls": llamadas} if llamadas else {})})
            if not llamadas:
                return (msg.get("content") or "").strip(), mensajes
            for tc in llamadas:
                fn = tc.get("function", {})
                nombre = fn.get("name")
                args = fn.get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                if verbose:
                    print(f"  ⚙ {nombre}({json.dumps(args, ensure_ascii=False)})", flush=True)
                resultado = H.invocar(nombre, args)
                self.trazas.append({"iter": i, "herramienta": nombre, "args": args,
                                    "bytes": len(resultado), "s_modelo": round(time.time() - t0, 1)})
                mensajes.append({"role": "tool", "content": resultado, "tool_name": nombre})
        # Se agotaron las iteraciones: pedir cierre sin herramientas.
        mensajes.append({"role": "user", "content": "Responde ahora con lo que ya tienes, sin llamar más herramientas."})
        msg = self._chat(mensajes, tools=None)
        mensajes.append({"role": "assistant", "content": msg.get("content", "")})
        return (msg.get("content") or "").strip(), mensajes

    REDACCION = """Redacta para el operador de turno un resumen EN ESPAÑOL de como máximo 12 líneas de texto
corrido (sin tablas, sin títulos, sin viñetas anidadas). Reglas estrictas:
- Solo cifras que aparezcan en los DATOS; no inventes causas ni diagnósticos ("falla de equipo",
  "calibración") — describe lo observado y, si acaso, di "revisar".
- Orden: 1) alertas de reglas (o "sin alertas"); 2) piscina: nivel típico, mínimo y tendencia
  inicio→fin; 3) por espesador, solo lo que cambió o llama la atención (escalones, congelados,
  válvula movida); 4) una línea de qué conviene mirar primero.
- Las señales "congeladas" de bombas/válvula suelen ser consignas fijas, no fallas: no las
  llames anomalía salvo que sea un instrumento (presión, nivel, flujo)."""

    def redactar(self, instruccion, contexto):
        """Una sola llamada sin herramientas ni razonamiento largo: resumir
        hallazgos ya calculados (modo vigilancia / informe). Recibe el texto
        legible del informe, no el JSON crudo: menos contexto y menos invención."""
        mensajes = [{"role": "system", "content": self.sistema()},
                    {"role": "user", "content": f"{self.REDACCION}\n{instruccion}\n\nDATOS:\n{contexto}"}]
        msg = self._chat(mensajes, tools=None, pensar=False)
        return (msg.get("content") or "").strip()
