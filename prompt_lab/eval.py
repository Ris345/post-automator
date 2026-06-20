#!/usr/bin/env python3
"""Evaluate a prompt version by generating N samples and scoring each.

Usage:
  OPENAI_API_KEY=sk-... python prompt_lab/eval.py --version v1 --n 10
  python prompt_lab/eval.py --version v1 --n 5 --no-llm-judge
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROMPT_LAB = Path(__file__).parent
sys.path.insert(0, str(PROMPT_LAB))

from dotenv import load_dotenv
load_dotenv(PROMPT_LAB.parent / ".env")

from core.runner import generate_samples
from core.scorer import score_output, run_rule_checks
from core.history import append_run, save_run_detail

PROMPTS_DIR = PROMPT_LAB / "prompts"
LAMBDA_DIR = PROMPT_LAB.parent / "lambda"


def load_prompt_version(version: str) -> tuple[str, str]:
    system_file = PROMPTS_DIR / f"system_{version}.txt"
    user_file = PROMPTS_DIR / f"user_{version}.txt"
    if system_file.exists() and user_file.exists():
        return system_file.read_text().strip(), user_file.read_text().strip()
    if version == "v1":
        sys.path.insert(0, str(LAMBDA_DIR))
        from prompt import SYSTEM_PROMPT, USER_PROMPT
        return SYSTEM_PROMPT, USER_PROMPT
    raise FileNotFoundError(f"Prompt version '{version}' not found in {PROMPTS_DIR}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default="v1", help="Prompt version to evaluate (default: v1)")
    parser.add_argument("--n", type=int, default=10, help="Number of samples (default: 10)")
    parser.add_argument("--no-llm-judge", action="store_true", help="Skip LLM judge (rule checks only, faster)")
    args = parser.parse_args()

    openai_key = os.environ.get("OPENAI_API_KEY")
    if not openai_key:
        print("Error: OPENAI_API_KEY not set")
        sys.exit(1)

    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if not args.no_llm_judge and not anthropic_key:
        print("Error: ANTHROPIC_API_KEY not set (use --no-llm-judge to skip)")
        sys.exit(1)

    system_prompt, user_prompt = load_prompt_version(args.version)
    print(f"Evaluating '{args.version}' — {args.n} samples", "  [rule-only]" if args.no_llm_judge else "")
    print("-" * 70)

    samples_raw = generate_samples(system_prompt, user_prompt, openai_key, args.n)

    scored_outputs = []
    for raw in samples_raw:
        if args.no_llm_judge:
            rule_result = run_rule_checks(raw["text"])
            scored = {
                "text": raw["text"],
                "latency_ms": raw["latency_ms"],
                "rule_checks": rule_result,
                "rule_score": rule_result["rule_score"],
                "llm_score": None,
                "final_score": rule_result["rule_score"],
                "hard_fail": rule_result["has_hard_fail"],
            }
        else:
            scored = score_output(raw["text"], anthropic_key)
            scored["latency_ms"] = raw["latency_ms"]

        status = "✗ HARD" if scored["hard_fail"] else ("✓" if scored["final_score"] >= 65 else "~")
        violations = scored["rule_checks"]["violations"]
        viol_str = f"  [{', '.join(violations[:3])}]" if violations else ""
        print(f"  [{raw['index']+1:>2}/{args.n}] {status} {scored['final_score']:>5.1f} | {raw['text'][:65]}...{viol_str}")
        scored_outputs.append(scored)

    n = len(scored_outputs)
    avg_rule = round(sum(s["rule_score"] for s in scored_outputs) / n, 1)
    avg_llm = round(sum(s["llm_score"] or 0 for s in scored_outputs) / n, 1) if not args.no_llm_judge else None
    avg_final = round(sum(s["final_score"] for s in scored_outputs) / n, 1)
    pass_rate = round(sum(1 for s in scored_outputs if s["final_score"] >= 65) / n * 100)
    hard_fail_count = sum(1 for s in scored_outputs if s["hard_fail"])

    violation_counts: dict[str, int] = {}
    for s in scored_outputs:
        for v in s["rule_checks"]["violations"]:
            violation_counts[v] = violation_counts.get(v, 0) + 1

    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_data = {
        "meta": {
            "version": args.version,
            "run_id": run_id,
            "n": n,
            "model": "gpt-4o-mini",
            "temperature": 0.85,
            "max_tokens": 300,
            "llm_judge": not args.no_llm_judge,
        },
        "outputs": scored_outputs,
        "aggregate": {
            "avg_rule_score": avg_rule,
            "avg_llm_score": avg_llm,
            "avg_final_score": avg_final,
            "pass_rate_pct": pass_rate,
            "hard_fail_count": hard_fail_count,
            "violation_counts": violation_counts,
        },
    }

    fname = save_run_detail(run_data)
    append_run({
        "version": args.version,
        "run_id": run_id,
        "n": n,
        "avg_rule_score": avg_rule,
        "avg_llm_score": avg_llm,
        "avg_final_score": avg_final,
        "pass_rate_pct": pass_rate,
        "hard_fail_count": hard_fail_count,
        "violation_counts": violation_counts,
        "run_file": fname,
    })

    print()
    print("=" * 70)
    print(f"Version:       {args.version}")
    print(f"Rule score:    {avg_rule}/100")
    if avg_llm is not None:
        print(f"LLM score:     {avg_llm}/100")
    print(f"Final score:   {avg_final}/100  (pass threshold: 65)")
    print(f"Pass rate:     {pass_rate}%")
    print(f"Hard fails:    {hard_fail_count}/{n}")
    if violation_counts:
        top = sorted(violation_counts.items(), key=lambda x: -x[1])[:5]
        print(f"Top violations: {', '.join(f'{k}({v})' for k, v in top)}")
    print(f"Saved:         prompt_lab/results/{fname}")


if __name__ == "__main__":
    main()
