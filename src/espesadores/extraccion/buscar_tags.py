import os
import clr
import sys
import pandas as pd
from datetime import datetime

from espesadores.config import EXTRACCION

# 1. Configuración de Rutas y Carga de DLLs
sys.path.append(EXTRACCION["af_sdk_path"])
clr.AddReference('OSIsoft.AFSDK')

import System
from System import Array, String
from OSIsoft.AF import *
from OSIsoft.AF.PI import *

# Lista de 52 Atributos
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

def buscar_y_exportar_tags():
    # 1. Solicitar solo el patrón por teclado
    patron_busqueda = input("Ingrese el patrón del tag a buscar (ej. *294100*): ").strip()
    if not patron_busqueda:
        print("Error: Patrón no válido.")
        return

    servidor_nombre = EXTRACCION["servidor"]
    pi_servers = PIServers()
    
    try:
        server = pi_servers[servidor_nombre]
    except Exception:
        print(f"Error: No se encontró el servidor '{servidor_nombre}'.")
        return

    server.ConnectionInfo.TimeOut = System.TimeSpan.FromMilliseconds(500000)
    if not server.ConnectionInfo.IsConnected:
        server.Connect()

    print(f"\nBuscando '{patron_busqueda}'...")
    
    try:
        # 2. Búsqueda de tags
        puntos_encontrados = list(PIPoint.FindPIPoints(server, patron_busqueda))
        
        if not puntos_encontrados:
            print("No se encontraron coincidencias.")
            return

        lista_datos = []
        array_atributos_net = Array[String](atributos_pi)

        # 3. Extracción de Atributos
        for point in puntos_encontrados:
            fila_tag = {'Tag_Encontrado': point.Name}
            try:
                point.LoadAttributes(array_atributos_net)
                for attr in atributos_pi:
                    try:
                        valor = point.GetAttribute(attr)
                        fila_tag[attr] = str(valor) if valor is not None else None
                    except Exception:
                        fila_tag[attr] = None
            except Exception as e:
                print(f"Error extrayendo atributos de {point.Name}: {e}")
                
            lista_datos.append(fila_tag)

        # 4. Generación de Tabla Resumen y Exportación
        if lista_datos:
            df = pd.DataFrame(lista_datos)
            
            # Resumen tabulado exacto
            columnas_resumen = ['Tag_Encontrado', 'descriptor', 'instrumenttag']
            columnas_existentes = [c for c in columnas_resumen if c in df.columns]
            
            print("\n" + "="*80)
            print(f" RESUMEN DE COINCIDENCIAS ({len(lista_datos)} tags)")
            print("="*80)
            print(df[columnas_existentes].to_string(index=False))
            print("="*80)

            # Exportación
            patron_limpio = patron_busqueda.replace('*', 'X').replace('?', 'Y')
            carpeta = os.path.join(EXTRACCION["rutas"]["salida"], "pi_metadata")
            os.makedirs(carpeta, exist_ok=True)
            nombre_archivo = os.path.join(
                carpeta, f"busqueda_{patron_limpio}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv")
            df.to_csv(nombre_archivo, index=False, encoding='utf-8-sig')
            
            print(f"\n[OK] Base de datos completa exportada en: {nombre_archivo}")

    finally:
        server.Disconnect()

if __name__ == "__main__":
    buscar_y_exportar_tags()