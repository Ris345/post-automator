#!/usr/bin/env python3
"""Generate and score a post locally, or smoke-test the real deployed Lambda.

Usage:
  python test_post.py             # single post, local only
  python test_post.py --n 5       # 5 posts, local only
  python test_post.py --smoke     # invoke real Lambda on AWS (no LinkedIn publish)
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

sys.path.insert(0, str(Path(__file__).parent / "lambda"))
sys.path.insert(0, str(Path(__file__).parent / "prompt_lab"))

from openai_client import generate_post
from prompt import pick_topic
from core.scorer import run_rule_checks


def test_one(api_key: str):
    topic = pick_topic()
    post = generate_post(api_key)
    result = run_rule_checks(post)

    status = "HARD FAIL" if result["has_hard_fail"] else ("PASS" if not result["violations"] else "WARN")
    violations = result["violations"]

    print(f"\nTopic:  {topic}")
    print(f"Post:   {post}")
    print(f"Rules:  {status}  ({result['passed_count']}/{result['total_count']} passed)", end="")
    if violations:
        print(f"  [{', '.join(violations)}]", end="")
    print()


def smoke_test():
    print("Invoking deployed Lambda with dry_run=true (no LinkedIn publish)...")
    out_file = "/tmp/lambda_smoke_out.json"
    result = subprocess.run(
        [
            "aws", "lambda", "invoke",
            "--function-name", "post-automator",
            "--payload", json.dumps({"dry_run": True}),
            "--cli-binary-format", "raw-in-base64-out",
            out_file,
        ],
        capture_output=True, text=True,
    )

    if result.returncode != 0:
        print(f"Error invoking Lambda:\n{result.stderr}")
        sys.exit(1)

    with open(out_file) as f:
        response = json.load(f)

    if "errorMessage" in response:
        print(f"Lambda error: {response['errorMessage']}")
        sys.exit(1)

    post = response.get("post", "")
    rule_result = run_rule_checks(post)
    status = "HARD FAIL" if rule_result["has_hard_fail"] else ("PASS" if not rule_result["violations"] else "WARN")
    violations = rule_result["violations"]

    print(f"\nPost:   {post}")
    print(f"Rules:  {status}  ({rule_result['passed_count']}/{rule_result['total_count']} passed)", end="")
    if violations:
        print(f"  [{', '.join(violations)}]", end="")
    print()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=1, help="Number of posts to generate (default: 1)")
    parser.add_argument("--smoke", action="store_true", help="Invoke real deployed Lambda on AWS (dry run, no publish)")
    args = parser.parse_args()

    if args.smoke:
        smoke_test()
        return

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("Error: OPENAI_API_KEY not set in .env")
        sys.exit(1)

    for i in range(args.n):
        if args.n > 1:
            print(f"\n{'='*60}  [{i+1}/{args.n}]")
        test_one(api_key)


if __name__ == "__main__":
    main()
