#!/usr/bin/env python3
"""Export a winning prompt version to lambda/prompt.py.

Usage:
  python prompt_lab/export.py --version v2
  python prompt_lab/export.py --version v2 --dry-run
"""
import argparse
import sys
from pathlib import Path

PROMPT_LAB = Path(__file__).parent
PROMPTS_DIR = PROMPT_LAB / "prompts"
LAMBDA_PROMPT = PROMPT_LAB.parent / "lambda" / "prompt.py"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True, help="Version to export (e.g. v2)")
    parser.add_argument("--dry-run", action="store_true", help="Print output without writing")
    args = parser.parse_args()

    sf = PROMPTS_DIR / f"system_{args.version}.txt"
    uf = PROMPTS_DIR / f"user_{args.version}.txt"

    if not sf.exists() or not uf.exists():
        print(f"Error: version '{args.version}' not found in {PROMPTS_DIR}")
        sys.exit(1)

    system = sf.read_text().strip()
    user = uf.read_text().strip()

    content = (
        f"# prompt version: {args.version}\n"
        f'SYSTEM_PROMPT = """\n{system}\n""".strip()\n'
        f"\n"
        f'USER_PROMPT = """\n{user}\n""".strip()\n'
    )

    if args.dry_run:
        print("--- lambda/prompt.py (dry run) ---")
        print(content)
        return

    LAMBDA_PROMPT.write_text(content)
    print(f"Updated lambda/prompt.py with version '{args.version}'")
    print("Review changes, then build and push: see CLAUDE.md for deploy commands.")


if __name__ == "__main__":
    main()
