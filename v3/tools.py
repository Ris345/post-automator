"""Tool functions for the v3 ADK pipeline.

Each function is registered as an ADK tool — the LLM calls them by name.
All scoring logic delegates to the existing scorer.py; no duplication.

Lambda modules are loaded via importlib (not sys.path) to avoid lambda/secrets.py
shadowing the stdlib secrets module that ADK's dependencies (starlette) need.
"""
import importlib.util
import json
import os
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
_EXAMPLES_PATH = REPO_ROOT / "prompt_lab" / "dataset" / "examples.json"
_POST_LOG = REPO_ROOT / "prompt_lab" / "results" / "post_log.json"

LIKE_THRESHOLD    = 1   # likes must be > this to be considered for reinforcement
QUALITY_THRESHOLD = 65  # final_score must be >= this — prevents viral-but-vague posts from earning reward


def _load_lambda_module(name: str):
    """Load a module from lambda/ by file path, without touching sys.path."""
    path = REPO_ROOT / "lambda" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_lambda.{name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_promptlab_module(name: str):
    """Load a module from prompt_lab/core/ by file path."""
    path = REPO_ROOT / "prompt_lab" / "core" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_promptlab.{name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Lazy-load heavy modules once at import time
_prompt_mod = _load_lambda_module("prompt")
_scorer_mod = _load_promptlab_module("scorer")  # use prompt_lab copy (prompt.py is lambda-only)
_linkedin_mod = _load_lambda_module("linkedin_client")


def get_topic() -> str:
    """Pick a random weighted topic for this week's LinkedIn post."""
    return _prompt_mod.pick_topic()


def get_examples(label: str) -> str:
    """Return labeled post examples from the dataset.

    Args:
        label: 'good' or 'bad'
    """
    with open(_EXAMPLES_PATH) as f:
        data = json.load(f)
    texts = [e["text"] for e in data["examples"] if e["label"] == label]
    return "\n".join(f"- {t}" for t in texts[:5])  # cap at 5 to keep context lean


def get_prompt_rules() -> str:
    """Return the system-level rules every post must follow."""
    return _prompt_mod.SYSTEM_PROMPT


def check_violations(draft: str) -> str:
    """Run rule checks on a single draft and return any violations.

    Returns 'PASS' if clean, 'HARD_FAIL: ...' for hard failures,
    or 'VIOLATIONS: ...' for soft violations that should be fixed.

    Args:
        draft: the post text to check
    """
    result = _scorer_mod.run_rule_checks(draft)
    if result["has_hard_fail"]:
        return f"HARD_FAIL: {', '.join(result['violations'])}"
    if result["violations"]:
        return f"VIOLATIONS: {', '.join(result['violations'])}"
    return "PASS"


def rule_score(draft: str) -> str:
    """Score a draft against all style rules. Returns JSON.

    Args:
        draft: the post text to score
    """
    result = _scorer_mod.run_rule_checks(draft)
    return json.dumps({
        "rule_score": result["rule_score"],
        "has_hard_fail": result["has_hard_fail"],
        "violations": result["violations"],
        "passed": result["passed_count"],
        "total": result["total_count"],
    })


def llm_judge(draft: str) -> str:
    """Run the LLM quality judge on a draft. Returns JSON with dimension scores.

    Scores authenticity, specificity, insight_density, tone_fit.
    llm_score is 0-100; total_raw is the raw sum (0-10).

    Args:
        draft: the post text to evaluate
    """
    api_key = os.environ["ANTHROPIC_API_KEY"]
    result = _scorer_mod.run_llm_judge(draft, api_key)
    return json.dumps({
        "llm_score": result["llm_score"],
        "total_raw": result["total_raw"],
        "authenticity": result["authenticity"],
        "specificity": result["specificity"],
        "insight_density": result["insight_density"],
        "tone_fit": result["tone_fit"],
        "reasoning": result["reasoning"],
    })


_COMPARATIVE_JUDGE_PROMPT = """You are ranking 5 LinkedIn posts written by a platform engineer named Rishav.

Compare all 5 posts against each other and rank them best to worst.

Evaluation criteria (compare posts RELATIVE TO EACH OTHER):
- Authenticity (0-3): sounds like a real practitioner vs generic AI copy
- Specificity (0-3): concrete scenario with real service names and numbers vs vague advice
- Insight density (0-3): a working engineer learns something actionable vs obvious filler
- Tone fit (0-1): direct assertion, no hedging, fits the one-sentence format

Posts:
{enumerated_drafts}

SCORING RULES — these are hard constraints, not suggestions:
1. Assign a unique llm_score (0-100) to every post — no ties allowed.
2. There must be at least 5 points between any two adjacent ranks.
3. Best post score must be at least 10 points higher than the worst.
4. Scores should cluster in the 50-90 range based on quality.

Return JSON only — no explanation outside the JSON:
{{"ranking": [
  {{"rank": 1, "index": <0-4>, "llm_score": <int>, "reasoning": "<one sentence on why this ranks here>"}},
  {{"rank": 2, "index": <0-4>, "llm_score": <int>, "reasoning": "..."}},
  {{"rank": 3, "index": <0-4>, "llm_score": <int>, "reasoning": "..."}},
  {{"rank": 4, "index": <0-4>, "llm_score": <int>, "reasoning": "..."}},
  {{"rank": 5, "index": <0-4>, "llm_score": <int>, "reasoning": "..."}}
]}}"""

JUDGE_MODEL = "claude-sonnet-4-6"


def llm_rank_all(drafts_json: str) -> str:
    """Comparatively rank all 5 drafts in one call. Forces differentiated scores — no ties.

    Presents all drafts to the judge model at once so it can rank them relative to each
    other, which produces meaningful score spreads rather than identical absolute scores.

    Args:
        drafts_json: JSON array of 5 draft strings, e.g. ["draft1", "draft2", ...]
    """
    from anthropic import Anthropic
    drafts = json.loads(drafts_json)
    enumerated = "\n".join(f"[{i}] {d}" for i, d in enumerate(drafts))
    prompt = _COMPARATIVE_JUDGE_PROMPT.format(enumerated_drafts=enumerated)

    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    resp = client.messages.create(
        model=JUDGE_MODEL,
        max_tokens=400,
        temperature=0.0,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text


def _load_post_log() -> list[dict]:
    if _POST_LOG.exists():
        return json.loads(_POST_LOG.read_text()).get("posts", [])
    return []


def _save_post_log(posts: list[dict]):
    _POST_LOG.parent.mkdir(parents=True, exist_ok=True)
    _POST_LOG.write_text(json.dumps({"posts": posts}, indent=2))


def _quality_weighted_score(post: dict) -> float:
    """likes × (final_score / 100) — rewards engagement only when quality is high."""
    likes = post.get("likes") or 0
    quality = post.get("final_score") or 0
    return likes * (quality / 100)


def get_top_performers(n: int = 3) -> str:
    """Return the top N posts ranked by quality-weighted engagement (likes × final_score/100).

    Only includes posts that pass both the like threshold AND the quality threshold.
    A post with many likes but low final_score (technically wrong or vague) is excluded
    and appears instead in get_reinforcement_context() as engagement_bait.

    Args:
        n: number of top posts to return (default 3)
    """
    posts = _load_post_log()
    qualified = [
        p for p in posts
        if p.get("likes") is not None
        and p.get("status") == "live"
        and (p.get("likes") or 0) > LIKE_THRESHOLD
        and (p.get("final_score") or 0) >= QUALITY_THRESHOLD
    ]
    if not qualified:
        return json.dumps([])
    top = sorted(qualified, key=_quality_weighted_score, reverse=True)[:n]
    return json.dumps([
        {
            "text":        p["text"],
            "likes":       p["likes"],
            "final_score": p.get("final_score"),
            "weighted":    round(_quality_weighted_score(p), 1),
        }
        for p in top
    ], indent=2)


def get_reinforcement_context() -> str:
    """Return the reinforcement learning state — reward signal, winners, and posts to avoid.

    Reinforcement is only awarded when BOTH conditions hold:
      - likes > LIKE_THRESHOLD  (real engagement)
      - final_score >= QUALITY_THRESHOLD  (technically correct and specific)

    This prevents high-likes-but-vague posts from corrupting the style signal.

    engagement_bait: posts with likes > threshold but final_score < quality threshold.
    These resonated with the audience for non-technical reasons — note their hook style
    but do NOT imitate their lack of specificity or rule violations.

    pruned_posts: deleted for zero engagement — avoid their patterns entirely.
    """
    posts = _load_post_log()

    winners = [
        p for p in posts
        if p.get("reinforcement") == 1
        and p.get("status") == "live"
        and (p.get("final_score") or 0) >= QUALITY_THRESHOLD
    ]
    engagement_bait = [
        p for p in posts
        if (p.get("likes") or 0) > LIKE_THRESHOLD
        and (p.get("final_score") or 0) < QUALITY_THRESHOLD
        and p.get("status") == "live"
    ]
    pruned = [p for p in posts if p.get("status") == "pruned"]

    total_reward = sum(p.get("reinforcement", 0) for p in posts)

    return json.dumps({
        "total_reward":    total_reward,
        "total_posts":     len(posts),
        "winning_posts": [
            {"text": p["text"], "likes": p.get("likes", 0), "final_score": p.get("final_score")}
            for p in sorted(winners, key=_quality_weighted_score, reverse=True)[:3]
        ],
        "engagement_bait": [
            {
                "text":        p["text"],
                "likes":       p.get("likes", 0),
                "final_score": p.get("final_score"),
                "note":        "resonated but technically weak — study the hook, not the content",
            }
            for p in sorted(engagement_bait, key=lambda x: x.get("likes", 0), reverse=True)[:2]
        ],
        "pruned_posts": [
            {"text": p["text"], "likes": p.get("likes", 0)}
            for p in pruned[-3:]
        ],
    }, indent=2)


def post_to_linkedin(
    draft: str,
    final_score: float = 0.0,
    rule_score: float = 0.0,
    llm_score: float = 0.0,
    dry_run: bool = True,
) -> str:
    """Publish the winning post to LinkedIn and log it for reinforcement tracking.

    Args:
        draft:       the final post text to publish
        final_score: combined score (0-100) from the scoring agent
        rule_score:  rule compliance score (0-100)
        llm_score:   LLM quality score (0-100)
        dry_run:     if True, skips the real API call and returns a preview
    """
    if dry_run:
        return f"DRY_RUN — would publish: {draft}"
    from datetime import datetime, timezone
    access_token = os.environ["LINKEDIN_ACCESS_TOKEN"]
    person_urn = os.environ["LINKEDIN_PERSON_URN"]
    post_id = _linkedin_mod.publish_post(access_token, person_urn, draft)

    posts = _load_post_log()
    posts.append({
        "post_id":          post_id,
        "post_urn":         f"urn:li:ugcPost:{post_id}",
        "text":             draft,
        "published_at":     datetime.now(timezone.utc).isoformat(),
        "final_score":      final_score,
        "rule_score":       rule_score,
        "llm_score":        llm_score,
        "views":            None,
        "clicks":           None,
        "likes":            None,
        "comments":         None,
        "views_fetched_at": None,
        "reinforcement":    0,
        "status":           "live",
        "deleted_at":       None,
    })
    _save_post_log(posts)

    return f"POSTED: {post_id}"
