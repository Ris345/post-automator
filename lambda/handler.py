import logging
from secrets import get_secrets
from openai_client import generate_post
from linkedin_client import publish_post

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event, context):
    logger.info("Starting LinkedIn post automation")

    # 1. Fetch credentials (env locally, Secrets Manager on Lambda)
    creds = get_secrets()

    # 2. Generate post via OpenAI
    logger.info("Generating post with gpt-4o-mini")
    post_text = generate_post(creds["openai_api_key"])
    logger.info("Generated post:\n%s", post_text)

    # 3. Publish to LinkedIn
    logger.info("Publishing to LinkedIn as %s", creds["person_urn"])
    post_id = publish_post(creds["access_token"], creds["person_urn"], post_text)
    logger.info("Successfully published. LinkedIn post ID: %s", post_id)

    return {
        "status": "success",
        "post_id": post_id,
        "post_preview": post_text[:80] + "...",
    }
