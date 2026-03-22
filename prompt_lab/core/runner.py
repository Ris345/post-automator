"""Generates N post samples — replicates exact parameters from lambda/openai_client.py."""
import sys
import time
from pathlib import Path
from openai import OpenAI

# Import pick_topic from lambda so eval matches real Lambda behaviour
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "lambda"))
from prompt import pick_topic


def generate_samples(system_prompt: str, user_prompt: str, api_key: str, n: int) -> list[dict]:
    client = OpenAI(api_key=api_key)
    results = []
    for i in range(n):
        topic = pick_topic()
        formatted_prompt = user_prompt.format(topic=topic) if "{topic}" in user_prompt else user_prompt
        start = time.time()
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": formatted_prompt},
            ],
            max_tokens=300,
            temperature=0.85,
        )
        latency_ms = int((time.time() - start) * 1000)
        text = resp.choices[0].message.content.strip()
        results.append({"index": i, "text": text, "latency_ms": latency_ms, "topic": topic})
    return results
