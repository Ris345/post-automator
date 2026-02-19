import requests


LINKEDIN_API_URL = "https://api.linkedin.com/v2/ugcPosts"


def publish_post(access_token: str, person_urn: str, text: str) -> str:
    """
    Publishes a text-only post to LinkedIn.
    Returns the LinkedIn post URN on success.
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
    }

    payload = {
        "author": person_urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {
                    "text": text,
                },
                "shareMediaCategory": "NONE",
            }
        },
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC",
        },
    }

    response = requests.post(LINKEDIN_API_URL, headers=headers, json=payload, timeout=10)

    if response.status_code != 201:
        raise RuntimeError(
            f"LinkedIn API error {response.status_code}: {response.text}"
        )

    post_id = response.headers.get("x-restli-id", "unknown")
    return post_id
