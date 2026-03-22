#!/usr/bin/env python3
"""Generate an improved prompt version guided by eval results.

Usage:
  OPENAI_API_KEY=sk-... python prompt_lab/generate.py --base v1 --out v2
  python prompt_lab/generate.py --base v1 --out v2 --focus "reduce vague conclusions"
"""
import argparse
import difflib
import os
import sys
from pathlib import Path

PROMPT_LAB = Path(__file__).parent
sys.path.insert(0, str(PROMPT_LAB))

from dotenv import load_dotenv
load_dotenv(PROMPT_LAB.parent / ".env")

from core.history import get_violation_counts, get_runs_for_version

PROMPTS_DIR = PROMPT_LAB / "prompts"
LAMBDA_DIR = PROMPT_LAB.parent / "lambda"

META_SYSTEM = """You are an expert prompt engineer improving a system prompt used to generate LinkedIn posts.
Return ONLY the improved prompts — no explanation, no preamble, no markdown fences.
Format your response exactly as:

SYSTEM_PROMPT:
<new system prompt text>

USER_PROMPT:
<new user prompt text>"""

META_USER = """{context}

Current system prompt:
---
{system}
---

Current user prompt:
---
{user}
---

Requirements you must follow:
- Preserve the persona (Rishav, platform engineer)
- Preserve the one-sentence format
- Preserve all hard rules (no em dash, no statistics, no emoji)
- Good examples in USER_PROMPT must not violate any rule stated in SYSTEM_PROMPT
- Address the weaknesses listed above specifically

Generate the improved prompts now."""


def load_base(version: str) -> tuple[str, str]:
    sf = PROMPTS_DIR / f"system_{version}.txt"
    uf = PROMPTS_DIR / f"user_{version}.txt"
    if sf.exists() and uf.exists():
        return sf.read_text().strip(), uf.read_text().strip()
    if version == "v1":
        sys.path.insert(0, str(LAMBDA_DIR))
        from prompt import SYSTEM_PROMPT, USER_PROMPT
        return SYSTEM_PROMPT, USER_PROMPT
    raise FileNotFoundError(f"Version '{version}' not found")


def build_context(base_version: str, focus: str) -> str:
    lines = []
    runs = get_runs_for_version(base_version)
    if runs:
        counts = get_violation_counts(base_version)
        if counts:
            top = sorted(counts.items(), key=lambda x: -x[1])[:5]
            lines.append(f"Eval results across {len(runs)} run(s) of version '{base_version}':")
            lines.append("Most frequent rule violations:")
            for rule, count in top:
                lines.append(f"  - {rule}: {count} violation(s)")
        llm_scores = [r["avg_llm_score"] for r in runs if r.get("avg_llm_score") is not None]
        if llm_scores:
            lines.append(f"Average LLM quality score: {sum(llm_scores)/len(llm_scores):.1f}/100")
    else:
        lines.append(f"No eval results found for version '{base_version}'. Generating a general improvement.")

    if focus:
        lines.append(f"\nSpecific focus area: {focus}")

    return "\n".join(lines)


def parse_response(text: str) -> tuple[str, str]:
    if "SYSTEM_PROMPT:" not in text or "USER_PROMPT:" not in text:
        raise ValueError(f"Response missing required markers.\nGot:\n{text[:500]}")
    after_system = text.split("SYSTEM_PROMPT:", 1)[1]
    parts = after_system.split("USER_PROMPT:", 1)
    system = parts[0].strip().strip("---").strip()
    user = parts[1].strip().strip("---").strip()
    return system, user


def show_diff(label: str, old: str, new: str):
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    diff = list(difflib.unified_diff(old_lines, new_lines, fromfile=f"{label} (current)", tofile=f"{label} (new)"))
    if diff:
        print(f"\n--- {label} diff ---")
        print("".join(diff))
    else:
        print(f"\n{label}: no changes")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="v1", help="Base version to improve (default: v1)")
    parser.add_argument("--out", required=True, help="Output version name (e.g. v2)")
    parser.add_argument("--focus", default="", help="Specific weakness to target")
    args = parser.parse_args()

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("Error: OPENAI_API_KEY not set")
        sys.exit(1)

    out_sf = PROMPTS_DIR / f"system_{args.out}.txt"
    out_uf = PROMPTS_DIR / f"user_{args.out}.txt"
    if out_sf.exists() or out_uf.exists():
        print(f"Error: version '{args.out}' already exists. Choose a different name.")
        sys.exit(1)

    base_system, base_user = load_base(args.base)
    context = build_context(args.base, args.focus)

    print(f"Generating '{args.out}' from '{args.base}'...")
    print(context)

    from openai import OpenAI
    client = OpenAI(api_key=api_key)
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": META_SYSTEM},
            {"role": "user", "content": META_USER.format(
                context=context,
                system=base_system,
                user=base_user,
            )},
        ],
        max_tokens=1200,
        temperature=0.7,
    )

    new_system, new_user = parse_response(resp.choices[0].message.content)
    PROMPTS_DIR.mkdir(exist_ok=True)
    out_sf.write_text(new_system)
    out_uf.write_text(new_user)

    show_diff("system_prompt", base_system, new_system)
    show_diff("user_prompt", base_user, new_user)

    print(f"\nSaved: prompt_lab/prompts/system_{args.out}.txt")
    print(f"Saved: prompt_lab/prompts/user_{args.out}.txt")
    print(f"\nNext: python prompt_lab/eval.py --version {args.out} --n 10")


if __name__ == "__main__":
    main()
