# Plan de «Say my name» (Di mi nombre)

Proyecto de portfolio: detectar duplicados de interlocutores comerciales (clientes KNA1 y proveedores LFA1) antes de una migración a S/4HANA. Primero reglas, y un LLM solo para la zona gris.

## Para contarlo en una entrevista (30 segundos)

> «En una migración a S/4HANA, cada cliente y proveedor de los sistemas antiguos se convierte en un Business Partner, y la misma empresa aparece varias veces escrita de formas distintas. Monté un banco de pruebas con datos SAP sintéticos y respuesta conocida, un emparejador por reglas que fusiona solo lo seguro, y un LLM que decide la zona gris citando las pruebas. Lo mido todo: precisión, cobertura, coste por cada mil registros y en qué tipo de caso falla.»

## Estado a 1-nov-2026: fases 0 y 1 hechas

- Generador de datos sintéticos con forma SAP, dos sistemas, ruido documentado y trampas (empresas hermanas, homónimas, CIF copiado).
- Emparejador por reglas en Python estándar. Una ejecución completa tarda menos de medio segundo.
- Evaluación con un informe que dice dónde y por qué falla. Hay 25 pruebas unitarias.
- En la semilla de test (2026): precisión 98,4 % y cobertura 87,0 %. El techo, si la zona gris se decidiera perfecta, es 97,2 % de F1.

**Antes de seguir, léete todo el código.** En una entrevista te van a preguntar por cualquier línea. Cambia lo que no te convenza; es tu proyecto.

## Fase 2: mejores reglas (1 fin de semana, en tu mano)

Método: ajustas con `make dev` (semilla 7) y solo apuntas cifras de `make eval` (semilla 2026). Cada cambio, con su hipótesis y su resultado, va en un `DECISIONES.md`.

Ideas que salen del informe actual, ordenadas por impacto:

1. **Mismo CIF pero en otra provincia → REVIEW en vez de AUTO.** Hoy las 17 fusiones erróneas por CIF copiado entran como AUTO. Ojo: las empresas que se mudaron también caerán en REVIEW. Mide si compensa.
2. **CIF con un dígito de diferencia** (uno válido y el otro no) como prueba a favor. Hoy el CIF inválido se ignora sin más.
3. **Abreviaturas raras**: una palabra que es subsecuencia de una palabra del sector y empieza por la misma letra («CIAL» → COMERCIAL, «DTBCIONES» → DISTRIBUCIONES). Hoy fallan la mitad de los pares con abreviaturas raras.
4. **Bloqueo**: 25 pares nunca llegan a compararse. Mira cuáles son y añade una clave que los recoja sin disparar el número de comparaciones.

## Fase 3: LLM en la zona gris (1-2 fines de semana, en tu ordenador personal)

- Entrada: `out/<run>/review.csv`. Salida estructurada en JSON: `same_company` (sí/no/no lo sé), `confidence`, `evidence` (los campos que lo justifican) y `risk` («posible CIF copiado», «empresa hermana»…).
- Modelos: Claude Haiku 5.5 frente a Sonnet 5.5. Las reglas fijas y las instrucciones van en un prompt cacheado.
- Métricas: precisión y cobertura sobre la zona gris, F1 final frente al techo, coste por cada mil registros, latencia y porcentaje de «no lo sé» que pasa a una persona.
- Evals en CI con un límite de gasto en la cuenta de Anthropic. La clave, solo como secreto, nunca en el repo.
- Tiene que mejorar a «aceptar todo a ciegas» (95,4 % de F1) y acercarse a 97,2 %.

## Fase 4: registro maestro y pantalla de revisión (1 fin de semana)

- Reglas de supervivencia: qué nombre, dirección y CIF ganan dentro de cada grupo, y por qué.
- Un Business Partner con roles de cliente y proveedor (CVI) cuando la misma empresa es ambas cosas.
- Una pantalla HTML estática para revisar la zona gris: aprobar o rechazar, con las pruebas a la vista.
- Fichero de correspondencia sistema/clave antigua → BP, listo para la plantilla de migración.

## Fase 5: publicar (unas horas)

- README con cifras finales, un diagrama y un GIF de la pantalla de revisión.
- Repositorio público en tu GitHub personal, post en LinkedIn y una línea en «Proyectos» del CV.

## Reglas del proyecto

- Siempre datos sintéticos. Nada de Syntax: ni código, ni nombres de clientes, ni datos de sistemas reales.
- En el Mac de Syntax, solo Python estándar y ficheros de texto. Lo que necesite instalar paquetes o claves de API, en tu ordenador personal.
- `data/` y `out/` no se suben: se regeneran con la semilla.
