"""Qwen2.5-7B-Instruct base adapter with direct prompt (Baseline B0).

Per ADR-005: HuggingFace Transformers + PEFT + bitsandbytes NF4.
Credentials read from HF_TOKEN env var only — never hardcoded.
Deterministic inference: temperature=0 or fixed seed.

This module requires the [ml] extras: pip install -e ".[ml]"
Unit tests use a stub mode (no GPU/model required).
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from typing import Any


@dataclass
class GenerationConfig:
    """Configuration for a single generation call."""
    max_new_tokens: int = 384
    temperature: float = 0.0       # 0.0 = greedy (deterministic)
    do_sample: bool = False         # False when temperature=0
    seed: int | None = 42


@dataclass
class GenerationResult:
    """Result of a single generation call."""
    generated_text: str
    prompt_hash: str           # SHA-256 of the full prompt
    model_id: str
    adapter_id: str | None
    input_tokens: int
    output_tokens: int
    elapsed_ms: float
    temperature: float
    seed: int | None
    hardware: str
    peak_memory_mb: float | None


class QwenBaseAdapter:
    """Qwen2.5-7B-Instruct base adapter for direct prompting (B0).

    Supports two modes:
    - stub_mode=True: returns deterministic fake output for testing
    - stub_mode=False: loads the actual HF model (requires GPU + HF_TOKEN)

    Credentials:
    - HF_TOKEN must be set as environment variable before construction
    - Never log or print the token value
    """

    MODEL_ID = "Qwen/Qwen2.5-7B-Instruct"

    def __init__(
        self,
        stub_mode: bool = False,
        config: GenerationConfig | None = None,
    ) -> None:
        self._stub_mode = stub_mode
        self._config = config or GenerationConfig()
        self._model = None
        self._tokenizer = None
        self._hardware = "cpu"

        if not stub_mode:
            self._load_model()

    def _load_model(self) -> None:
        """Load model and tokenizer. Raises if HF_TOKEN not set."""
        token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_HUB_TOKEN")
        if not token:
            raise RuntimeError(
                "HF_TOKEN environment variable is not set. "
                "Set it before loading the model. Never hardcode credentials."
            )
        try:
            import torch
            from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
            self._tokenizer = AutoTokenizer.from_pretrained(
                self.MODEL_ID, token=token, trust_remote_code=False
            )
            # NF4 4-bit quantization — same as B3/B4/B5 scripts.
            # Reduces VRAM from ~14GB (bfloat16) to ~5GB, keeping model on GPU.
            bnb_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=torch.bfloat16,
                bnb_4bit_use_double_quant=True,
            )
            self._model = AutoModelForCausalLM.from_pretrained(
                self.MODEL_ID, token=token, device_map="auto",
                quantization_config=bnb_config, trust_remote_code=False,
            )
            self._hardware = "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError as exc:
            raise ImportError(
                "torch, transformers, and bitsandbytes are required for full model loading. "
                "Install with: pip install -e '.[ml]'"
            ) from exc

    def generate(
        self,
        prompt: str,
        config: GenerationConfig | None = None,
    ) -> GenerationResult:
        """Generate text from a prompt.

        Parameters
        ----------
        prompt:
            Full prompt string.
        config:
            Override generation config for this call.
        """
        cfg = config or self._config
        prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        start = time.monotonic()

        if self._stub_mode:
            # Deterministic stub for testing
            fake_text = f"[STUB] Generated for prompt hash {prompt_hash[:8]}"
            elapsed = (time.monotonic() - start) * 1000
            return GenerationResult(
                generated_text=fake_text,
                prompt_hash=prompt_hash,
                model_id=self.MODEL_ID,
                adapter_id=None,
                input_tokens=len(prompt.split()),
                output_tokens=len(fake_text.split()),
                elapsed_ms=elapsed,
                temperature=cfg.temperature,
                seed=cfg.seed,
                hardware="stub",
                peak_memory_mb=None,
            )

        # Real inference
        import torch
        if cfg.seed is not None:
            torch.manual_seed(cfg.seed)

        inputs = self._tokenizer(prompt, return_tensors="pt").to(self._model.device)
        input_tokens = inputs["input_ids"].shape[1]

        with torch.no_grad():
            output = self._model.generate(
                **inputs,
                max_new_tokens=cfg.max_new_tokens,
                temperature=cfg.temperature if cfg.temperature > 0 else None,
                do_sample=cfg.do_sample,
                pad_token_id=self._tokenizer.eos_token_id,
            )

        generated_ids = output[0][input_tokens:]
        generated_text = self._tokenizer.decode(generated_ids, skip_special_tokens=True)
        elapsed = (time.monotonic() - start) * 1000

        peak_mem = None
        if torch.cuda.is_available():
            peak_mem = torch.cuda.max_memory_allocated() / (1024 ** 2)

        return GenerationResult(
            generated_text=generated_text,
            prompt_hash=prompt_hash,
            model_id=self.MODEL_ID,
            adapter_id=None,
            input_tokens=input_tokens,
            output_tokens=len(generated_ids),
            elapsed_ms=elapsed,
            temperature=cfg.temperature,
            seed=cfg.seed,
            hardware=self._hardware,
            peak_memory_mb=peak_mem,
        )
