import logging
from secrets import get_secrets
from openai_client import generate_post
from linkedin_client import publish_post
from scorer import run_rule_checks, run_llm_judge

logger = logging.getLogger()
logger.setLevel(logging.INFO)

MAX_ATTEMPTS = 5
MIN_RULE_SCORE = 92
MIN_FINAL_SCORE = 70


def handler(event, context):
    dry_run = event.get("dry_run", False)
    logger.info("Starting LinkedIn post automation%s", " [DRY RUN]" if dry_run else "")

    creds = get_secrets()

    post_text = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        logger.info("Generating post (attempt %d/%d)", attempt, MAX_ATTEMPTS)
        candidate = generate_post(creds["openai_api_key"])
        rule_result = run_rule_checks(candidate)
        rule_score = rule_result["rule_score"]
        violations = rule_result["violations"]

        if rule_result["has_hard_fail"] or rule_score < MIN_RULE_SCORE:
            logger.warning("Attempt %d failed rule checks (score=%s, violations=%s), retrying...", attempt, rule_score, violations)
            continue

        llm_result = run_llm_judge(candidate, creds["openai_api_key"])
        final_score = round(0.4 * rule_score + 0.6 * llm_result["llm_score"], 1)
        logger.info("Attempt %d scores — rule: %s, llm: %s, final: %s | %s\n%s",
                    attempt, rule_score, llm_result["llm_score"], final_score,
                    llm_result["reasoning"], candidate)

        if final_score >= MIN_FINAL_SCORE:
            post_text = candidate
            break
        logger.warning("Attempt %d failed quality threshold (final=%s), retrying...", attempt, final_score)

    if post_text is None:
        raise RuntimeError(f"Failed to generate a passing post after {MAX_ATTEMPTS} attempts")

    if dry_run:
        return {"status": "dry_run", "post": post_text}

    logger.info("Publishing to LinkedIn as %s", creds["person_urn"])
    try:
        post_id = publish_post(creds["access_token"], creds["person_urn"], post_text)
    except RuntimeError as e:
        if "401" in str(e):
            raise RuntimeError("LinkedIn token expired — run: python scripts/auth.py") from e
        raise
    logger.info("Successfully published. LinkedIn post ID: %s", post_id)

    return {
        "status": "success",
        "post_id": post_id,
        "post_preview": post_text[:80] + "...",
    }
