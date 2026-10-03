# Tasks: NLQ Quality Benchmark
## From Natural-Language Data Quality Policies to Verified Executable Controls

> Cada tarea referencia: etapa del pipeline, criterio de validación, estado real del artefacto.
> Los datos están en `data/raw/` (86 datasets con CSV verificados, no en cache).

---

## Estado de implementación

| Etapa | Nombre | Implementada | Pendiente |
|:-:|---|---|---|
| 1 | Canonicalización (P7) | T4.1 ✅ | — |
| 2 | Alcance y evidencia | T4.2 ✅, T4.3 ✅ | — |
| 3 | Planificación lógica | T4.4 ✅ | — |
| 4 | Router de complejidad | T4.5 ✅ | — |
| 5 | TDD Agent (P8) | T4.6 ⏳ código+integración escrita, falta pytest | T4.6 |
| 5 | Generación + Dynamic RAG | T4.7 ✅ | — |
| 6 | AST Guard (P9) | T4.8 ✅ | — |
| 7 | Sandbox (P10) | T4.9 ✅, T1.5 ✅ | — |
| 8 | Pruebas funcionales oracle | T4.10 ⏳, T5.1 ✅, T5.2 ⏳ fix needed, T5.3 ✅ | T4.10, T5.2 fix |
| 9 | Repair Agent (P11) | T4.11 ✅ | — |
| 10 | Validación metamórfica | T6.1 ✅, T6.2 ✅, T6.3 ✅ | T6.4 ⏳ |
| 11 | Adjudicación final | T4.12 ✅ | — |

## Estado de datos (sincronizado 2026-09-26)

| Componente | Estado | Ruta real |
|---|---|---|
| Datasets con CSV | **86** eligible=True | `data/raw/{owner}/{slug}/vlatest/raw/` |
| Registry | 86 entradas | `data/registry/datasets.csv` |
| Reglas REVIEWED | 20 (R-0101..R-0120) | `data/rules/pilot_reviewed_20.jsonl` |
| Reglas GENERATED | 180 (R-0121..R-0300) | `data/rules/pilot_rules_200.jsonl` |
| Predicciones B0 | 20 reglas, 100% syntax | `artifacts/predictions/pilot/B0/predictions.parquet` |
| Predicciones B1 | 20 reglas, 100% syntax | `artifacts/predictions/pilot/B1/predictions.parquet` |
| Predicciones B3 | 20 reglas, 100% syntax | `artifacts/predictions/pilot/B3_seed42/predictions.parquet` |
| **F1 funcional B0** | **0.5683** (18/20 reglas) | `artifacts/metrics/pilot/B0_metrics.parquet` ✅ |
| **F1 funcional B1** | **0.4009** (18/20 reglas) | `artifacts/metrics/pilot/B1_metrics.parquet` ✅ |
| **F1 funcional B3** | **0.6254** (18/20 reglas) | `artifacts/metrics/pilot/B3_seed42_metrics.parquet` ✅ |
| Natural errors report | 119 registros, 17 datasets | `artifacts/metrics/pilot/natural_errors_report.csv` ✅ |
| QLoRA adapters | seeds 42/123/7, loss 3.29 | `artifacts/adapters/qlora_nl2code_seed*/` |

---

## Fase 0 — Auditoría

- [x] **T0.1** Inventariar código, modelos, adapters, datos, resultados.
- [x] **T0.2** Verificar Qwen2.5-7B-Instruct commit `a09a35458c`. 3 adapters hash `70331ccb`.
- [x] **T0.3** 200 pares entrenamiento. SHA-256: `70331ccb3ef914d72df0feaade1fd12b5a2d7432100feb7d3a9bc75bf232ea5c`.
- [x] **T0.4** Papers: Wang & Zhu 2024, Símola et al. 2026. Matrix en `design.md` §17.
- [x] **T0.5** ADRs: orquestación, sandbox, tracking, almacenamiento, backend.
- [x] **T0.6** Estimador de costos. Full-run bloqueado sin presupuesto.

---

## Fase 1 — Fundaciones

- [x] **T1.1** Entorno reproducible, lockfile, CI, lint, typing, seguridad.
- [x] **T1.2** Modelos Pydantic: Dataset, Rule, IR, AgentResult, RunManifest, Prediction.
- [x] **T1.3** Logging estructurado, IDs, hashes, MLflow.
- [x] **T1.4** Máquina de estados 15 estados.
- [x] **T1.5** Sandbox + suite adversarial.
- [x] **T1.6** Política secrets.

---

## Fase 2 — Datos del benchmark

- [x] **T2.1** Búsqueda y metadata Kaggle API.
- [x] **T2.2** 200 slugs curados en `scripts/download_200.py`.
- [x] **T2.3** Descarga con manifiestos SHA-256. Estructura: `data/raw/{owner}/{slug}/vlatest/`.
- [x] **T2.4** Perfiles CSV/Parquet/multitabla con DuckDB.
- [x] **T2.5** Detección de mirrors y duplicados.
- [x] **T2.6** **86 datasets con CSV** en `data/raw/`. Registry actualizado. Frozen `pilot-200_20260926T070825Z.csv`.
  - _Script:_ `python scripts/update_registry_from_raw.py`
- [x] **T2.7** 72 datasets sin CSV eliminados. 86 usables.

---

## Fase 3 — Corpus de reglas

- [x] **T3.1** Taxonomía: 6 dimensiones, 3 niveles, operadores lógicos.
- [x] **T3.2** Review queue DRAFT/REVIEWED/FROZEN.
- [x] **T3.3** Generador asistido. Promoción manual.
- [x] **T3.4** Casos positivo, negativo, frontera, ambiguo, no aplicable.
- [x] **T3.5** Mutaciones controladas con provenance.

- [ ] **T3.6** 200 reglas con distribución 20%/40%/40%.
  - _Estado:_ 20 REVIEWED (80% fácil, 0% difícil) + 180 GENERATED sin revisar.
  - _Herramienta disponible:_ `python scripts/generate_difficult_rules.py --all --target 160`
  - _Criterio:_ `python scripts/audit_rules.py --target 200` reporta distribución correcta.

- [ ] **T3.7** 500 reglas sobre 50+ datasets. Prerequisito: T3.6.
- [ ] **T3.8** 1,000 reglas. Prerequisito: T3.7.
- [x] **T3.9** Auditoría automática de cobertura.
- [ ] **T3.10** Anti-leakage semántico entre splits.

---

## Fase 4 — Agentes del pipeline

### Etapa 1 (P7) — Símola §3.1, TIC 2024
- [x] **T4.1** Canonicalizer. `src/agents/canonicalizer.py`. Configs: B1,B2,B4,B5,P,B_conf.

### Etapas 2-3 — Símola §3.2-3.3, PlanCompiler 2025
- [x] **T4.2** Scope Resolver. `src/agents/scope_resolver.py`.
- [x] **T4.3** Evidence Locator. `src/agents/evidence_locator.py`.
- [x] **T4.4** Logical Planner. `src/agents/logical_planner.py`.

### Etapa 4 — DecoSearch 2025
- [x] **T4.5** Router + Gate ML. `src/agents/router.py`.

### Etapa 5 (P8) — Schafer 2024, LLM4TDD 2023
- [ ] **T4.6** TDD Agent integrado en pipeline.
  - _Estado:_ `src/agents/tdd_agent.py` ✅. `src/orchestration/pipeline_runner.py` ✅ (integrado en Stage 5a).
  - _Pendiente:_ `pytest tests/test_tdd_agent.py`. Verificar en ejecución B5.
  - _Configs:_ B5, P, B_conf.

- [x] **T4.7** Generadores + Dynamic RAG. `src/agents/generators/`. Todas las configs.

### Etapas 6-7 (P9/P10) — SandboxEval 2024, Rashidi 2025
- [x] **T4.8** AST Guard (P9). `src/agents/ast_guard.py`. Configs: B5,P,B_conf.
- [x] **T4.9** Sandbox (P10). `src/agents/sandbox.py`. Configs: B5,P,B_conf.

### Etapa 8 — HoloClean 2017, RAHA 2019
- [ ] **T4.10** Pruebas funcionales contra oracle (integrado en B5/P).
  - _Prerequisito:_ T4.6 + T5.2 fix.

### Etapa 9 (P11) — VeriHarness 2025
- [x] **T4.11** Repair Agent. `src/agents/repair_agent.py`. Configs: B5,P,B_conf.

### Etapa 11
- [x] **T4.12** Adjudicator. `src/agents/adjudicator.py`.

---

## Fase 5 — Oracle y evaluación funcional

- [x] **T5.1** Perfilador de errores naturales.
  - _Estado:_ `src/evaluation/oracle_injector.py:profile_natural_errors()` ✅. 119 errores naturales en 17 datasets (2026-09-26).

- [ ] **T5.2** Injector de errores controlados — **requiere fix**.
  - _Estado:_ Código escrito. BUG-008/009 detectados en ejecución real:
    - `uniqueness`: inyecta `str + "_DUPLICATE"` en columnas int64 → falla con dtype error
    - `consistency`: inyecta `"INCONSISTENT_xxx"` string en columnas int64 → falla
  - _Fix requerido:_ En `_inject_by_dimension()`:
    - `uniqueness` int64: inyectar `original_val + 999999` (no string)
    - `consistency` int64: inyectar `-abs(original_val) - 1` (ya numérico, verificar dtype)
  - _Criterio:_ R-0109 y R-0110 pasan sin error de dtype.

- [x] **T5.3** `scripts/compute_metrics.py` — **COMPLETADO 2026-09-26**.
  - _Resultados:_ B0 F1=0.5683 | B1 F1=0.4009 | B3 F1=0.6254 (18/20 reglas, ver §2.2)
  - _BUG-001 validado:_ B3/R-0120 F1=0.028 < 1.0 ✅
  - _Artefactos:_ `artifacts/metrics/pilot/*_metrics.parquet`

- [ ] **T5.4** Bootstrap CI 95% agrupado por dataset. Prerequisito: más reglas evaluables.
- [ ] **T5.5** McNemar test pareado. Prerequisito: T5.4.
- [ ] **T5.6** Corrección de Holm. Prerequisito: T5.5.

---

## Fase 5b — Corrección de bugs de infraestructura (T9.2)

Bugs identificados durante la ejecución real de compute_metrics.py (2026-09-26).

- [ ] **T5.7** Fix BUG-008/009: oracle_injector dtype int64.
  - _Fix:_ `src/evaluation/oracle_injector.py:_inject_by_dimension()` — preservar dtype al inyectar uniqueness y consistency.
  - _Criterio:_ R-0109 y R-0110 producen F1 calculable (no SKIP).

- [ ] **T5.8** Investigar BUG-007: R-0117 columna 'AccountBalance' no en CSV.
  - _Verificar:_ `data/raw/goyaladi/fraud-detection-dataset/vlatest/raw/` — listar columnas reales.
  - _Si columna no existe:_ corregir la regla R-0117 con el nombre real de la columna.

- [ ] **T5.9** Investigar BUG-010: alta tasa FP en R-0105, R-0111, R-0113.
  - _R-0105:_ Gender enum, 2794 FP — verificar si el dataset tiene valores no estándar.
  - _R-0111:_ Balance consistency, 2075 FP — la tolerancia en la fórmula puede no estar implementada.
  - _R-0113:_ Quantity returns 130 FP — el dataset tiene devoluciones (negative Quantity legítimas).

- [ ] **T5.10** Investigar BUG-011: uniqueness F1=0 para R-0114, R-0118.
  - _Posible causa:_ código generado verifica unicidad solo en la fila actual, no en el DataFrame completo.
  - _Fix:_ El código debe usar `df.duplicated(subset=['col'], keep=False)`.

---

## Fase 6 — Validación metamórfica

- [x] **T6.1** Generador de paráfrasis.
- [x] **T6.2** Medidas de similitud.
- [x] **T6.3** Comparación conductual.
- [ ] **T6.4** Piloto n=3/5/7 sobre 100 reglas. Prerequisito: T5.3 ✅ + split definido.
- [x] **T6.5** Congelar n, modelo, prompt, umbral.

---

## Fase 7 — Modelos y adaptadores

- [x] **T7.1** B0: F1=0.5683. `artifacts/predictions/pilot/B0/`.
- [x] **T7.2** B1: F1=0.4009. BUG-002 confirmado en R-0120.
- [x] **T7.3** B2: RAG estático implementado.
- [x] **T7.4** B3: F1=0.6254. BUG-001 confirmado en R-0120.
- [x] **T7.5** B4: QLoRA NL→IR.
- [ ] **T7.6** B5: pipeline completo etapas 1-11.
  - _Prerequisito:_ T4.6 pytest + T4.10 + T5.2 fix.
  - _Criterio:_ B5 F1 > B3 en reglas HISTORICAL (una vez T3.6 completado).
- [ ] **T7.7** P: B5 + QLoRA NL→IR.
- [x] **T7.8** Paridad de datos, decoding, métricas.
- [ ] **T7.9** B_conf: calidad-datos-v4 (Ollama) sobre Kaggle datasets.
  - _Ruta:_ `C:\Users\User\Documents\Conference_LLM_DataQuality\finetuned_merged\`

---

## Fase 8 — Splits

- [x] **T8.1** Deduplicación.
- [x] **T8.2** Split 60/20/20 por familia.
- [x] **T8.3** Tests anti-leakage.
- [x] **T8.4** Test bloqueado hasta T9.4.

---

## Fase 9 — Pilotos y preregistro

- [ ] **T9.1** Matriz completa: 20 datasets, 200 reglas, B0-B5-P.
  - _Prerequisito:_ T3.6 (reglas difíciles) + T5.2 fix + T7.6 (B5).
  - _Criterio:_ F1(B5) > F1(B3) en reglas HISTORICAL.

- [ ] **T9.2** Corregir bugs de infraestructura (T5.7–T5.10) sin ver el test set.
  - _Bugs a corregir:_ BUG-007, BUG-008, BUG-009, BUG-010, BUG-011.

- [ ] **T9.3** 86 datasets, 500+ reglas. Successive halving.
- [ ] **T9.4** Congelar hipótesis, métricas, criterios H1.
- [ ] **T9.5** Preregistration interna.

---

## Fase 10 — Full run

- [ ] **T10.1** Gate: datos, seguridad, oracles, GPU, almacenamiento.
- [ ] **T10.2** Baselines + finalistas / 1,000 reglas.
- [ ] **T10.3** Ablaciones: retirar cada etapa (1-11) de B5.
- [ ] **T10.4** 3 seeds QLoRA; inferencia determinista.
- [ ] **T10.5** Test final UNA vez. Sellar predicciones.
- [ ] **T10.6** Registrar todos los fallos, retries, missing runs.

---

## Fase 11 — Análisis

- [ ] **T11.1** F1 por regla/dataset/grupo + CI bootstrap.
- [ ] **T11.2** McNemar, Wilcoxon, Holm, effect sizes.
- [ ] **T11.3** Modelos mixtos.
- [ ] **T11.4** H1: QLoRA/no-QLoRA/inconcluso.
- [ ] **T11.5** Errores lógicos: AND estricto, IFF, verdad vacua, alcance.
- [ ] **T11.6** Errores naturales vs inyectados separados.
- [ ] **T11.7** Tablas, figuras, informe, resultados negativos.
- [ ] **T11.8** Reproducción limpia.

---

## Trazabilidad actualizada

| Task | Etapa | Configs | Estado | Criterio |
|---|:-:|---|---|---|
| T4.1 | 1 (P7) | B1,B2,B4,B5,P,B_conf | ✅ | 0 blueprints incompletos al generador |
| T4.2 | 2 alcance | B1,B2,B4,B5,P,B_conf | ✅ | 0 excepciones por columnas inexistentes |
| T4.3 | 2 evidencia | B1,B2,B4,B5,P,B_conf | ✅ | ABSTAIN en verdad vacua |
| T4.4 | 3 planificación | B1,B2,B4,B5,P,B_conf | ✅ | IFF → 2 cláusulas |
| T4.5 | 4 router | B5,P | ✅ | 20 piloto → POINT_IN_TIME |
| T4.6 | 5 TDD (P8) | B5,P,B_conf | ⏳ | pytest pasa; TDD antes de CodeGen |
| T4.7 | 5 gen+RAG | Todas | ✅ | K ejemplos en prompt |
| T4.8 | 6 AST (P9) | B5,P,B_conf | ✅ | Patrón nombrado |
| T4.9 | 7 sandbox (P10) | B5,P,B_conf | ✅ | BUG-002 detectable |
| T4.10 | 8 oracle F1 | B5,P,B_conf | ⏳ | BUG-001 → F1 < 1.0 (ya validado en B3) |
| T4.11 | 9 repair (P11) | B5,P,B_conf | ✅ | HUMAN_REVIEW en intento 4 |
| T4.12 | 11 adjudicación | Todas | ✅ | 0 estados finales incorrectos |
| T5.1 | 8 natural errors | eval | ✅ | 119 errores en 17 datasets |
| T5.2 | 8 injector | eval | ⏳ fix | BUG-008/009 → dtype error |
| T5.3 | 8 compute F1 | eval | ✅ | B0=0.57 B1=0.40 B3=0.63 |
| T6.1-T6.3 | 10 metamórfica | B5,P | ✅ | Implementado |
| T6.4 | 10 piloto n=5 | B5,P | ⏳ | n congelado antes del test |
| T10.3 | ablación | post full-run | ⏳ | Δ F1 por etapa |
