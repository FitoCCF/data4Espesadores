# 001 — Namespace del PI AF SDK para paginación bulk: `AF.PI`, no `AF.Data`

**Fecha:** anterior a 2026-09-05 (extraído de `Untitled.ipynb`, sin fecha de
commit propia; el archivo vivo es de 2026-09-05 18:03).
**Estado:** confirmado y aplicado en producción.
**Contexto:** extracción bulk de PI mediante `PIPointList.InterpolatedValues`
con `PIPagingConfiguration`, para no hacer un round-trip por tag.

## Pregunta

¿En qué namespace de OSIsoft.AF SDK vive `PIPagingConfiguration`/`PIPageType`,
necesarios para extracción bulk paginada: `OSIsoft.AF.PI` o `OSIsoft.AF.Data`?
Ambos existen en el SDK y es fácil asumir el equivocado por analogía con otras
clases.

## Evidencia (prueba directa contra la instalación del AF SDK de destino)

```python
import sys, clr
sys.path.append(r'C:\Program Files (x86)\PIPC\AF\PublicAssemblies\4.0')
clr.AddReference('OSIsoft.AFSDK')

import OSIsoft.AF.PI as pi
import OSIsoft.AF.Data as afdata

print('AF.PI  :', [n for n in dir(pi) if 'Pag' in n or 'PageType' in n])
print('AF.Data:', [n for n in dir(afdata) if 'Pag' in n or 'PageType' in n])
print('bulk   :', hasattr(pi.PIPointList(), 'InterpolatedValues'))
```

Salida:

```
AF.PI  : ['PIPageType', 'PIPagingConfiguration']
AF.Data: []
bulk   : True
```

## Decisión

`PIPageType` y `PIPagingConfiguration` viven en `OSIsoft.AF.PI`, no en
`OSIsoft.AF.Data`, en esta instalación del SDK. `PIPointList` sí expone
`InterpolatedValues` para extracción bulk.

## Aplicación

`getDataAllTH.py` importa `from OSIsoft.AF.PI import PIServers, PIPoint,
PIPointList, PICommonPointAttributes` y usa ese namespace para la paginación
(corrección #3 documentada en su propio docstring). El notebook original de
extracción, `getData.ipynb` (descartado el 2026-09-06 — ver
`docs/inventario_proyecto.md` / `docs/plan_migracion.md`), usaba
`OSIsoft.AF.Data`, namespace incorrecto para este propósito; quedó superseded
por `getDataAllTH.py` antes de que el error tuviera consecuencias en el
dataset canónico.

## Notebook de origen

El código y la salida de arriba vienen íntegros de `Untitled.ipynb`. El
notebook se descartó el 2026-09-06 por indicación del usuario, una vez
extraído aquí el único contenido con valor de decisión que tenía.
