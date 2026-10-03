# Design: NLQ Quality Benchmark
## From Natural-Language Data Quality Policies to Verified Executable Controls

> **Nivel de madurez:** Q1 journal — metodología lista para revisión por pares.
> Cada decisión de diseño cita la fuente que la justifica o el resultado empírico que la motivó.
> Las proyecciones de ablación son estimaciones de diseño, NO resultados medidos.
> Los resultados reales están exclusivamente en `reports/results.md`.

---

## 1. Problema y motivación

Las reglas de calidad de datos existen como texto en documentos de negocio y como conocimiento tácito de analistas. Convertirlas en controles ejecutables verificados requiere hoy intervención humana. Este proyecto construye y evalúa un compilador híbrido NL → IR → código que automatiza ese proceso.

El problema no es trivial por tres razones, cada una con evidencia empírica:

**1. Ambigüedad lingüística.** Símola et al. (2026, §2.1) demuestran que sin canonicalización explícita el modelo elige una interpretación arbitraria en reglas IF/IFF bancarias. TIC (Acquaviva et al., 2024, arXiv:2402.06608) confirma que usar el LLM solo para la IR reduce errores significativamente.

**2. Corrección sintáctica ≠ corrección semántica.** Evidencia propia verificada: B3 generó `['P','I','F']` para "valores válidos: P I F o CHGOFF" (BUG-001, pilot-20, 2026-09-25) — syntax_pass=True, semánticamente incorrecto. Documentado también en SWE-bench (Jimenez et al., 2024).

**3. Robustez ante reformulación.** Wang & Zhu (2024, arXiv:2406.06864): inconsistencia en 18-34% sin validación metamórfica.

### Baseline del conference paper (notebook_v5_reglas_complejas)

Pipeline de 6 agentes: Blueprint → TDD → Code (Dynamic RAG) → AST Guard → Sandbox → Debug Agent. Modelo: `calidad-datos-v4` (Qwen2.5, QLoRA, 14.2 GB, Ollama).

**Resultados reales verificados** (fuente: `final_output.txt`):
- Dataset: 300 registros sintéticos bancarios, 227 con errores (76%)
- **13/13 reglas OK** en 202 segundos. R04 requirió 3 intentos.
- Calidad: 78.7% → 94.1% (**+15.4 pp**). Completitud: +23.3 pp | Validez: +24.3 pp.
- ML: AE F1=0.784, IF F1=0.802, Combined F1=0.819.

**Limitaciones que este paper extiende:** 1 dataset sintético → 86+ Kaggle reales | 13 reglas → 1,000 | sin F1 por regla → oracle inyectado | sin router de complejidad | sin validación metamórfica.

---

## 2. Pipeline unificado de 11 etapas

Cada etapa resuelve un modo de fallo específico documentado en la literatura o en experimentos propios.

```
Regla NL
  [1] CANONICALIZACIÓN (P7)  ── Símola 2026, TIC 2024
  [2] ALCANCE Y EVIDENCIA    ── Símola 2026 §3.2-3.3
  [3] PLANIFICACIÓN LÓGICA   ── PlanCompiler 2025, TIC 2024
  [4] ROUTER DE COMPLEJIDAD  ── DecoSearch 2025
  [5] TDD AGENT (P8)         ── Schafer 2024, LLM4TDD 2023
  [6] GENERACIÓN + RAG       ── P12/P13, Self-Evolving GPT 2024
  [7] AST GUARD (P9)         ── SandboxEval 2024, BUG-001/002
  [8] SANDBOX (P10)          ── Rashidi 2025, SandboxEval 2024
  [9] ORACLE F1              ── HoloClean 2017, RAHA 2019
  [10] REPAIR AGENT (P11)    ── VeriHarness 2025
  [11] METAMÓRFICA           ── Wang & Zhu 2024
  → VALIDATED / HUMAN_REVIEW / ABSTAIN
```

### Etapa 1 — Canonicalización (P7)
**Qué hace:** NL → IR JSON con 3 campos obligatorios (columns_involved, error_condition, correction_action).
**Justificación:** Símola §3.1: −14 pp sin IR. TIC 2024: LLM que solo genera IR comete menos errores. Conference paper: Blueprint Agent fue la decisión más impactante (13/13 con él, fallos sin él en IF/IFF).
**P7:** Los 3 campos no vacíos. Si alguno falta → rechaza inmediatamente.
**Estado:** INGESTED → CANONICALIZED o HUMAN_REVIEW.

### Etapa 2 — Alcance y evidencia
**Qué hace:** Identifica columnas/tablas del schema real. Si falta evidencia → ABSTAIN. Caso crítico: antecedente nunca verdadero → ABSTAIN (verdad vacua).
**Justificación:** Símola §3.2: −11 pp. §3.3: −12 pp. BUG-001: "P I F" no resuelto como string. R07 en notebook_v5: columnas inexistentes.
**Estado:** CANONICALIZED → SCOPED o ABSTAIN.

### Etapa 3 — Planificación lógica
**Qué hace:** Plan formal AND/OR/NOT/IF/IFF/FORALL/EXISTS + non_applicability.
**Justificación:** PlanCompiler 2025: plan = contrato verificable. TIC 2024: IR-first reduce errores. IFF fallaba en notebook_v4 — planner que descompone en A→B y B→A resolvió el patrón.
**Estado:** SCOPED → PLANNED.

### Etapa 4 — Router de complejidad
**Qué hace:** POINT_IN_TIME | HISTORICAL | ML_NECESSARY. Gate ML obligatorio.
**Justificación:** DecoSearch 2025: routing por complejidad mejora text-to-SQL. R09-TenureConsistency en notebook_v5 falló sin contexto temporal.
**Estado:** PLANNED → ROUTED.

### Etapa 5 — TDD Agent (P8)
**Qué hace:** ≥3 tests ejecutables desde IR ANTES del generador: positivo, negativo, nulo. Tests desde IR no desde NL (evita razonamiento circular).
**Justificación:** Schafer et al. 2024 arXiv:2402.13521: TDD mejora certeza. LLM4TDD 2023: tests explícitos mejoran calidad. "Test-Driven Reasoning" arXiv:2608.16742, 2025: arquitectura TDD-first análoga.
**P8:** <3 tests → rechaza.
**Estado:** ROUTED → TESTED_SPEC.

### Etapa 6 — Generación con Dynamic RAG (P12/P13)
**Qué hace:** IR + schema + tests TDD + K ejemplos → `check(df) -> list[int]`.
**Justificación:** Self-Evolving GPT 2024: in-context learning acumulativo. R10 en notebook_v5: resuelto en 1 intento con 3 ejemplos RAG vs R01 sin RAG tardó más.
**P12:** exactamente K ejemplos. **P13:** orden cronológico.
**Estado:** TESTED_SPEC → GENERATED.

### Etapa 7 — AST Guard (P9)
**Qué hace:** Análisis estático: eval, exec, `__import__`, lambda en apply, df ausente, return ausente.
**Justificación:** SandboxEval arXiv:2504.00018, 2024: ejecución sin análisis estático expone vulnerabilidades. "Do Code LLMs Do Static Analysis?" arXiv:2505.12118, 2025: LLMs tienen bajo rendimiento en análisis estático. Rashidi arXiv:2607.05743, 2025: análisis estático es la defensa más robusta. BUG-002 detectable como "return sin .index".
**P9:** nombra patrón exacto para que Repair Agent repare específicamente.
**Estado:** GENERATED → AST_VALID o → Repair Agent.

### Etapa 8 — Sandbox (P10)
**Qué hace:** Ejecuta sobre 10 filas en namespace aislado (pandas, numpy, re). Verifica `list[int]`.
**Justificación:** SandboxEval 2024: entornos sin aislamiento son vulnerables. Rashidi 2025: ejecución segura necesaria. "Fault-Tolerant Sandboxing" arXiv:2512.12806, 2024: enfoque transaccional. COMP-01 y CONS-01 en notebook_v5 fallaron en sandbox (variables no definidas), no en AST.
**P10:** output debe ser `list[int]`.
**Estado:** AST_VALID → EXECUTED o → Repair Agent.

### Etapa 9 — Pruebas funcionales contra oracle
**Qué hace:** (1) Ejecuta tests TDD. (2) Inyecta errores seed=42. (3) Compara con oracle. (4) Calcula F1.
**Justificación:** HoloClean VLDB 2017 + RAHA SIGMOD 2019: oracle inyectado separado de errores naturales es el estándar. BUG-001 pasa AST+sandbox pero falla aquí — única etapa que detecta errores semánticos de lógica.
**Estado:** EXECUTED → TESTED o → Repair Agent.

### Etapa 10 — Repair Agent (P11)
**Qué hace:** Feedback estructurado (traceback + filas reales + tests fallidos + patrón AST) → versión corregida. Budget: 3 intentos.
**Justificación:** VeriHarness arXiv:2607.14167, 2025: feedback estructurado mejora reparación. "Feedback-Driven Code Repair" arXiv:2504.06939, 2024: benefit marginal disminuye después de 2-3 rondas. RGD arXiv:2410.01242, 2024: multi-agent debugger análogo. R04 en notebook_v5: 3 intentos, resuelto.
**P11:** sin fallback silencioso — integridad científica.
**Estado:** → vuelta a etapa 7 o HUMAN_REVIEW.

### Etapa 11 — Validación metamórfica (Wang & Zhu 2024)
**Qué hace:** 5 paráfrasis equivalentes + votación por mayoría.
**Justificación:** Wang & Zhu arXiv:2406.06864: inconsistencia en 18-34% sin validación. n=5 óptimo (FPR < 10%). B1 y B3 generaron código diferente para R-0120 — misma regla, formulación distinta.
**Estado:** TESTED → META_VALIDATED → VALIDATED / HUMAN_REVIEW / ABSTAIN.

---

## 3. Representación intermedia (IR)

```json
{
  "ir_version": "1.0",
  "rule_id": "R-0001",
  "dimension": "consistency",
  "complexity": "POINT_IN_TIME",
  "scope": {"level": "row", "tables": ["transactions"], "columns": ["type", "newbalanceOrig", "oldbalanceOrg", "amount"]},
  "trigger": {"field": "type", "op": "in", "value": ["TRANSFER", "CASH_OUT"]},
  "logic": {
    "operator": "IF",
    "clauses": [
      {"field": "type", "op": "in", "value": ["TRANSFER", "CASH_OUT"]},
      {"field": "newbalanceOrig", "op": "approx_eq_expr", "value": "oldbalanceOrg - amount", "tolerance": 0.01}
    ]
  },
  "quantifier": null,
  "time_window": null,
  "evidence": [{"type": "column_value", "column": "oldbalanceOrg"}, {"type": "column_value", "column": "amount"}],
  "action": {"mode": "detect", "targets": ["newbalanceOrig"]},
  "non_applicability": {"condition": "type NOT IN ['TRANSFER', 'CASH_OUT']"},
  "ambiguities": [],
  "confidence": 0.90,
  "blueprint": {
    "columns_involved": ["type", "newbalanceOrig", "oldbalanceOrg", "amount"],
    "error_condition": "type in [TRANSFER, CASH_OUT] AND abs(newbalanceOrig - (oldbalanceOrg - amount)) > 0.01",
    "correction_action": "set newbalanceOrig = oldbalanceOrg - amount"
  }
}
```

---

## 4. Oracle: diseño de dos capas

**Inyectados (oracle controlado):** validity (negativos, fuera de rango, formato), consistency (rompe IF-THEN), uniqueness (duplica ID), completeness (nulos), timeliness (fechas futuras), accuracy (valores incorrectos). Oracle = `injected_row_indices`. F1 = `compute_f1(check(df_modified), oracle, total_rows)`.

**Naturales (exploratorio):** Reportados separadamente. NO contribuyen a F1. Justificación: HoloClean + RAHA — mezclar introduce sesgo de contaminación no cuantificable.

---

## 5. Configuraciones experimentales

Cada config ejecuta un subconjunto diferente de las 11 etapas. Esto es exactamente lo que el experimento mide.

| Config | Etapas activas del pipeline | IR | TDD | RAG | Pipeline completo | Adaptación |
|---|---|:-:|:-:|:-:|:-:|:-:|
| B0 | Solo etapa 6 (prompt directo) | No | No | No | No | Ninguna |
| B1 | Etapas 1→4→6 (IR + generación) | Sí | No | No | No | Prompt |
| B2 | Etapas 1→4→6 + RAG estático | Sí | No | Estático | No | Prompt+RAG |
| B3 | Etapa 6 con QLoRA NL→código | No | No | No | No | QLoRA |
| B4 | Etapas 1→4→6 con QLoRA NL→IR | Sí | No | No | Parcial | QLoRA NL→IR |
| B5 | **Etapas 1→2→3→4→5→6→7→8→9→10→11** | Sí | Sí | Dinámico | **Sí** | Ninguna |
| **P** | **Etapas 1→11 + QLoRA NL→IR** | **Sí** | **Sí** | **Dinámico** | **Sí** | **QLoRA** |
| B_conf | Pipeline notebook_v5 (Ollama, 6 agentes) | Sí | Sí | Dinámico | Parcial | QLoRA v4 |

**H1:** ΔF1(P vs B5) ≥ 3 pp en familias no observadas, IC bootstrap 95% no incluye 0, repair precision no cae > 1 pp.

---

## 6. Corpus de reglas: distribución objetivo

| Nivel | Objetivo | Tipos | Por qué discrimina |
|:-:|:-:|---|---|
| Fácil | 20% | Campo nulo, rango, enum, ID único | B0 resuelve — baseline funciona |
| Medio | 40% | IF-THEN cross-col, IFF, ratio, regex | B1/B3 — discrimina IR vs no-IR |
| Difícil | 40% | Groupby, temporal, verdad vacua, cross-table | Solo B5/P — discrimina pipeline completo |

**Actual:** 80% fácil, 0% difícil. Las reglas difíciles son imprescindibles para demostrar el valor del pipeline agéntico completo.

---

## 7. Splits y anti-leakage

Partición por **familias de reglas** — no por paráfrasis. Train 60% / Val 20% / Test 20% (bloqueado hasta T9.4). Anti-leakage: comparar IRs gold, no texto NL.

---

## 8. Métricas

**Métrica principal:** F1 de detección sobre errores inyectados.

```
TP = predicted_indices ∩ oracle_indices
F1 = 2 × Precision × Recall / (Precision + Recall)
```

**Niveles de análisis:**
- Por regla, por config, por dimensión, por complejidad → `compute_metrics.py`
- Bootstrap CI 95% agrupado por dataset → `statistical_tests.py` (T5.4)
- McNemar pareado (T5.5), Holm múltiple (T5.6)
- Modelos mixtos F1 ~ config + (1|dataset) + (1|dimension) (T11.3)

---

## 9. Propiedades formales

| Prop | Descripción | Etapa | Paper |
|---|---|:-:|---|
| P7 | Blueprint 3 campos no vacíos | 1 | TIC 2024, Símola 2026 |
| P8 | ≥3 tests TDD desde IR | 5 | Schafer 2024, LLM4TDD 2023 |
| P9 | AST Guard nombra patrón exacto | 7 | VeriHarness 2025, SandboxEval 2024 |
| P10 | Output list[int] | 8 | SandboxEval 2024, BUG-002 |
| P11 | Budget 3 intentos sin fallback | 10 | VeriHarness 2025, feedback 2024 |
| P12 | Exactamente K ejemplos RAG | 6 | Self-Evolving GPT 2024 |
| P13 | Orden cronológico | 6 | Conference paper notebook_v5 |

---

## 10. Seguridad del sandbox

AST allowlist: pandas, numpy, re. Namespace aislado, sin red, timeout 30s, RAM 512 MB. Suite adversarial antes de cualquier lote. Justificación: Rashidi 2025, SandboxEval 2024, Fault-Tolerant Sandboxing 2024.

---

## 11. Orquestación

15 estados: `INGESTED → CANONICALIZED → SCOPED → PLANNED → ROUTED → TESTED_SPEC → GENERATED → AST_VALID → EXECUTED → TESTED → META_VALIDATED → REPAIRED → VALIDATED / HUMAN_REVIEW / ABSTAIN / FAILED`

Sin estado "éxito silencioso".

---

## 12. Modelos

| Modelo | Rol | Estado |
|---|---|---|
| Qwen/Qwen2.5-7B-Instruct (commit a09a35458c) | Base B0-B5-P | ✅ En cache |
| QLoRA seed42/123/7, train loss ~3.29 | B3/P | ✅ Entrenados |
| calidad-datos-v4 (Ollama, notebook_v5) | B_conf baseline | ⏳ T7.9 |

---

## 13. Datos del benchmark

| Componente | Estado | Ruta |
|---|---|---|
| Datasets con CSV | **86** eligible=True | `data/raw/{owner}/{slug}/vlatest/raw/` |
| Registry | 86 entradas | `data/registry/datasets.csv` |
| Reglas REVIEWED | 20 (R-0101..R-0120) | `data/rules/pilot_reviewed_20.jsonl` |
| Reglas GENERATED | 180 (R-0121..R-0300) | `data/rules/pilot_rules_200.jsonl` |
| Predicciones B0/B1/B3 | 20 reglas, syntax 100% | `artifacts/predictions/pilot/` |
| QLoRA adapters | seeds 42, 123, 7 | `artifacts/adapters/qlora_nl2code_seed*/` |
| F1 funcional | ⏳ PENDING | Requiere `compute_metrics.py` |

---

## 14. Fases

| Fase | Datasets | Reglas | Configs | Objetivo |
|---|:-:|:-:|---|---|
| Pilot-20 | 20 (de 86) | 200 | B0,B1,B2,B3,B5,P | Primeros F1 reales, pipeline agéntico verificado |
| Pilot-86 | 86 | 500+ | Finalistas (successive halving) | Seleccionar configs para full-run |
| Full-run | 86+ | 1,000 | Finalistas + B_conf | Resultados definitivos para el paper |

---

## 15. Protocolo experimental completo

### Paso 1 — Preparar corpus de reglas (T3.6)

1. Usar los 86 datasets en `data/raw/` con sus schemas reales de columnas
2. Generar reglas con distribución 20%/40%/40% (40 fácil, 80 medio, 80 difícil)
3. Cada regla: `nl_text` + `ir_gold` verificada + `oracle` + ≥3 `test_cases`
4. Solo reglas REVIEWED entran al experimento
5. Verificar anti-leakage semántico entre splits (T3.10)

**Criterio:** `python scripts/audit_rules.py --target 200` reporta distribución correcta.

### Paso 2 — Ejecutar inferencia por configuración (T7.x + T9.1)

Para cada config (B0, B1, B2, B3, B4, B5, P, B_conf), para cada regla:

```
B0: regla_NL → [etapa 6 prompt directo] → check(df)
B1: regla_NL → [etapa 1→2→3→4] → IR → [etapa 6] → check(df)
B2: igual B1 + RAG estático del train split
B3: regla_NL → [etapa 6 con QLoRA adaptado] → check(df)
B4: regla_NL → [etapa 1→2→3→4 con QLoRA NL→IR] → IR → [etapa 6] → check(df)
B5: regla_NL → [etapas 1→2→3→4→5→6→7→8→9→10→11 completas] → VALIDATED/HR/ABSTAIN
P:  igual B5 + QLoRA NL→IR en etapa 1
B_conf: regla_NL → [pipeline Ollama 6 agentes] → VALIDATED/HR/ABSTAIN
```

Persistir en `predictions.parquet`: rule_id, dataset_id, config, generated_code, syntax_pass, latency_ms, pipeline_state, n_repair_attempts, trace_id.

**Garantías:**
- Código generado persistido ANTES de evaluarlo
- Todos los intentos del Repair Agent registrados (no solo el exitoso)
- ABSTAIN registrado explícitamente, no silenciado
- Cada predicción tiene trace_id y hash del código

### Paso 3 — Evaluar con oracle inyectado (T5.3)

Para cada regla × config:

```
1. CSV ← data/raw/{owner}/{slug}/vlatest/raw/*.csv
2. profile_natural_errors(df) → guardar separadamente (no contribuye a F1)
3. inject_errors(df, rule, n_inject=20, seed=42) → (df_modified, manifest)
4. check(df_modified) en sandbox aislado
5. compute_f1(predicted_indices, manifest.injected_row_indices, len(df))
6. Guardar: rule_id, config, f1, precision, recall, tp, fp, fn, manifest_hash
```

**Invariante:** mismo seed=42 para todos los configs → mismo oracle → comparaciones pareadas válidas.

### Paso 4 — Análisis estadístico (T11.x)

```
F1 macro por config → Bootstrap CI 95% agrupado por dataset (1,000 iter)
McNemar por par → Holm correction sobre 21+ pares
Modelos mixtos: F1 ~ config + (1|dataset) + (1|dimension)
Ablación T10.3: Δ F1 al retirar cada etapa de B5
```

### Paso 5 — Reportar

```
Tabla 1: F1 por config (B0→B_conf), CI, significancia
Tabla 2: F1 por complejidad (POINT_IN_TIME vs HISTORICAL vs ML_NECESSARY)
Tabla 3: F1 por dimensión (6 dimensiones)
Tabla 4: Ablación — Δ F1 por etapa retirada
Tabla 5: Errores lógicos — distribución de fallos por config
Tabla 6: Errores naturales — exploratorio
Figuras: precision-recall, radar por dimensión, evolución Dynamic RAG
```

---

## 16. Criterios de éxito, fracaso y abstención

### Para una regla individual

| Estado | Condición | En F1 |
|---|---|---|
| **VALIDATED** | Pasa todos los tests TDD + F1 ≥ umbral_val + consistente entre paráfrasis | Éxito |
| **HUMAN_REVIEW** | F1 < umbral_val, O inconsistente entre paráfrasis, O budget agotado (P11) | Fallo (F1=calculado) |
| **ABSTAIN** | Evidencia insuficiente, verdad vacua, ML sin datos | Excluido de F1; reportado como abstención |
| **FAILED** | Excepción, timeout, código malicioso | F1=0 para esa regla |

El umbral_val se determina en el split de validación (T9.4) y se congela antes del test.

### Para una configuración

| Métrica | Criterio de éxito |
|---|---|
| F1 macro | > F1 del config anterior en la tabla |
| Syntax pass | > 95% (prerequisito mínimo) |
| ABSTAIN rate correcto | > 80% (calidad del Evidence Locator) |
| Repair success | > 30% sobre las que fallaron inicialmente |

### Para el pipeline agéntico (B5/P) — condiciones de correctitud

1. **P7:** 0 reglas con blueprint incompleto llegan al generador
2. **P8:** 0 reglas procesadas con <3 tests TDD
3. **P9:** Cada rechazo AST nombra el patrón exacto (verificable en logs)
4. **P10:** 0 funciones con output incorrecto llegan al oracle
5. **P11:** 0 reglas con >3 intentos totales entre etapas 7-9
6. **Trazabilidad completa:** trace_id + estado máquina + hash código en cada predicción

### Para H1

**Se confirma:** ΔF1(P vs B5) ≥ 3 pp **Y** IC 95% no incluye 0 **Y** repair precision no cae > 1 pp.
**No se confirma:** ΔF1 < 3 pp **O** IC incluye 0. Ambos resultados son publicables.

---

## 17. Referencias

**Acquaviva et al. (2024).** *Translate-Infer-Compile.* arXiv:2402.06608. → Etapas 1, 3.

**Wang & Zhu (2024).** *Automatic Validation of LLM-Generated Code with Prompt Paraphrasing.* arXiv:2406.06864. ICSE-NIER 2026. → Etapa 11.

**Símola et al. (2026).** *LLM-Driven Compliance Checking.* Machine Learning, Springer. doi:10.1007/s10994-026-07038-6. → Etapas 1-4.

**Schafer et al. (2024b).** *Test-Driven Development for Code Generation.* arXiv:2402.13521. → Etapa 5.

**LLM4TDD (2023).** arXiv:2312.04687. → Etapa 5.

**VeriHarness (2025).** *Structured Feedback Improves Repair in an LLM Agent Loop.* arXiv:2607.14167. → Etapas 9, 10.

**Feedback benchmark (2024).** arXiv:2504.06939. → Etapa 10 (budget 3 óptimo).

**SandboxEval (2024).** arXiv:2504.00018. → Etapas 7, 8.

**Rashidi et al. (2025).** arXiv:2607.05743. → Etapa 8.

**DecoSearch (2025).** arXiv:2606.17821. → Etapa 4.

**PlanCompiler (2025).** arXiv:2604.13092. → Etapas 3, 4.

**HoloClean (2017).** *Holistic Data Repairs.* VLDB 2017. → Etapa 9.

**RAHA (2019).** *Configuration-Free Error Detection.* SIGMOD 2019. → Etapa 9.

**Conference paper propio (2024).** *calidad-datos-v4, notebook_v5.* → B_conf. 13/13 OK, 202s, +15.4 pp. P7-P13 establecidas.
