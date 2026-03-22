"""Loads labeled post examples from prompt_lab/dataset/examples.json."""
import json
import random
from pathlib import Path

DATASET_FILE = Path(__file__).parent.parent / "dataset" / "examples.json"


def load_examples(n_good: int = 2, n_bad: int = 1) -> dict:
    if not DATASET_FILE.exists():
        return {"good": [], "bad": []}
    data = json.loads(DATASET_FILE.read_text())
    examples = data.get("examples", [])
    good = [e["text"] for e in examples if e["label"] == "good"]
    bad = [e["text"] for e in examples if e["label"] == "bad"]
    return {
        "good": random.sample(good, min(n_good, len(good))),
        "bad": random.sample(bad, min(n_bad, len(bad))),
    }
