"""Reads and writes eval run history to prompt_lab/results/."""
import json
from pathlib import Path

RESULTS_DIR = Path(__file__).parent.parent / "results"
HISTORY_FILE = RESULTS_DIR / "history.json"


def load_history() -> dict:
    if not HISTORY_FILE.exists():
        return {"runs": []}
    return json.loads(HISTORY_FILE.read_text())


def append_run(run_summary: dict):
    RESULTS_DIR.mkdir(exist_ok=True)
    data = load_history()
    data["runs"].append(run_summary)
    HISTORY_FILE.write_text(json.dumps(data, indent=2))


def save_run_detail(run_data: dict) -> str:
    RESULTS_DIR.mkdir(exist_ok=True)
    ts = run_data["meta"]["run_id"]
    version = run_data["meta"]["version"]
    fname = f"{version}_run_{ts}.json"
    (RESULTS_DIR / fname).write_text(json.dumps(run_data, indent=2))
    return fname


def get_runs_for_version(version: str) -> list[dict]:
    return [r for r in load_history().get("runs", []) if r["version"] == version]


def get_violation_counts(version: str) -> dict:
    """Aggregate violation counts across all runs for a version."""
    combined: dict[str, int] = {}
    for run in get_runs_for_version(version):
        for k, v in run.get("violation_counts", {}).items():
            combined[k] = combined.get(k, 0) + v
    return combined
