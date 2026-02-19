import os


def get_secrets() -> dict:
    required = ("OPENAI_API_KEY", "LINKEDIN_ACCESS_TOKEN", "LINKEDIN_PERSON_URN")
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        raise RuntimeError(f"Missing env vars: {', '.join(missing)}")

    return {
        "openai_api_key": os.environ["OPENAI_API_KEY"],
        "access_token": os.environ["LINKEDIN_ACCESS_TOKEN"],
        "person_urn": os.environ["LINKEDIN_PERSON_URN"],
    }
