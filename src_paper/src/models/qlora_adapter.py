"""QLoRA adapter base class for NL→code and NL→IR adapters.

Supports stub_mode for testing without GPU. Real mode requires
HF_TOKEN env var and GPU with NF4 quantization support (bitsandbytes).
"""
from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path
from typing import Any

import yaml

from models.qwen_adapter import GenerationConfig, GenerationResult


class QLoRAAdapter:
    """Base QLoRA adapter. Subclassed for NL→code (B3) and NL→IR (B4/P)."""

    def __init__(
        self,
        config_path: str,
        adapter_weights_path: str | None = None,
        stub_mode: bool = False,
    ) -> None:
        self._config_path = config_path
        self._adapter_weights_path = adapter_weights_path
        self._stub_mode = stub_mode
        self._model = None
        self._tokenizer = None
        self._config = self._load_config()

        if not stub_mode and adapter_weights_path:
            self._load_adapter()

    def _load_config(self) -> dict[str, Any]:
        """Load and validate the YAML config."""
        path = Path(self._config_path)
        if not path.exists():
            raise FileNotFoundError(f"QLoRA config not found: {path}")
        with path.open() as f:
            cfg = yaml.safe_load(f)
        # Validate required fields
        if not cfg.get("base_model"):
            raise ValueError("QLoRA config must specify base_model.")
        return cfg

    def _load_adapter(self) -> None:
        """Load model + LoRA adapter weights."""
        token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_HUB_TOKEN")
        if not token:
            raise RuntimeError(
                "HF_TOKEN environment variable is not set. "
                "Required for loading gated models."
            )
        try:
            import torch
            from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
            from peft import PeftModel

            bnb_cfg = self._config.get("quantization", {})
            quant_config = BitsAndBytesConfig(
                load_in_4bit=bnb_cfg.get("load_in_4bit", True),
                bnb_4bit_quant_type=bnb_cfg.get("bnb_4bit_quant_type", "nf4"),
                bnb_4bit_compute_dtype=getattr(torch, bnb_cfg.get("bnb_4bit_compute_dtype", "bfloat16")),
                bnb_4bit_use_double_quant=bnb_cfg.get("bnb_4bit_use_double_quant", True),
            )
            base_model_id = self._config["base_model"]
            self._tokenizer = AutoTokenizer.from_pretrained(base_model_id, token=token)
            base = AutoModelForCausalLM.from_pretrained(
                base_model_id, quantization_config=quant_config,
                device_map="auto", token=token,
            )
            self._model = PeftModel.from_pretrained(base, self._adapter_weights_path)
        except ImportError as exc:
            raise ImportError(
                "torch, transformers, peft, bitsandbytes required. "
                "Install: pip install -e '.[ml]'"
            ) from exc

    def generate(self, prompt: str, config: GenerationConfig | None = None) -> GenerationResult:
        cfg = config or GenerationConfig()
        prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()
        start = time.monotonic()

        if self._stub_mode:
            fake = f"[QLORA-STUB] {prompt_hash[:8]}"
            return GenerationResult(
                generated_text=fake, prompt_hash=prompt_hash,
                model_id=self._config.get("base_model", "unknown"),
                adapter_id=self._adapter_weights_path or "no-adapter",
                input_tokens=len(prompt.split()), output_tokens=len(fake.split()),
                elapsed_ms=(time.monotonic() - start) * 1000,
                temperature=cfg.temperature, seed=cfg.seed,
                hardware="stub", peak_memory_mb=None,
            )

        import torch
        if cfg.seed is not None:
            torch.manual_seed(cfg.seed)
        inputs = self._tokenizer(prompt, return_tensors="pt").to(self._model.device)
        with torch.no_grad():
            out = self._model.generate(
                **inputs, max_new_tokens=cfg.max_new_tokens,
                do_sample=cfg.do_sample, pad_token_id=self._tokenizer.eos_token_id,
            )
        generated = self._tokenizer.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
        return GenerationResult(
            generated_text=generated, prompt_hash=prompt_hash,
            model_id=self._config.get("base_model", "unknown"),
            adapter_id=self._adapter_weights_path,
            input_tokens=inputs["input_ids"].shape[1],
            output_tokens=len(out[0]) - inputs["input_ids"].shape[1],
            elapsed_ms=(time.monotonic() - start) * 1000,
            temperature=cfg.temperature, seed=cfg.seed,
            hardware="cuda" if torch.cuda.is_available() else "cpu",
            peak_memory_mb=torch.cuda.max_memory_allocated() / 1024**2 if torch.cuda.is_available() else None,
        )
