# Paquete Kiro: benchmark NLQ para calidad de datos

Este paquete convierte la propuesta de investigación en una especificación ejecutable para Kiro.

## Uso recomendado

1. Copiar el contenido del paquete en la raíz del repositorio.
2. Colocar los dos artículos de apoyo en `papers/` sin versionarlos si su licencia no permite redistribución.
3. Abrir Kiro y usar un **Feature Spec Design-First**, porque ya existe una arquitectura multiagente y hay requisitos estrictos de seguridad, reproducibilidad y evaluación.
4. Pegar `MASTER_PROMPT.md` en la sesión del Spec.
5. Revisar y aprobar `requirements.md`, `design.md` y `tasks.md` antes de ejecutar tareas.
6. Invocar `/nlq-quality-experiment` cuando se quiera auditar o ejecutar una fase experimental.

Kiro genera Specs en tres artefactos: `requirements.md`, `design.md` y `tasks.md`. Los Skills se ubican en `.kiro/skills/<nombre>/SKILL.md` y el steering persistente en `.kiro/steering/`.

## Regla científica central

El sistema no debe “producir resultados que confirmen el éxito”. Debe ejecutar un protocolo preregistrado, guardar resultados reales y decidir si QLoRA aporta valor. Un resultado negativo, nulo o mixto debe conservarse y reportarse.

## Alcance cuantitativo

- 200 identificadores únicos de datasets públicos de Kaggle.
- 1,000 reglas canónicas de calidad, exactamente cinco por dataset.
- Objetivo inicial: 400 puntuales, 350 históricas y 250 ML-necesarias.
- Cinco dimensiones lingüísticas por regla solo después de un piloto que compare 3, 5 y 7 paráfrasis.
- Separación principal por dataset: 120 entrenamiento, 40 validación y 40 prueba.
- Las reglas de prueba, sus paráfrasis, esquemas y oráculos no pueden contaminar entrenamiento, RAG o selección de hiperparámetros.

## Fuentes metodológicas incorporadas

- Wang y Zhu (ICSE-NIER 2026), *Automatic Validation of LLM-Generated Code with Prompt Paraphrasing*: validación metamórfica, comparación por mayoría, experimento 3/5/7 y control de similitud entre paráfrasis.
- Simbola et al. (2026), verificación de políticas NL sobre descriptores YAML: canonicalización, resolución de alcance, localización de evidencia, evaluación estructurada, ablaciones y taxonomía de errores lógicos.
- Documentación de Kiro Specs y Skills: https://kiro.dev/docs/specs/ y https://kiro.dev/docs/skills/
- API pública de Kaggle: https://www.kaggle.com/docs/api
