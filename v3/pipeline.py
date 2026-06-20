"""v3 LinkedIn post pipeline — Google ADK multi-agent architecture.

Flow:
  DraftPoolAgent (generates 5 drafts, self-sanitizes via check_violations)
    → output_key="drafts" → session.state["drafts"]
  ScoringAgent (scores all 5 with rule_score + llm_judge, picks best)
    → output_key="winner" → session.state["winner"]
  PublisherAgent (posts if best final_score >= CONFIDENCE_THRESHOLD, else skips)

Confidence threshold: final_score >= 65 (0-100 scale).
  - rule_score contributes 40%, llm_judge 60%
  - Hard fails (em dash, hedging, statistics, emoji) zero out rule_score
  - A hard-failing post can score at most 60, which is below threshold
"""
import asyncio
import json
import os
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from google.adk.agents import LlmAgent, SequentialAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.sessions import InMemorySessionService
from google.adk.runners import Runner
from google.genai import types

from v3.tools import (
    get_topic, get_examples, get_prompt_rules,
    check_violations, rule_score, llm_rank_all, post_to_linkedin,
    get_top_performers, get_reinforcement_context,
)

CONFIDENCE_THRESHOLD = 65  # final_score out of 100

_MODEL = LiteLlm(model="anthropic/claude-sonnet-4-6")

_DRAFT_POOL_INSTRUCTION = """
You are Rishav, an infrastructure engineer writing LinkedIn posts about AWS, Kubernetes, and distributed systems.

Task: generate exactly 5 DISTINCT one-sentence post drafts.

Steps (in order — complete ALL tool calls before writing anything):
1. Call get_topic() — your assigned topic. All 5 drafts must be about this topic.
2. Call get_prompt_rules() — hard rules every draft must obey.
3. Call get_examples("good") — the gold standard to match.
4. Call get_examples("bad") — patterns you must never use.
5. Call get_top_performers() — posts that earned the most LinkedIn likes. Study their style: specificity level, how they end, what they name. Mirror that style.
6. Call get_reinforcement_context() — the running reward signal. Winning posts (reinforcement=1) show what earns engagement; pruned posts (status=pruned) show patterns to avoid. If total_reward > 0, weight your drafts toward winning patterns.
7. Write all 5 drafts now. Each must cover a DIFFERENT specific behavior, limit, or quirk.
8. Call check_violations(draft) for all 5 drafts. Fix any that return VIOLATIONS or HARD_FAIL, then recheck only the fixed ones.

Output ONLY a raw JSON array of 5 strings. No markdown, no explanation:
["draft one", "draft two", "draft three", "draft four", "draft five"]
"""

_SCORING_INSTRUCTION = """
You have 5 LinkedIn post drafts to rank:
{drafts}

Follow these steps exactly:

Step 1 — Rule scoring (call once per draft, 5 calls total):
  Call rule_score(draft) for each of the 5 drafts. Record rule_score for each.

Step 2 — Comparative LLM ranking (ONE call for all 5):
  Build a JSON array of all 5 draft strings in order, then call llm_rank_all with that JSON.
  Example: llm_rank_all(drafts_json='["draft0", "draft1", "draft2", "draft3", "draft4"]')
  The tool returns a ranking with llm_score per draft. Record llm_score for each.

Step 3 — Compute final scores:
  final_score = round(0.4 * rule_score + 0.6 * llm_score, 1)
  Do this for all 5 drafts.

Step 4 — Sort by final_score descending. The highest is the winner.

Output ONLY a raw JSON object. No markdown, no explanation:
{{
  "best_draft": "<text of the #1 ranked draft>",
  "best_score": <float>,
  "ranking": [
    {{"rank": 1, "draft": "...", "rule_score": X, "llm_score": X, "final_score": X}},
    {{"rank": 2, "draft": "...", "rule_score": X, "llm_score": X, "final_score": X}},
    {{"rank": 3, "draft": "...", "rule_score": X, "llm_score": X, "final_score": X}},
    {{"rank": 4, "draft": "...", "rule_score": X, "llm_score": X, "final_score": X}},
    {{"rank": 5, "draft": "...", "rule_score": X, "llm_score": X, "final_score": X}}
  ]
}}
"""

_PUBLISHER_INSTRUCTION = f"""
The scoring agent selected the best post from 5 candidates:
{{winner}}

Parse that JSON. Extract from ranking[0] (rank 1): draft, rule_score, llm_score, final_score.

Decision:
- If final_score >= {CONFIDENCE_THRESHOLD}: call post_to_linkedin with draft, final_score, rule_score, llm_score. Report what was posted.
- If final_score < {CONFIDENCE_THRESHOLD}: do NOT post. Output exactly:
  "SKIP: best score <final_score> below confidence threshold {CONFIDENCE_THRESHOLD}. No post this week."
"""


def _build_publisher_tool(dry_run: bool):
    """Return a post_to_linkedin tool with dry_run baked in."""
    def _publish(draft: str, final_score: float = 0.0, rule_score: float = 0.0, llm_score: float = 0.0) -> str:
        """Publish the winning post to LinkedIn. Returns post ID or dry-run confirmation.

        Args:
            draft:       the final post text to publish
            final_score: combined score from the scoring agent (0-100)
            rule_score:  rule compliance score (0-100)
            llm_score:   LLM quality score (0-100)
        """
        return post_to_linkedin(draft, final_score=final_score, rule_score=rule_score,
                                llm_score=llm_score, dry_run=dry_run)
    return _publish


def build_pipeline(dry_run: bool = True) -> SequentialAgent:
    draft_pool = LlmAgent(
        name="draft_pool",
        model=_MODEL,
        instruction=_DRAFT_POOL_INSTRUCTION,
        output_key="drafts",
        tools=[get_topic, get_examples, get_prompt_rules, check_violations, get_top_performers, get_reinforcement_context],
    )

    scorer = LlmAgent(
        name="scorer",
        model=_MODEL,
        instruction=_SCORING_INSTRUCTION,
        output_key="winner",
        tools=[rule_score, llm_rank_all],
    )

    publisher = LlmAgent(
        name="publisher",
        model=_MODEL,
        instruction=_PUBLISHER_INSTRUCTION,
        tools=[_build_publisher_tool(dry_run=dry_run)],
    )

    return SequentialAgent(
        name="linkedin_v3",
        sub_agents=[draft_pool, scorer, publisher],
    )


async def _run_async(dry_run: bool = True, max_retries: int = 3) -> dict:
    for attempt in range(max_retries):
        try:
            return await _attempt_run(dry_run=dry_run)
        except Exception as e:
            is_rate_limit = "RateLimitError" in type(e).__name__ or "rate_limit" in str(e).lower()
            if is_rate_limit and attempt < max_retries - 1:
                wait = 60 * (attempt + 1)
                print(f"\n[Rate limit] waiting {wait}s before retry {attempt + 2}/{max_retries}...")
                await asyncio.sleep(wait)
            else:
                raise


async def _attempt_run(dry_run: bool = True) -> dict:
    session_service = InMemorySessionService()
    session = await session_service.create_session(
        app_name="linkedin_v3",
        user_id="rishav",
        session_id="v3_local",
    )

    pipeline = build_pipeline(dry_run=dry_run)
    runner = Runner(
        agent=pipeline,
        app_name="linkedin_v3",
        session_service=session_service,
    )

    publisher_output = ""
    async for event in runner.run_async(
        user_id="rishav",
        session_id=session.id,
        new_message=types.Content(
            role="user",
            parts=[types.Part(text="Generate and publish a LinkedIn post.")],
        ),
    ):
        if event.is_final_response() and event.content and event.content.parts:
            publisher_output = event.content.parts[0].text

    # Read intermediate state for display
    final_session = await session_service.get_session(
        app_name="linkedin_v3",
        user_id="rishav",
        session_id=session.id,
    )
    winner_raw = final_session.state.get("winner", "{}") if final_session else "{}"
    try:
        winner = json.loads(winner_raw)
    except (json.JSONDecodeError, TypeError):
        winner = {}

    return {
        "publisher_output": publisher_output,
        "winner": winner,
    }


def run(dry_run: bool = True) -> dict:
    return asyncio.run(_run_async(dry_run=dry_run))
