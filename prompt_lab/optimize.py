#!/usr/bin/env python3
"""Automated prompt optimization via hill climbing.

generate → eval (rule-only) → if improved: LLM judge → keep best → repeat

Two-phase scoring keeps costs low: LLM judge only runs when rule score improves.

Usage:
  python prompt_lab/optimize.py --base v1 --max-iters 5
  python prompt_lab/optimize.py --base v1 --max-iters 5 --n 5 --target 85
  python prompt_lab/optimize.py --base v1 --max-iters 3 --rules-only  (free run)
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
from core.scorer import run_rule_checks, run_llm_judge, score_output
from core.history import append_run, save_run_detail, get_runs_for_version

PROMPTS_DIR = PROMPT_LAB / "prompts"
LAMBDA_DIR = PROMPT_LAB.parent / "lambda"
OPT_LOG_FILE = PROMPT_LAB / "results" / "optimize_log.json"


def load_prompt(version: str) -> tuple[str, str]:
    sf = PROMPTS_DIR / f"system_{version}.txt"
    uf = PROMPTS_DIR / f"user_{version}.txt"
    if sf.exists() and uf.exists():
        return sf.read_text().strip(), uf.read_text().strip()
    if version in ("v1", "v2"):
        sys.path.insert(0, str(LAMBDA_DIR))
        from prompt import SYSTEM_PROMPT, USER_PROMPT
        return SYSTEM_PROMPT, USER_PROMPT
    raise FileNotFoundError(f"Version '{version}' not found")


def save_prompt(version: str, system: str, user: str):
    PROMPTS_DIR.mkdir(exist_ok=True)
    (PROMPTS_DIR / f"system_{version}.txt").write_text(system)
    (PROMPTS_DIR / f"user_{version}.txt").write_text(user)


def generate_candidate(base_version: str, out_version: str, weakness_context: str, api_key: str) -> tuple[str, str]:
    from openai import OpenAI
    base_system, base_user = load_prompt(base_version)

    meta_system = """You are an expert prompt engineer. Improve the given prompt to fix the specific weaknesses listed.
Return ONLY the improved prompts in this exact format — no explanation:

SYSTEM_PROMPT:
<text>

USER_PROMPT:
<text>"""

    meta_user = f"""{weakness_context}

Current system prompt:
---
{base_system}
---

Current user prompt:
---
{base_user}
---

Critical requirements:
- Keep all good/bad examples in USER_PROMPT — they are essential
- Keep the persona (Rishav, infrastructure engineer)
- Keep the topic weighting list
- Harden the rule that causes most violations
- Every good example must end with a specific detail, number, or named service"""

    client = OpenAI(api_key=api_key)
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": meta_system},
            {"role": "user", "content": meta_user},
        ],
        max_tokens=1200,
        temperature=0.7,
    )

    text = resp.choices[0].message.content
    if "SYSTEM_PROMPT:" not in text or "USER_PROMPT:" not in text:
        raise ValueError(f"Bad generator response:\n{text[:300]}")

    after = text.split("SYSTEM_PROMPT:", 1)[1]
    parts = after.split("USER_PROMPT:", 1)
    new_system = parts[0].strip().strip("---").strip()
    new_user = parts[1].strip().strip("---").strip()
    return new_system, new_user


def eval_version(version: str, n: int, api_key: str, rules_only: bool) -> dict:
    system, user = load_prompt(version)
    samples = generate_samples(system, user, api_key, n)

    scored = []
    for s in samples:
        rule = run_rule_checks(s["text"])
        if rules_only:
            entry = {
                "text": s["text"],
                "rule_checks": rule,
                "rule_score": rule["rule_score"],
                "llm_score": None,
                "final_score": rule["rule_score"],
                "hard_fail": rule["has_hard_fail"],
            }
        else:
            llm = run_llm_judge(s["text"], api_key)
            entry = {
                "text": s["text"],
                "rule_checks": rule,
                "llm_judge": llm,
                "rule_score": rule["rule_score"],
                "llm_score": llm["llm_score"],
                "final_score": round(0.4 * rule["rule_score"] + 0.6 * llm["llm_score"], 1),
                "hard_fail": rule["has_hard_fail"],
            }
        scored.append(entry)

    n_samples = len(scored)
    avg_rule = round(sum(s["rule_score"] for s in scored) / n_samples, 1)
    avg_llm = round(sum(s["llm_score"] or 0 for s in scored) / n_samples, 1) if not rules_only else None
    avg_final = round(sum(s["final_score"] for s in scored) / n_samples, 1)
    pass_rate = round(sum(1 for s in scored if s["final_score"] >= 65) / n_samples * 100)
    hard_fails = sum(1 for s in scored if s["hard_fail"])

    vc: dict[str, int] = {}
    for s in scored:
        for v in s["rule_checks"]["violations"]:
            vc[v] = vc.get(v, 0) + 1

    return {
        "version": version,
        "avg_rule": avg_rule,
        "avg_llm": avg_llm,
        "avg_final": avg_final,
        "pass_rate": pass_rate,
        "hard_fails": hard_fails,
        "violation_counts": vc,
        "outputs": scored,
    }


def build_weakness_context(result: dict) -> str:
    lines = [f"Weaknesses to fix in version '{result['version']}':"]
    vc = result["violation_counts"]
    if vc:
        top = sorted(vc.items(), key=lambda x: -x[1])[:4]
        lines.append("Most frequent violations:")
        for rule, count in top:
            lines.append(f"  - {rule}: {count} time(s)")
    if result["avg_llm"] and result["avg_llm"] < 70:
        lines.append(f"LLM quality score is low ({result['avg_llm']}/100) — posts sound generic or lack specificity")
    return "\n".join(lines)


def estimate_calls(n: int, max_iters: int, rules_only: bool) -> int:
    # base eval + per-iter: 1 generator call + n generation + n judge (if not rules_only)
    base = n + (0 if rules_only else n)
    per_iter = 1 + n + (0 if rules_only else n)  # generator + generation + optional judge
    return base + per_iter * max_iters


def log_run(log: list[dict]):
    OPT_LOG_FILE.parent.mkdir(exist_ok=True)
    OPT_LOG_FILE.write_text(json.dumps({"runs": log}, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="v1", help="Starting version (default: v1)")
    parser.add_argument("--max-iters", type=int, default=5, help="Max iterations (default: 5)")
    parser.add_argument("--n", type=int, default=5, help="Samples per eval (default: 5 to save credits)")
    parser.add_argument("--target", type=float, default=88.0, help="Stop early if final score reaches this (default: 88)")
    parser.add_argument("--rules-only", action="store_true", help="Skip LLM judge entirely (free run)")
    args = parser.parse_args()

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("Error: OPENAI_API_KEY not set")
        sys.exit(1)

    est = estimate_calls(args.n, args.max_iters, args.rules_only)
    print(f"Optimization run: base={args.base}, max_iters={args.max_iters}, n={args.n}")
    print(f"Estimated API calls: ~{est}  (two-phase: LLM judge skipped if rule score doesn't improve)")
    print(f"Early stop target: {args.target}")
    print("-" * 60)

    # Eval base
    print(f"[base] Evaluating {args.base}...")
    best_result = eval_version(args.base, args.n, api_key, args.rules_only)
    best_version = args.base
    print(f"[base] rule={best_result['avg_rule']} llm={best_result['avg_llm']} final={best_result['avg_final']} pass={best_result['pass_rate']}%")

    log = [{"iteration": 0, "version": best_version, **{k: best_result[k] for k in ("avg_rule", "avg_llm", "avg_final", "pass_rate", "hard_fails")}}]

    for i in range(1, args.max_iters + 1):
        candidate_version = f"opt_{args.base}_{i}"
        print(f"\n[iter {i}] Generating {candidate_version}...")

        context = build_weakness_context(best_result)
        new_system, new_user = generate_candidate(best_version, candidate_version, context, api_key)
        save_prompt(candidate_version, new_system, new_user)

        # Phase 1: rule-only (cheap)
        print(f"[iter {i}] Phase 1 — rule checks...")
        phase1 = eval_version(candidate_version, args.n, api_key, rules_only=True)
        print(f"[iter {i}] Rule score: {phase1['avg_rule']} (best so far: {best_result['avg_rule']})")

        if args.rules_only:
            result = phase1
        elif phase1["avg_rule"] >= best_result["avg_rule"]:
            # Phase 2: LLM judge only if rules improved
            print(f"[iter {i}] Phase 2 — LLM judge (rule score improved or held)...")
            result = eval_version(candidate_version, args.n, api_key, rules_only=False)
        else:
            print(f"[iter {i}] Skipping LLM judge — rule score dropped, candidate rejected")
            result = phase1

        improved = result["avg_final"] > best_result["avg_final"]
        marker = "NEW BEST" if improved else "no improvement"
        print(f"[iter {i}] {marker} — rule={result['avg_rule']} llm={result['avg_llm']} final={result['avg_final']} pass={result['pass_rate']}%")

        log.append({"iteration": i, "version": candidate_version, **{k: result[k] for k in ("avg_rule", "avg_llm", "avg_final", "pass_rate", "hard_fails")}})
        log_run(log)

        if improved:
            best_result = result
            best_version = candidate_version

        if best_result["avg_final"] >= args.target:
            print(f"\nTarget score {args.target} reached. Stopping early.")
            break

    print(f"\n{'='*60}")
    print(f"Best version:  {best_version}")
    print(f"Final score:   {best_result['avg_final']}/100")
    print(f"Pass rate:     {best_result['pass_rate']}%")
    print(f"\nTo deploy: python prompt_lab/export.py --version {best_version}")
    print(f"To verify:  python prompt_lab/eval.py --version {best_version} --n 10")


if __name__ == "__main__":
    main()
