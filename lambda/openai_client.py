from openai import OpenAI
from prompt import SYSTEM_PROMPT, USER_PROMPT


def generate_post(api_key: str) -> str:
    client = OpenAI(api_key=api_key)

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_PROMPT},
        ],
        max_tokens=300,
        temperature=0.85,
    )

    post = response.choices[0].message.content.strip()
    return post
