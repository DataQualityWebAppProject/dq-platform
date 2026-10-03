"""Structured prompt adapter for Qwen2.5-7B-Instruct (Baseline B1).

Per Simbola et al. 2026: structured prompts with explicit sections
(canonicalize → scope → evidence → evaluate → decide → output)
outperform direct prompting by ~4 pp F1.

This adapter wraps QwenBaseAdapter with a structured prompt template.
"""
from __future__ import annotations

from models.qwen_adapter import QwenBaseAdapter, GenerationConfig, GenerationResult
from models.ir import IR


_STRUCTURED_TEMPLATE = """You are a data quality rule evaluator.

## Task
Evaluate whether the following data quality rule is satisfied for the given dataset row.

## Rule (Canonicalized)
- Rule ID: {rule_id}
- Dimension: {dimension}
- Complexity: {complexity}
- Scope: columns {columns}
- Logic: {operator}
- Natural language: {nl_text}

## Dataset Schema
Columns available: {schema_columns}

## Row Data
{row_data}

## Instructions
1. Identify which columns are in scope.
2. Locate the relevant evidence in the row.
3. Apply the logical condition.
4. Determine if the row violates the rule.
5. Output a JSON object with:
   - "violation": true/false
   - "reason": one sentence explanation
   - "confidence": 0.0-1.0

## Output (JSON only, no preamble):
"""


class StructuredPromptAdapter:
    """Qwen adapter with structured 7-stage prompt (Baseline B1).

    Uses QwenBaseAdapter internally. The structured template follows
    the 7 stages from Simbola et al. 2026.
    """

    def __init__(
        self,
        stub_mode: bool = False,
        config: GenerationConfig | None = None,
    ) -> None:
        self._base = QwenBaseAdapter(stub_mode=stub_mode, config=config)
        self._stub_mode = stub_mode

    def generate_for_rule(
        self,
        ir: IR,
        nl_text: str,
        schema_columns: list[str],
        row_data: dict,
        config: GenerationConfig | None = None,
    ) -> GenerationResult:
        """Generate evaluation result using structured prompt.

        Parameters
        ----------
        ir:
            The IR for the rule being evaluated.
        nl_text:
            Natural language description of the rule.
        schema_columns:
            Available column names in the dataset.
        row_data:
            Dict representing a single row to evaluate.
        """
        import json
        prompt = _STRUCTURED_TEMPLATE.format(
            rule_id=ir.rule_id,
            dimension=ir.dimension,
            complexity=ir.complexity,
            columns=", ".join(ir.scope.columns) or "all columns",
            operator=ir.logic.operator,
            nl_text=nl_text,
            schema_columns=", ".join(schema_columns),
            row_data=json.dumps(row_data, ensure_ascii=False),
        )
        return self._base.generate(prompt, config=config)
