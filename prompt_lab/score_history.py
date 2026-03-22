#!/usr/bin/env python3
"""Show score history across all eval runs.

Usage:
  python prompt_lab/score_history.py
  python prompt_lab/score_history.py --version v1
"""
import argparse
import sys
from pathlib import Path

PROMPT_LAB = Path(__file__).parent
sys.path.insert(0, str(PROMPT_LAB))

from core.history import load_history


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default=None, help="Filter by version")
    args = parser.parse_args()

    runs = load_history().get("runs", [])
    if args.version:
        runs = [r for r in runs if r["version"] == args.version]

    if not runs:
        print("No eval runs found. Run: python prompt_lab/eval.py --version v1 --n 10")
        return

    print(f"{'Run ID':<20} {'Ver':<6} {'N':<4} {'Rule':>6} {'LLM':>6} {'Final':>7} {'Pass%':>6} {'Hard':>5}  Top violation")
    print("-" * 90)

    for r in runs:
        llm = f"{r['avg_llm_score']:.0f}" if r.get("avg_llm_score") is not None else "N/A"
        vc = r.get("violation_counts", {})
        top_v = ""
        if vc:
            top = max(vc, key=lambda k: vc[k])
            top_v = f"{top}({vc[top]})"
        print(
            f"{r['run_id']:<20} {r['version']:<6} {r['n']:<4} "
            f"{r['avg_rule_score']:>6.0f} {llm:>6} {r['avg_final_score']:>7.1f} "
            f"{r['pass_rate_pct']:>5}% {r['hard_fail_count']:>5}  {top_v}"
        )


if __name__ == "__main__":
    main()
