# Glosario · Espesador TH-001

Guía para leer el **one-pager** y el **REPORTE_COMPLETO.txt**.
Ordenado por dónde aparece cada término.

---

# Parte 1 · Términos del one-pager

## Los tres roles de una variable

El one-pager clasifica cada variable en un rol, porque el sistema experto no
debe tratarlas igual.

| Rol | Qué significa | Ejemplos |
|---|---|---|
| **Variable objetivo** | El sistema la lleva a un valor y la sostiene ahí | Presión de cama, torque, nivel de interfaz, cizallamiento |
| **Actuador** | El sistema la mueve como *medio* para llegar al objetivo, dentro de límites, pero no la persigue como meta | Bomba de descarga |
| **Monitoreo** | Solo se lee, para verificar que la operación va bien | % sólidos de descarga |
| **Sin efecto** | No sirve como variable de ajuste; se descartó con datos | Floculante, válvula de alimentación |

**Por qué la bomba de descarga es actuador y no objetivo:** su velocidad
*responde* a la densidad del relave, no la produce. Cuando el underflow sale más
espeso es más viscoso, y la bomba necesita más velocidad para moverlo. Fijar un
valor de velocidad como meta sería invertir la causa y el efecto.

## Cómo se leen las escalas

Cada fila del one-pager es una escala de instrumento dibujada a proporción:

| Elemento | Qué es |
|---|---|
| **Riel gris** | Rango completo en que se movió la variable históricamente |
| **Banda verde** | Ventana objetivo: donde vive la planta cuando recupera más agua |
| **Banda ámbar** | Rango válido de un actuador (no es una meta) |
| **Marca negra** | Valor a apuntar |
| **Marca roja** | Valor promedio actual de la planta |
| **Flecha (SUBIR / BAJAR)** | Dirección en que hay que corregir |

Si la marca roja está fuera de la banda verde, ahí hay una oportunidad.

## Variables de proceso

**Presión de cama** (`TH001_PLC_BEDM`)
Cuánto material sedimentado hay acumulado en el fondo del espesador. Más presión
de cama = más sólidos acumulados = más tiempo de residencia = relave más espeso.
Es la variable objetivo de mayor peso.

**Torque de rastra** (`TH001_PLC_TORK`)
Esfuerzo que hace el mecanismo de rastras para girar dentro de la cama. Sube
cuando la cama está más cargada o más densa. Es a la vez indicador y
**restricción**: por encima de cierto valor hay riesgo de sobrecarga mecánica.
El límite alto de la ventana es un **tope**, no una meta.

**Nivel de interfaz** (`TH001_PLC_LVL`)
Altura de la frontera entre el agua clara de arriba y la pulpa sedimentada de
abajo. Interfaz más baja = más espacio para que los sólidos sedimenten =
mejor recuperación.

**Flujo de alimentación** (`LIT_1011_Flow`)
Caudal de pulpa que entra al espesador, en m³/h.

**% sólidos de descarga** (`wt_activo`)
Qué tan espeso sale el relave por el fondo. **Es el indicador principal**: cada
punto que sube es agua que deja de irse con los sólidos y se recupera por el
rebose. El sufijo *activo* significa que se toma la medición de la bomba que
está realmente en servicio, no la de la que está detenida.

**Rebose**
Agua clara que rebalsa por la parte superior del espesador y se recupera hacia
las pozas. Es el objetivo final de todo el análisis.

**Recuperación**
Rebose dividido entre el agua que entró. Se expresa en porcentaje. A diferencia
del rebose en m³/h, **no depende del tonelaje**, por lo que sirve para comparar
turnos y condiciones distintas.

**Sensibilidad (m³/h por punto)**
Cuántos m³/h de agua se ganan por cada punto de % sólidos de descarga. En TH-001:
**10.9 m³/h por punto**. Es la regla de conversión para traducir cualquier mejora
de densidad a metros cúbicos.

**Tren de bombeo**
Conjunto acoplado de bomba de descarga + bomba de cizallamiento que arrancan y
paran juntas. TH-001 tiene dos trenes que nunca se mezclan entre sí.

**Bomba de cizallamiento**
Recircula y corta el relave espesado. Mantenerla a velocidad fija ayuda a liberar
agua atrapada en los flóculos. Es la única bomba que **sí** es variable objetivo.

---

# Parte 2 · Términos del REPORTE_COMPLETO.txt

## Las once etapas

| Etapa | Qué hace |
|---|---|
| **E01** | Carga los datos, cuenta filas y detecta cada cuánto se muestrea |
| **E02** | Descarta variables inservibles antes de que contaminen el análisis |
| **E03** | Limpieza: valores imposibles, planta detenida, valores atípicos |
| **E04** | Determina qué tren de bombeo está operando en cada instante |
| **E05** | Recalcula el rebose desde el balance de agua |
| **E06** | Conserva solo los períodos de operación estable |
| **E07** | **Compuerta de calidad**: verifica que los datos reproduzcan la física |
| **E08** | Detecta tipos de mineral sin usar etiquetas previas |
| **E09** | Mide si las guardias operan distinto entre sí |
| **E10** | Calcula las ventanas operativas óptimas |
| **E11** | Compara el desempeño de los dos trenes de bombeo |

## Conceptos de limpieza (E02 y E03)

**Hold / señal congelada**
Cuando un instrumento o un reporte deja de actualizarse y repite el último valor.
Se detecta porque un solo número concentra demasiadas filas. En TH-001,
`Ratio_concentracion_Output` tenía el 86 % de las filas con el mismo valor: no
era un dato, era un reporte que no se refrescaba.

**Rango físico**
Límite de lo que un instrumento puede medir. Un nivel de 99 999 no es un dato:
es un código de falla. Se anula esa medición puntual, **no la fila completa**,
porque un sensor fallado no invalida las otras 29 mediciones de ese instante.

**Valor atípico (Hampel / MAD)**
Medición que se aparta demasiado del comportamiento cercano en el tiempo. Se
detecta comparando contra la **mediana** móvil y no contra el promedio, porque el
promedio ya viene distorsionado por los propios valores extremos.

**SG / gravedad específica**
Cuánto pesa el mineral respecto del agua. En TH-001 salió constante en 2.77, lo
que reveló que el % de sólidos y la densidad **no son mediciones independientes**:
el sistema calcula una a partir de la otra.

**Duty / standby**
Configuración en que un equipo opera y otro queda de respaldo. La medición del
equipo detenido no significa nada y hay que excluirla.

**Estado estacionario**
Períodos en que la planta opera estable, sin arranques ni cambios bruscos.
Durante un transitorio las variables no están en equilibrio y las relaciones
causa-efecto quedan enmascaradas.

**Coeficiente de variación (CV)**
Cuánto se mueve una variable respecto de su propio promedio, en porcentaje.
CV bajo = señal estable.

## Conceptos de validación (E07)

**Correlación bruta vs. correlación parcial**
La bruta mide si dos variables se mueven juntas. La **parcial** mide lo mismo
pero después de descontar el efecto de una tercera.

Ejemplo real del reporte: la correlación bruta entre % sólidos y rebose era
+0.214, casi nula. Al descontar el tonelaje subió a **+0.893**. El tonelaje
estaba enmascarando la relación, porque el rebose sigue a la producción.

**Pendiente empírica vs. pendiente teórica**
La teórica es la que predice el balance de agua: cuántos m³/h debería ganar el
espesador por cada punto de % sólidos. La empírica es la que se mide en los datos
limpios.

**Si ambas coinciden, la limpieza y el balance están bien hechos.** Es la
compuerta de calidad del pipeline: si no coinciden, hay un problema de tags o de
instrumentación y las ventanas no serían confiables.

**Desvío**
Diferencia porcentual entre ambas pendientes. Se acepta hasta 30 %.

> La banda de tonelaje más bajo suele fallar (−53.6 % en TH-001). Es esperable:
> es el régimen casi detenido, donde el balance de agua pierde sentido.

## Conceptos de agrupamiento (E08)

**Clustering**
Agrupar automáticamente períodos parecidos entre sí, sin decirle al algoritmo qué
buscar. Se usó para descubrir tipos de mineral, que no venían etiquetados.

**Variable exógena**
Variable que viene dada de afuera y el operador del espesador no controla, como
la ley del mineral. Los tipos de mineral se construyeron **solo** con exógenas,
para no caer en el razonamiento circular de agrupar por decisiones del operador
y luego "descubrir" que el operador responde a ellas.

**Silueta / Davies-Bouldin / Calinski-Harabasz**
Tres formas distintas de medir si los grupos encontrados están bien separados.
Silueta alta = mejor; Davies-Bouldin baja = mejor; Calinski alto = mejor. Se
exige que coincidan, porque ninguna sola es confiable.

**ARI (estabilidad)**
Si se repite el agrupamiento con una muestra distinta de los mismos datos,
¿salen los mismos grupos? Un ARI cercano a 1.0 significa que los grupos son
reproducibles y no un artefacto de la muestra.

**AUC**
Qué tan bien se puede predecir algo. 0.5 = puro azar; 1.0 = perfecto.

**Control positivo**
Verificación de que el detector funciona **antes** de interpretar un resultado
negativo. Si se concluye que "el mineral no influye" con un detector roto, sería
un falso negativo. En E08 se exige AUC alto de las variables exógenas hacia los
tipos de mineral: si no lo alcanza, el pipeline avisa que no se interprete E09.

## Conceptos de comparación (E09 y E11)

**Efecto real (η²)**
Qué fracción de la variación de un parámetro queda explicada por un factor.
0.01 = el factor explica el 1 %. En el reporte aparece como "efecto real".

**Nulo**
Valor que daría el mismo cálculo si no hubiera ningún efecto verdadero. Sirve de
punto de comparación: un efecto solo es real si supera claramente a su nulo.

**p-valor**
Probabilidad de obtener ese resultado por casualidad. Menor a 0.05 se considera
significativo. En el reporte, la columna final marca `SI` o `no`.

**Desplazamiento circular**
Forma de construir el nulo para el rol de guardias: se corre el rol unos días,
conservando la rotación y el comportamiento del proceso pero rompiendo la
correspondencia real entre guardia y fecha. Si el efecto verdadero no supera a
ese nulo, no hay huella de guardia.

> Esto evita una trampa: comparar contra "día calendario" parecía mostrar un
> efecto enorme de las guardias, pero trocear el tiempo en bloques arbitrarios
> daba lo mismo. Era autocorrelación, no criterio de guardia.

**Emparejamiento**
Comparar dos grupos solo dentro de condiciones equivalentes. En E11 los trenes se
comparan únicamente entre períodos con la misma presión de cama, el mismo nivel y
el mismo tonelaje, para descartar que uno se use solo en condiciones difíciles.

**Percentiles p10 y p90**
El valor por debajo del cual está el 10 % (o el 90 %) de los casos. Las ventanas
operativas son el rango p10–p90 del tercio de mejor recuperación: describen
**dónde vive la planta cuando recupera más agua**, no un óptimo teórico.

**Tercio de alta / baja recuperación**
Se ordena la operación por recuperación y se parte en tres. Comparar el tercio
superior contra el inferior, dentro del mismo tipo de mineral y a igual tonelaje,
revela qué distingue una buena operación de una mala.

## Conceptos del balance de agua (E05)

**Partición**
Fracción del relave total de la planta que llega a este espesador en particular.

**Tonelaje del espesador**
Toneladas por hora de sólidos que llegan a este espesador. Es el tonelaje total
del molino repartido según la partición.

**Balance de agua**
```
agua que entra  =  agua de dilución + agua que trae la pulpa
agua que sale   =  agua que se va por el fondo con los sólidos
rebose          =  agua que entra − agua que sale
```

**Por qué se recalcula el rebose**
El estimador del sistema de control quedaba congelado el 70 % del tiempo, pero
sus entradas seguían vivas. Recalcularlo desde el balance conserva la mayor parte
del historial en vez de descartarlo.

---

# Parte 3 · Preguntas frecuentes

**¿Por qué el rebose en m³/h no sirve para comparar turnos?**
Porque escala casi directamente con el tonelaje (correlación +0.978). Un turno
con más producción tendrá más rebose sin operar mejor. Para comparar se usa la
**recuperación** en porcentaje, que ya está normalizada.

**¿Subir el torque no es peligroso?**
El torque objetivo de 33 está en el percentil 63: la planta ya opera ahí más de
un tercio del tiempo. El máximo histórico registrado es 53.8. Aun así, el límite
alto de la ventana es un tope operativo y debe validarse con Procesos antes de
aplicarse.

**¿Por qué el floculante aparece como "sin efecto"?**
Porque su dosis es prácticamente la misma en la operación de alta y de baja
recuperación, en los cuatro tipos de mineral. Eso sugiere que está saturado:
dosificar más no espesa más. No significa que no sea necesario, sino que no es
la palanca para recuperar más agua.

**¿Los "tipos de mineral" son tipos geológicos reales?**
No exactamente. Son **regímenes de alimentación inferidos** a partir de la ley y
el ratio de cobre. Para confirmarlos habría que cruzarlos con el plan de mina o
con resultados de laboratorio.

**¿Cuánta confianza tienen estos números?**
El análisis se basa en 1 064 161 registros de dos años, de los cuales quedaron
424 946 en operación estable tras la limpieza. La compuerta de calidad E07 se
superó: la ganancia medida por punto de % sólidos coincide con la que predice el
balance de agua en cuatro de cinco bandas de tonelaje.
