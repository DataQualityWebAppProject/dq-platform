"""RAG adapter for Qwen2.5-7B-Instruct (Baseline B2).

Design rule (R5, R12): The RAG index must ONLY contain training split examples.
Validation and test examples must NEVER enter the index.

Index audit: before any inference, verify that no test/validation examples
are present in the index. This is a hard gate.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from models.qwen_adapter import QwenBaseAdapter, GenerationConfig, GenerationResult
from models.ir import IR


@dataclass
class RAGExample:
    """A single few-shot example in the RAG index."""
    rule_id: str
    nl_text: str
    split: str  # "train" only — validation/test must never be indexed
    example_output: str


class RAGIndexLeakageError(RuntimeError):
    """Raised when validation or test examples are found in the RAG index."""


@dataclass
class RAGIndex:
    """Simple in-memory RAG index with leakage audit."""
    examples: list[RAGExample] = field(default_factory=list)

    def add(self, example: RAGExample) -> None:
        """Add a training example to the index."""
        if example.split != "train":
            raise RAGIndexLeakageError(
                f"Cannot add example from split='{example.split}' to RAG index. "
                "Only 'train' split examples are permitted (R5, R12)."
            )
        self.examples.append(example)

    def audit(self) -> list[str]:
        """Audit the index for leakage. Returns list of violation messages."""
        violations = []
        for i, ex in enumerate(self.examples):
            if ex.split != "train":
                violations.append(
                    f"Index entry {i} (rule_id={ex.rule_id}) has split='{ex.split}'. "
                    "Only 'train' is allowed."
                )
        return violations

    def retrieve(self, query: str, top_k: int = 3) -> list[RAGExample]:
        """Retrieve top_k examples by simple keyword overlap."""
        query_tokens = set(query.lower().split())
        scored = []
        for ex in self.examples:
            ex_tokens = set(ex.nl_text.lower().split())
            overlap = len(query_tokens & ex_tokens)
            scored.append((overlap, ex))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [ex for _, ex in scored[:top_k]]


class RAGAdapter:
    """Qwen adapter with RAG few-shot examples (Baseline B2).

    Only training-split examples can be in the index.
    """

    def __init__(
        self,
        index: RAGIndex | None = None,
        stub_mode: bool = False,
        config: GenerationConfig | None = None,
    ) -> None:
        self._base = QwenBaseAdapter(stub_mode=stub_mode, config=config)
        self._index = index or RAGIndex()
        self._stub_mode = stub_mode

        # Gate: audit index before use
        violations = self._index.audit()
        if violations:
            raise RAGIndexLeakageError(
                f"RAG index failed audit: {violations}"
            )

    def generate_for_rule(
        self,
        ir: IR,
        nl_text: str,
        schema_columns: list[str],
        row_data: dict,
        config: GenerationConfig | None = None,
    ) -> GenerationResult:
        """Generate with few-shot RAG examples prepended."""
        import json
        examples = self._index.retrieve(nl_text, top_k=3)
        few_shot = ""
        for ex in examples:
            few_shot += f"Example rule: {ex.nl_text}\nExpected output: {ex.example_output}\n\n"

        prompt = (
            f"{few_shot}"
            f"Rule: {nl_text}\n"
            f"Dimension: {ir.dimension}, Scope: {', '.join(ir.scope.columns)}\n"
            f"Row data: {json.dumps(row_data)}\n"
            "Evaluate: does this row violate the rule? Output JSON: "
        )
        return self._base.generate(prompt, config=config)
