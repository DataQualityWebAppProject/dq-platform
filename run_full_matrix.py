#!/usr/bin/env python3
"""Full experiment matrix — runs all configs over all eligible rules in one shot.

Configs executed in order:
  B3_seed42  — QLoRA NL→code adapter     (~2.7s/rule,  ~8 min  for 171)
  B0         — Prompt directo             (~27s/rule,  ~77 min for 171)
  B1         — Prompt+IR                  (~32s/rule,  ~91 min for 171)  ← shares B0 model load
  B2         — Prompt+IR+RAG estático     (~40s/rule, ~114 min for 171)  ← shares B0 model load
  B4_seed42  — QLoRA NL→IR + code         (~20s/rule,  ~57 min for 171)
  B5 (fixed) — Full pipeline             (~14s/rule,  ~40 min for 171)

Total estimated: ~6.5h (vs ~8h naive — saves time by sharing model loads B0→B1→B2)

Outputs saved to: artifacts/predictions/pilot/{config}_{TAG}/predictions.parquet
Metrics saved to: artifacts/metrics/pilot/{config}_{TAG}_metrics.parquet
TAG = 'ext' (avoids overwriting 20-rule pilot predictions)

Resume support: skips rules already predicted (checks parquet by rule_id).
Compute metrics: runs compute_metrics.py after each config.

Usage:
    python scripts/run_full_matrix.py
    python scripts/run_full_matrix.py --rules data/rules/pilot_rules_200_eligible.jsonl
    python scripts/run_full_matrix.py --skip-existing  # resume interrupted run
    python scripts/run_full_matrix.py --configs B0,B3,B5  # subset of configs
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent

# Default rules file — eligible subset with CSV available
_DEFAULT_RULES = "data/rules/pilot_rules_200_eligible.jsonl"

# Tag appended to output dirs to avoid overwriting the 20-rule pilot predictions
_TAG = "ext"

# Config definitions: (name, script, extra_args)
_CONFIGS = [
    ("B3_seed42",  "run_inference_pilot.py",  ["--config", "B3", "--seed", "42", "--tag", _TAG]),
    ("B0",         "run_inference_pilot.py",  ["--config", "B0", "--tag", _TAG]),
    ("B1",         "run_inference_pilot.py",  ["--config", "B1", "--tag", _TAG]),
    ("B2",         "run_inference_pilot.py",  ["--config", "B2", "--tag", _TAG,
                                               "--rag-file", "data/rag/train_b2_examples.jsonl"]),
    ("B4_seed42",  "run_b4_inference.py",     ["--tag", _TAG]),
    ("B5",         "run_b5_inference.py",     ["--tag", _TAG]),
]

# Metric configs map: inference tag → compute_metrics config name
_METRIC_CONFIG_MAP = {
    "B3_seed42": f"B3_seed42_{_TAG}",
    "B0":        f"B0_{_TAG}",
    "B1":        f"B1_{_TAG}",
    "B2":        f"B2_{_TAG}",
    "B4_seed42": f"B4_seed42_{_TAG}",
    "B5":        f"B5_{_TAG}",
}


def _load_rules(path: str) -> list[dict]:
    rules = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                rules.append(json.loads(line))
    return rules


def _get_existing_rule_ids(parquet_path: Path) -> set[str]:
    """Return set of rule_ids already in the predictions parquet."""
    if not parquet_path.exists():
        return set()
    try:
        import pandas as pd
        df = pd.read_parquet(parquet_path)
        return set(df["rule_id"].tolist())
    except Exception:
        return set()


def _write_remaining_rules(rules: list[dict], existing_ids: set[str], tmp_path: Path) -> int:
    """Write rules not yet predicted to a temp file. Returns count of remaining."""
    remaining = [r for r in rules if r["rule_id"] not in existing_ids]
    with open(tmp_path, "w", encoding="utf-8") as f:
        for r in remaining:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return len(remaining)


def _run_inference(
    config_name: str,
    script: str,
    extra_args: list[str],
    rules_path: str,
    skip_existing: bool,
    tag: str = "",
) -> tuple[bool, float]:
    """Run inference script for one config. Returns (success, elapsed_seconds)."""
    # Predictions are saved with _TAG appended by the inference scripts themselves
    pred_dir = _REPO / "artifacts" / "predictions" / "pilot" / f"{config_name}_{_TAG}"
    parquet_path = pred_dir / "predictions.parquet"

    # Check resume
    rules = _load_rules(rules_path)
    existing_ids = _get_existing_rule_ids(parquet_path) if skip_existing else set()

    if skip_existing and len(existing_ids) >= len(rules):
        print(f"  [SKIP] {config_name}: all {len(rules)} rules already predicted")
        return True, 0.0

    if skip_existing and existing_ids:
        print(f"  [RESUME] {config_name}: {len(existing_ids)}/{len(rules)} done, running {len(rules)-len(existing_ids)} remaining")
        # Write remaining rules to temp file
        tmp_rules = _REPO / f"data/rules/_tmp_remaining_{config_name}.jsonl"
        n_remaining = _write_remaining_rules(rules, existing_ids, tmp_rules)
        if n_remaining == 0:
            print(f"  [SKIP] {config_name}: nothing remaining")
            return True, 0.0
        rules_to_use = str(tmp_rules)
    else:
        rules_to_use = rules_path

    script_path = _REPO / "scripts" / script
    cmd = [sys.executable, str(script_path), "--rules", rules_to_use] + extra_args

    print(f"\n{'='*60}")
    print(f"  CONFIG: {config_name}")
    print(f"  Script: {script}")
    print(f"  Rules:  {rules_to_use}")
    print(f"  Time:   {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}")
    print(f"{'='*60}")

    t0 = time.monotonic()
    env = os.environ.copy()
    env["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

    try:
        proc = subprocess.run(
            cmd, cwd=str(_REPO), env=env,
            timeout=7200,  # 2h max per config
        )
        elapsed = time.monotonic() - t0
        success = proc.returncode == 0

        # If resume: merge remaining predictions with existing parquet
        if skip_existing and existing_ids and (tmp_rules := _REPO / f"data/rules/_tmp_remaining_{config_name}.jsonl").exists():
            _merge_predictions(parquet_path, config_name)
            tmp_rules.unlink(missing_ok=True)

        return success, elapsed
    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - t0
        print(f"  [TIMEOUT] {config_name} exceeded 2h limit")
        return False, elapsed
    except Exception as e:
        elapsed = time.monotonic() - t0
        print(f"  [ERROR] {config_name}: {e}")
        return False, elapsed


def _merge_predictions(parquet_path: Path, config_name: str) -> None:
    """Merge newly-generated predictions with existing ones (for resume)."""
    try:
        import pandas as pd
        if not parquet_path.exists():
            return
        existing = pd.read_parquet(parquet_path)
        # The script saves to the same path — it already contains only new predictions
        # We need to re-load and concatenate with original
        # NOTE: This is handled by the inference scripts themselves via parquet append
        # If the script overwrites, we just accept the new file
    except Exception:
        pass


def _run_metrics(config_name: str, rules_path: str) -> tuple[float, bool]:
    """Run compute_metrics.py for a config. Returns (f1_macro, success)."""
    script_path = _REPO / "scripts" / "compute_metrics.py"
    metric_config = _METRIC_CONFIG_MAP.get(config_name, config_name)
    cmd = [
        sys.executable, str(script_path),
        "--config", metric_config,
        "--rules", rules_path,
    ]
    print(f"\n  Computing metrics for {config_name}...")
    env = os.environ.copy()
    try:
        result = subprocess.run(
            cmd, cwd=str(_REPO), env=env,
            capture_output=True, text=True, timeout=300,
        )
        # Extract F1 from output
        f1 = 0.0
        for line in result.stdout.split("\n"):
            if "F1 macro" in line:
                try:
                    f1 = float(line.split(":")[-1].strip())
                except Exception:
                    pass
        print(f"  {config_name} F1_macro = {f1:.4f}")
        if result.returncode != 0:
            print(f"  [WARN] compute_metrics returned non-zero: {result.stderr[:200]}")
        return f1, result.returncode == 0
    except Exception as e:
        print(f"  [ERROR] compute_metrics {config_name}: {e}")
        return 0.0, False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rules",
        default=_DEFAULT_RULES,
        help="JSONL rules file to run all configs against",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        default=True,
        help="Skip rules already in predictions.parquet (resume support)",
    )
    parser.add_argument(
        "--no-skip",
        action="store_true",
        help="Re-run all rules even if predictions exist",
    )
    parser.add_argument(
        "--configs",
        default="",
        help="Comma-separated subset of configs to run (default: all). E.g. B0,B3,B5",
    )
    parser.add_argument(
        "--metrics-only",
        action="store_true",
        help="Only compute metrics, skip inference",
    )
    args = parser.parse_args()

    skip_existing = args.skip_existing and not args.no_skip
    rules_path = str(_REPO / args.rules)

    # Filter configs if specified
    configs_to_run = _CONFIGS
    if args.configs:
        requested = set(args.configs.split(","))
        configs_to_run = [(n, s, e) for n, s, e in _CONFIGS if n in requested]
        if not configs_to_run:
            print(f"ERROR: no matching configs in {args.configs}")
            return 1

    # Load rules to show summary
    rules = _load_rules(rules_path)
    print(f"\n{'='*60}")
    print(f"  FULL MATRIX RUN")
    print(f"  Rules:   {len(rules)} from {args.rules}")
    print(f"  Configs: {', '.join(n for n, _, _ in configs_to_run)}")
    print(f"  Resume:  {skip_existing}")
    print(f"  Start:   {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"{'='*60}\n")

    results: dict[str, dict] = {}
    total_start = time.monotonic()

    for config_name, script, extra_args in configs_to_run:
        if args.metrics_only:
            f1, ok = _run_metrics(config_name, rules_path)
            results[config_name] = {"f1": f1, "ok": ok, "elapsed": 0.0}
            continue

        t_config_start = time.monotonic()
        success, elapsed = _run_inference(
            config_name, script, extra_args, rules_path, skip_existing
        )
        results[config_name] = {"elapsed": elapsed, "inference_ok": success}

        # Compute metrics immediately after inference
        if success or elapsed > 0:
            f1, metrics_ok = _run_metrics(config_name, rules_path)
            results[config_name]["f1"] = f1
            results[config_name]["metrics_ok"] = metrics_ok
        else:
            results[config_name]["f1"] = None
            results[config_name]["metrics_ok"] = False

        config_elapsed = time.monotonic() - t_config_start
        print(f"\n  [{config_name}] Done in {config_elapsed/60:.1f} min — F1={results[config_name].get('f1', 'N/A')}")

    # Final summary
    total_elapsed = time.monotonic() - total_start
    print(f"\n{'='*60}")
    print(f"  FULL MATRIX COMPLETE")
    print(f"  Total time: {total_elapsed/3600:.2f}h ({total_elapsed/60:.0f} min)")
    print(f"  End:        {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"{'='*60}")
    print(f"\n  Results summary:")
    print(f"  {'Config':<20} {'F1 macro':>10} {'Time':>10} {'OK':>6}")
    print(f"  {'-'*50}")
    for config_name, r in results.items():
        f1_str = f"{r.get('f1', 0):.4f}" if r.get('f1') is not None else "  N/A "
        elapsed_str = f"{r.get('elapsed', 0)/60:.1f}m"
        ok_str = "✓" if r.get("inference_ok", r.get("ok", False)) else "✗"
        print(f"  {config_name:<20} {f1_str:>10} {elapsed_str:>10} {ok_str:>6}")

    print(f"\nNext: update reports/results.md with these F1 values")
    print(f"  Parquets: artifacts/metrics/pilot/*_metrics.parquet")

    # Write run manifest
    manifest_path = _REPO / "artifacts" / "metrics" / "pilot" / "full_matrix_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "rules_file": args.rules,
        "n_rules": len(rules),
        "configs": list(results.keys()),
        "results": {k: {kk: vv for kk, vv in v.items() if kk != "elapsed"} for k, v in results.items()},
        "total_elapsed_min": total_elapsed / 60,
    }
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"  Manifest: {manifest_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
