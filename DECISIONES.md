# Decisiones

Cada cambio del emparejador lleva su hipótesis, su resultado y su coste. Se ajusta con desarrollo (`make dev`, semilla 7, 5.000 empresas) y test (`make eval`, semilla 2026, 1.000 empresas) se mide **una sola vez** al final de cada fase. Ninguna decisión se toma mirando test.

Abreviaturas de las tablas:
- **P, R, F1**: precisión, cobertura y F1 por pares, solo con lo que se fusiona automáticamente.
- **Erróneas**: pares de empresas distintas fusionados.
- **REVIEW**: pares en la zona gris (entre paréntesis, cuántos son la misma empresa).
- **Techo**: F1 si la zona gris se decidiera perfecta.

## D0 · Desarrollo con 5.000 empresas (1-nov-2026)

- **Problema:** con 1.000 empresas, desarrollo solo tenía 4 fusiones erróneas, y así ningún cambio se distingue del ruido.
- **Cambio:** desarrollo pasa a 5.000 empresas (unas 10.000 fichas, 8 s por ejecución). Test se queda en 1.000.
- **Bug encontrado:** el generador solo sabía inventar unas 3.100 marcas y se colgaba sin error por encima de ~3.000 empresas. Ahora combina 0–2 sílabas centrales (~37.000 marcas) y lanza un error si se agotan. Hay una prueba que lo cubre.
- **Efecto:** los datos cambian, así que hay que volver a medir la línea base en los dos conjuntos.

| | P | R | F1 | Erróneas | REVIEW | Techo |
|---|---:|---:|---:|---:|---:|---:|
| Línea base, desarrollo | 98,13 | 89,22 | 93,47 | 112 | 792 (537) | 97,58 |
| Línea base, test | 98,58 | 89,96 | 94,07 | 16 | 145 (102) | 98,13 |

## D1 · Mismo CIF en otra provincia → REVIEW

- **Hipótesis:** de las 112 fusiones erróneas, 101 vienen de un CIF copiado de una empresa vinculada, casi siempre una homónima de otra ciudad.
- **Datos:**
  - Empresas distintas, mismo CIF y otra provincia: 75 pares.
  - La misma empresa (mudada), mismo CIF y otra provincia: 156 pares.
  - Con los datos de la ficha no se distinguen.
- **Cambio:** mismo CIF válido, nombre parecido y provincia distinta pasa a REVIEW («same tax ID, different province»).
- **Resultado:** las fusiones erróneas bajan de 112 a 19. La cobertura automática baja de 89,2 a 86,5 y el techo sube a 98,29.
- **Coste:** 231 pares más a revisar, dos tercios de ellos mudanzas legítimas.
- **Estado:** adoptada. Kirill la confirmó el 1-nov-2026: fusionar dos empresas distintas es peor que perder un duplicado.

## D2 · CIF a una errata de distancia

- **Hipótesis:** hoy un CIF inválido se ignora. Pero un CIF inválido a una sola errata de un CIF válido es casi seguro el mismo.
- **Cambio:** un CIF válido y otro inválido, misma letra y distancia de edición 1, cuentan como «mismo CIF», con los mismos filtros de nombre y provincia.
- **Resultado:** la cobertura sube de 86,45 a 86,69. No hay fusiones erróneas nuevas.
- **Estado:** adoptada.

## D3 · Abreviaturas raras por subsecuencia

- **Hipótesis:** una abreviatura desconocida conserva la primera letra y quita letras, así que es subsecuencia de la palabra completa (CIAL → COMERCIAL).
- **Cambio:** si una palabra encaja así en **una sola** palabra del sector, y es al menos 2 letras más corta, se expande. Si encaja en varias, se deja como está (CNES: CONSTRUCCIONES o COMPONENTES).
- **Resultado:**
  - La cobertura sube de 86,69 a **89,53**.
  - Los pares con abreviatura rara pasan de fallar el 49 % de las veces al 14 %.
  - No hay fusiones erróneas nuevas.
- **Riesgo encontrado:** de las 20 palabras que expande en desarrollo, 19 son correctas y 1 es falsa: la marca «CORCA» → COMERCIAL. Aquí no causó errores.
- **Mitigación posible:** expandir solo si en el texto original la palabra va seguida de punto («Cial.»).
- **Estado:** adoptada.

## D4 · Marca completa en cualquier provincia

- **Hipótesis:** las 118 parejas que nunca se comparaban eran todas empresas mudadas de provincia sin un CIF válido en común. Las claves de nombre iban por provincia, así que no se encontraban. Y aunque se compararan, sacarían «NO» (0,72).
- **Cambio:**
  - Nueva clave de bloqueo por marca completa, sin provincia.
  - Mismo nombre (≥ 0,95) en otra provincia sin CIF que lo confirme pasa a REVIEW («same name, another province»).
- **Resultado:** las parejas sin comparar bajan de 118 a 28, y el techo sube de 98,33 a **98,90**. La cobertura automática no cambia.
- **Coste:** 251 pares más a revisar. En el grupo nuevo, 155 de 219 son empresas distintas: homónimas sin CIF.
- **Estado:** adoptada. Kirill la confirmó el 1-nov-2026. Se revisa en la fase 3 según si el LLM sabe separar mudanzas de homónimas.

## Fin de la fase 2: test (semilla 2026), medido una vez

| | P | R | F1 | Erróneas | REVIEW | Techo |
|---|---:|---:|---:|---:|---:|---:|
| Antes de la fase 2 | 98,58 | 89,96 | 94,07 | 16 | 145 (102) | 98,13 |
| Después de D1–D4 | **99,91** | **91,98** | **95,78** | **1** | 162 (90) | **99,43** |

## Lo que esto enseña para la fase 3

La zona gris ya no es homogénea. Cada motivo pide algo distinto al LLM:

- **«name + address, grey zone»** y **«same tax ID, different name»**: el LLM puede razonar con los datos de la ficha. Por ejemplo, «Norte» frente a «Sur» indica otra empresa, y el mismo CIF con la misma dirección indica un cambio de nombre.
- **«same tax ID, different province»** y **«same name, another province»**: los datos no bastan. La respuesta correcta suele ser «no lo sé: comprobar en el Registro Mercantil». El LLM tiene que saber decir eso en lugar de adivinar.

## Fase 3 · Diseño (1-nov-2026, antes de gastar nada)

- **D5 · Solo la zona gris va al LLM.** Las reglas deciden gratis casi todos los pares candidatos. El LLM ve 1.077 pares en desarrollo y 162 en test.
- **D6 · Tres respuestas, no dos:** `same_company`, `different_companies` y `needs_external_check`.
  - La fase 2 demostró que hay pares que los datos no deciden, como el mismo CIF o el mismo nombre en otra provincia.
  - Lo que el LLM no decide va a una persona y nunca se fusiona por defecto. Lo mismo pasa con cualquier respuesta inservible: un rechazo, una respuesta cortada, un JSON roto o un error de la API.
- **D7 · Salida forzada con esquema JSON** (`output_config.format`), con campos para auditar la decisión: confianza, patrón, pruebas citando los campos y una explicación de una frase. Así una persona puede revisar la decisión sin repetir el análisis.
- **D8 · Qué ve el modelo:**
  - los campos SAP de las dos fichas;
  - el motivo que dan las reglas;
  - si cada CIF pasa el dígito de control. Es un cálculo determinista, así que no se le pide al modelo.
  - No ve los identificadores de registro ni las puntuaciones de similitud.
- **D9 · Modelos:** Claude Haiku 5.5 frente a Claude Sonnet 5.5, con el esfuerzo configurable (low, medium o high).
  - Sonnet lleva `fallbacks: "default"`: si un clasificador de seguridad rechaza la petición, el servidor la reintenta en otro modelo.
  - Haiku 5.5 no tiene esa opción, así que un rechazo suyo va a una persona.
- **D10 · Coste:**
  - El prompt de sistema (~1.200 tokens) va en caché.
  - Las respuestas se guardan en disco con un hash del prompt: repetir no cuesta, y cambiar el prompt solo invalida lo afectado.
  - Estimación sin llamadas reales (`make llm-dry`), suponiendo 600 tokens de salida por par: todo desarrollo con Haiku ≈ 0,36 $ y con Sonnet ≈ 7,23 $.
  - La Batches API (un 50 % más barata) queda descartada por ahora: a este volumen ahorra céntimos y no admite `fallbacks`.
- **Sesgo que hay que declarar:** el prompt está escrito sabiendo qué ruido mete el generador (Norte/Sur, CIF copiados…). Es conocimiento de dominio real, pero las cifras saldrán optimistas frente a datos reales. Por eso el prompt se itera solo en desarrollo y test se mide una vez.

**Método de la fase 3:**
1. `make llm-sample` con 50 pares, que cuesta céntimos, para comprobar que todo funciona.
2. `make llm-dev` con Haiku y con Sonnet, a dos niveles de esfuerzo.
3. Iterar el prompt mirando solo desarrollo y apuntar aquí cada cambio.
4. Congelar el prompt y el modelo, y ejecutar `make llm-test` una sola vez.
