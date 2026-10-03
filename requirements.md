# Requirements: NLQ Quality Benchmark

## R1 — Registro reproducible

**WHEN** el sistema incorpore un dataset **THE SYSTEM SHALL** registrar un `owner/slug` único, URL, versión, licencia, fecha, manifiesto SHA-256 y decisión de elegibilidad.

**Acceptance:** 200 entradas válidas; cero duplicados por slug o hash; todos los campos críticos completos.

## R2 — Uso responsable de Kaggle

**WHEN** se acceda a Kaggle **THE SYSTEM SHALL** usar la API oficial y secretos externos al repositorio.

**Acceptance:** no hay tokens en Git/logs; cada descarga es reproducible; datasets sin licencia verificable quedan excluidos.

## R3 — Corpus de reglas

**WHEN** se congele el benchmark **THE SYSTEM SHALL** contener exactamente 1,000 reglas canónicas, cinco por cada uno de los 200 datasets.

**Acceptance:** IDs únicos; conteos automáticos; cada regla posee IR, evidencia, pruebas y oráculo.

## R4 — Complejidad

**WHEN** se clasifique una regla **THE SYSTEM SHALL** asignar `POINT_IN_TIME`, `HISTORICAL`, `ML_NECESSARY` o `ABSTAIN` mediante criterios verificables.

**Acceptance:** objetivo 400/350/250; toda desviación está documentada; matriz de confusión contra etiqueta gold.

## R5 — Necesidad de ML

**IF** una regla se marca `ML_NECESSARY` **THEN THE SYSTEM SHALL** demostrar insuficiencia del baseline determinista, suficiencia de datos y evaluación fuera de muestra.

**Acceptance:** ninguna regla ML sin gate aprobado; splits temporales o por entidad sin leakage.

## R6 — Dimensiones

**WHEN** se construya el corpus **THE SYSTEM SHALL** cubrir completitud, validez, consistencia, unicidad, exactitud y oportunidad.

**Acceptance:** cada dimensión representa al menos 10% del corpus o existe una desviación aprobada antes de test.

## R7 — Interpretación estructurada

**WHEN** se procese una regla NL **THE SYSTEM SHALL** canonicalizar lógica, resolver alcance, localizar evidencia y emitir una IR versionada antes de generar código.

**Acceptance:** JSON Schema válido; operadores lógicos y no aplicabilidad explícitos; errores devuelven abstención o revisión.

## R8 — Flujo multiagente

**WHEN** exista un plan válido **THE SYSTEM SHALL** generar, validar por AST, ejecutar en sandbox, probar, reparar y adjudicar el artefacto.

**Acceptance:** trazas por transición; máximo de reparaciones configurable; ningún código no validado se etiqueta como exitoso.

## R9 — Seguridad

**WHEN** se ejecute código generado **THE SYSTEM SHALL** usar un contenedor sin red, usuario no root y límites de recursos.

**Acceptance:** suite adversarial aprobada; intentos de filesystem, red, shell y procesos bloqueados; incidentes detienen el run.

## R10 — Validación semántica

**WHEN** un artefacto pase AST y ejecución **THE SYSTEM SHALL** evaluarlo contra pruebas funcionales y oráculos.

**Acceptance:** métricas de detección, reparación y sobrecorrección; ejecución sin error no equivale a éxito.

## R11 — Paráfrasis

**WHEN** se valide robustez lingüística **THE SYSTEM SHALL** comparar el comportamiento generado por formulaciones semánticamente equivalentes.

**Acceptance:** piloto 3/5/7; baseline de repetición; control de similitud y deriva; número final congelado usando validación.

## R12 — Splits

**WHEN** se dividan los datos **THE SYSTEM SHALL** agrupar por dataset y familia, manteniendo variantes y paráfrasis juntas.

**Acceptance:** 120/40/40 datasets; auditoría automática de fugas igual a cero.

## R13 — Baselines

**WHEN** se evalúe la propuesta **THE SYSTEM SHALL** comparar prompt directo, prompt estructurado, few-shot/RAG, QLoRA NL→código, QLoRA NL→IR y sistemas completos con/sin QLoRA.

**Acceptance:** interfaz, datos, presupuesto y métricas comparables; cambios simultáneos se etiquetan como comparación de sistema, no causal.

## R14 — Ablación

**WHEN** se atribuya una mejora **THE SYSTEM SHALL** retirar individualmente canonicalización, alcance, evidencia, IR, AST, sandbox-feedback, reparación, pruebas y paráfrasis.

**Acceptance:** tabla con deltas e intervalos para cada componente.

## R15 — Decisión QLoRA

**WHEN** finalice el test **THE SYSTEM SHALL** aplicar criterios preregistrados para seleccionar QLoRA, no-QLoRA, híbrido o inconcluso.

**Acceptance:** decisión calculada automáticamente desde resultados bloqueados; no existe una salida hardcodeada.

## R16 — Trazabilidad

**WHEN** se publique una métrica **THE SYSTEM SHALL** enlazarla a predicciones, manifiesto, configuración, commit y entorno.

**Acceptance:** toda tabla puede regenerarse desde un comando limpio.

## R17 — Estadística

**WHEN** se comparen configuraciones **THE SYSTEM SHALL** usar análisis pareado, intervalos agrupados por dataset, tamaños de efecto y corrección múltiple.

**Acceptance:** scripts preregistrados; resultados faltantes visibles; análisis exploratorios etiquetados.

## R18 — Fases

**WHEN** una fase avance **THE SYSTEM SHALL** verificar criterios de cierre de la fase anterior.

**Acceptance:** 20/100 y 50/250 completados antes de 200/1000; test final permanece cerrado hasta congelación.

## R19 — Fallos y abstención

**WHEN** falte evidencia, la regla sea ambigua o el riesgo sea excesivo **THE SYSTEM SHALL** emitir `HUMAN_REVIEW` o `ABSTAIN` con causa estructurada.

**Acceptance:** se miden cobertura, riesgo y abstención correcta/incorrecta.

## R20 — Reporte honesto

**WHEN** se produzca el informe **THE SYSTEM SHALL** incluir resultados favorables, negativos, nulos, fallos de infraestructura y amenazas a validez.

**Acceptance:** no hay valores placeholder; todas las afirmaciones cuantitativas tienen artefactos de respaldo.
