#!/usr/bin/env python3
"""Local test runner for the v3 ADK pipeline.

Usage:
  python test_v3.py              # dry run (default) — scores all 5, no LinkedIn post
  python test_v3.py --publish    # real run — posts to LinkedIn if score >= 65
"""
import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

from v3.pipeline import run

CONFIDENCE_THRESHOLD = 65


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--publish", action="store_true", help="Actually post to LinkedIn (default: dry run)")
    args = parser.parse_args()

    dry_run = not args.publish
    print(f"\n{'='*60}")
    print(f"LinkedIn Automator — v3 ADK Pipeline")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE — will post to LinkedIn'}")
    print(f"Confidence threshold: {CONFIDENCE_THRESHOLD}/100")
    print(f"{'='*60}\n")

    try:
        result = run(dry_run=dry_run)
    except Exception as e:
        print(f"Pipeline error: {e}")
        sys.exit(1)

    winner = result.get("winner", {})
    publisher_output = result.get("publisher_output", "")

    if winner:
        ranking = winner.get("ranking", [])
        best_draft = winner.get("best_draft", "")
        best_score = winner.get("best_score", 0)

        print("RANKED DRAFTS")
        print("-" * 60)
        for entry in ranking:
            flag = " ← WINNER" if entry["rank"] == 1 else ""
            print(f"  #{entry['rank']}  score={entry['final_score']:5.1f}  "
                  f"(rule={entry['rule_score']:.0f}, llm={entry['llm_score']:.0f}){flag}")
            print(f"       {entry['draft'][:100]}{'...' if len(entry['draft']) > 100 else ''}")
        print()

        print("WINNER")
        print("-" * 60)
        print(f"  Score: {best_score}/100  (threshold: {CONFIDENCE_THRESHOLD})")
        print(f"  Post:  {best_draft}")
        print()

    print("PUBLISHER DECISION")
    print("-" * 60)
    print(f"  {publisher_output}")
    print()


if __name__ == "__main__":
    main()
