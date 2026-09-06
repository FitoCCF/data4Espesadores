import os
import clr
import sys
import pandas as pd
from datetime import datetime

from espesadores.config import EXTRACCION, TAGS_EXTRACCION_PI

# 1. Configuración de Rutas y Carga de DLLs
sys.path.append(EXTRACCION["af_sdk_path"])
clr.AddReference('OSIsoft.AFSDK')

import System
from System import Array, String
from OSIsoft.AF import *
from OSIsoft.AF.PI import *

# ==========================================
# 2. PARÁMETROS CONFIGURABLES — desde conf/base/extraccion.yaml y tags.yaml
# ==========================================
SERVIDOR_NOMBRE = EXTRACCION["servidor"]

# Antes un dict de 30 tags escrito a mano aquí (subconjunto de una corrida
# anterior a los 68 tags). Ahora se deriva de la lista maestra: cubre los 68,
# incluidos los 5 que en esa corrida vieja aparecían como no identificados.
tags_config = {tag_pi: columna for tag_pi, columna, _grupo, _desc in TAGS_EXTRACCION_PI}

# Lista de 52 atributos según la imagen de PI Builder
atributos_pi = [
    # General
    "descriptor", "instrumenttag", "digitalset", "displaydigits", "engunits", "exdesc", 
    "future", "pointsource", "pointtype", "ptclassname", "sourcetag",
    # Archive
    "archiving", "compressing", "compdev", "compmax", "compmin", "compdevpercent",
    "excdev", "excmax", "excmin", "excdevpercent", "scan", "shutdown", 
    "span", "step", "typicalvalue", "zero",
    # Security
    "datasecurity", "ptsecurity",
    # Classic
    "convers", "filtercode",  "location1", "location2", 
    "location3", "location4", "location5", "squareroot", "srcptid", 
    "totalcode", "userint1", "userint2", "userreal1", "userreal2",
    # System
    "changedate", "changer", "creationdate", "creator", "pointid"
]

def extraer_atributos_afsdk():
    pi_servers = PIServers()
    server = pi_servers[SERVIDOR_NOMBRE]
    server.ConnectionInfo.TimeOut = System.TimeSpan.FromMilliseconds(500000)

    if not server.ConnectionInfo.IsConnected:
        server.Connect()

    print(f"Conectado a: {server.Name} para extracción de Atributos.")
    lista_datos = []
    
    # Conversión directa a un array nativo de C# para compatibilidad perfecta
    array_atributos_net = Array[String](atributos_pi)

    try:
        for tag_name, alias in tags_config.items():
            fila_tag = {'Tag_Original': tag_name, 'Alias_Dataframe': alias}
            try:
                point = PIPoint.FindPIPoint(server, tag_name)
                # Carga masiva usando el Array
                point.LoadAttributes(array_atributos_net)
                
                for attr in atributos_pi:
                    try:
                        valor = point.GetAttribute(attr)
                        fila_tag[attr] = str(valor) if valor is not None else None
                    except Exception:
                        fila_tag[attr] = None
                
                print(f"Atributos extraídos: {tag_name} OK")
                
            except Exception as e:
                print(f"Error extrayendo {tag_name}: {e}")
                
            lista_datos.append(fila_tag)

        if lista_datos:
            df_atributos = pd.DataFrame(lista_datos)
            carpeta = os.path.join(EXTRACCION["rutas"]["salida"], "pi_metadata")
            os.makedirs(carpeta, exist_ok=True)
            nombre_archivo = os.path.join(
                carpeta, f"atributos_pi_{datetime.now().strftime('%Y%m%d_%H%M')}.csv")
            df_atributos.to_csv(nombre_archivo, index=False, encoding='utf-8-sig')
            print(f"\nProceso Exitoso. Metadata guardada en: {nombre_archivo}")
            return df_atributos
            
    finally:
        server.Disconnect()

if __name__ == "__main__":
    df_meta = extraer_atributos_afsdk()