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

## Fase 2: mejores reglas (hecha el 1-nov-2026)

Todo está en `DECISIONES.md`. En test, las fusiones erróneas bajan de 16 a 1, la cobertura sube de 90,0 % a 92,0 % y el techo con revisión perfecta sube a 99,4 %.

**Decidido el 1-nov:** se mantienen D1 y D4. D4 se revisa en la fase 3 según si el LLM sabe separar mudanzas de homónimas.

**Pendiente, opcional:**
- que «CORCA» no se convierta en COMERCIAL (expandir solo si la palabra va seguida de punto);
- una métrica que pese más una fusión errónea que un duplicado perdido.

## Fase 3: LLM en la zona gris (código listo el 1-nov; falta ejecutarlo)

El diseño y sus motivos están en `DECISIONES.md` (D5–D10). El código está en `say_my_name/adjudicate.py` y se prueba sin red con un cliente falso.

**Pasos en tu ordenador personal**, con tu clave de Anthropic y un límite de gasto en el workspace:

```bash
git pull
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[llm]"                        # solo instala anthropic==1.17.0
export ANTHROPIC_API_KEY=...                   # o `ant auth login`; nunca en el repo
make dev && make eval                          # regenera data/ y out/ (no están en git)
make llm-sample                                # 50 pares de desarrollo con Haiku: céntimos
make llm-dev                                   # todo desarrollo con Haiku (≈ 0,36 $)
make llm-dev MODEL=sonnet                      # todo desarrollo con Sonnet (≈ 7 $)
make llm-dev EFFORT=low                        # y otro nivel de esfuerzo
make llm-test MODEL=<el elegido> EFFORT=<el elegido>   # una sola vez, al final
```

Cada ejecución deja `out/<dev|test>/llm-<modelo>-<esfuerzo>/report.md`, con la precisión de las fusiones del LLM, lo que pasa a personas, F1 del sistema completo, coste por cada mil registros y latencia.

**Para dar la fase por buena:**
- Que el LLM no meta más fusiones erróneas que las reglas solas, porque una fusión errónea es peor que un duplicado perdido.
- Que el F1 de «reglas + LLM + personas» se acerque al techo (99,4 % en test).
- Que lo que pasa a personas sea una fracción pequeña de la zona gris.

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
