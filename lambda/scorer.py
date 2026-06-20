"""Rule-based compliance checks + LLM judge for LinkedIn post evaluation."""
import re
import json
from openai import OpenAI

REAL_TOOLS = {
    # Core AWS
    "EKS", "ECR", "Lambda", "CloudWatch", "Datadog", "Kubernetes", "k8s",
    "Terraform", "Docker", "X-Ray", "S3", "RDS", "SQS", "SNS", "IAM", "VPC",
    "ALB", "NLB", "HPA", "PDB", "Prometheus", "Grafana", "Helm", "ArgoCD",
    "ECS", "Fargate", "EventBridge", "API Gateway", "DynamoDB", "ElastiCache",
    "Route 53", "CloudFront", "SSM", "Parameter Store", "Secrets Manager",
    "CodePipeline", "CodeBuild", "CodeDeploy", "Step Functions", "Kinesis",
    "Karpenter", "Aurora", "MemoryDB", "OpenSearch",
    # ML / GenAI infra
    "SageMaker", "Bedrock", "pgvector", "HNSW",
}

OUTCOME_WORDS = {
    "latency", "timeout", "threshold", "bytes", "seconds", "ms", "nodes",
    "pods", "replicas", "requests", "queue", "metric", "limit", "cost",
    "memory", "cpu", "vcpu", "throughput", "interval", "scrape",
}

VAGUE_PHRASES = [
    "made a significant difference",
    "worth considering",
    "really matters",
    "in the long run",
    "significantly improve",
    "meaningful impact",
    "best practices",
]

FORBIDDEN_VERB_STEMS = ["consider", "ensur", "implement"]
HEDGING_STEMS = ["can", "may", "might", "could"]

CORPORATE_SPEAK = [
    "leverag", "synergy", "paradigm", "streamlin", "best-in-class",
    "world-class", "cutting-edge", "innovative solution", "empower", "holistic",
]

CONDITIONAL_PHRASES = ["unless ", "without ", " if you", " if your", " if the"]


def _is_multi_sentence(text: str) -> bool:
    cleaned = text.strip().rstrip('"\'')
    return bool(re.search(r'[.!?]\s+[A-Z]', cleaned))


def _has_statistics(text: str) -> bool:
    return bool(re.search(r'\d+\s*%|\b\d+[xX]\b', text))


def _has_emoji(text: str) -> bool:
    return bool(re.search(r'[\U0001F300-\U0001FAFF\U00002700-\U000027BF]', text))


def _names_real_tool(text: str) -> bool:
    for tool in REAL_TOOLS:
        if re.search(r'\b' + re.escape(tool) + r'\b', text, re.IGNORECASE):
            return True
    return False


def _ends_with_specific(text: str) -> bool:
    last_part = text.rsplit(',', 1)[-1]
    if re.search(r'\d', last_part):
        return True
    for word in OUTCOME_WORDS:
        if word.lower() in last_part.lower():
            return True
    for tool in REAL_TOOLS:
        if re.search(r'\b' + re.escape(tool) + r'\b', last_part, re.IGNORECASE):
            return True
    return False


# (name, check_fn returns True if VIOLATION, is_hard_fail)
RULE_CHECKS: list[tuple[str, callable, bool]] = [
    ("single_sentence", _is_multi_sentence, False),
    ("no_em_dash", lambda t: '—' in t or '–' in t, True),
    ("no_semicolon", lambda t: ';' in t, False),
    ("no_starts_with_if", lambda t: t.strip().lower().startswith("if "), False),
    ("no_statistics", _has_statistics, True),
    ("no_emoji", _has_emoji, True),
    ("no_vague_conclusions", lambda t: any(p.lower() in t.lower() for p in VAGUE_PHRASES), False),
    ("no_forbidden_verbs", lambda t: any(re.search(r'\b' + v + r'\w*\b', t, re.I) for v in FORBIDDEN_VERB_STEMS), False),
    ("no_hedging", lambda t: any(re.search(r'\b' + w + r'\w*\b', t, re.I) for w in HEDGING_STEMS), True),
    ("no_conditional", lambda t: any(p.lower() in t.lower() for p in CONDITIONAL_PHRASES), False),
    ("no_corporate_speak", lambda t: any(p.lower() in t.lower() for p in CORPORATE_SPEAK), False),
    ("no_first_person_story", lambda t: bool(re.match(r'^(I was|I spent|I noticed|I found|Spent the)', t.strip(), re.I)), False),
    ("names_real_tool", lambda t: not _names_real_tool(t), False),   # violation = NOT naming a tool
    ("ends_with_specific", lambda t: not _ends_with_specific(t), False),  # violation = NOT ending specific
]


def run_rule_checks(text: str) -> dict:
    results = []
    has_hard_fail = False
    violation_names = []

    for name, check_fn, is_hard_fail in RULE_CHECKS:
        violated = check_fn(text)
        if violated:
            violation_names.append(name)
            if is_hard_fail:
                has_hard_fail = True
        results.append({"rule": name, "passed": not violated, "hard_fail": is_hard_fail and violated})

    passed = sum(1 for r in results if r["passed"])
    rule_score = 0.0 if has_hard_fail else round((passed / len(results)) * 100, 1)

    return {
        "checks": results,
        "violations": violation_names,
        "passed_count": passed,
        "total_count": len(results),
        "has_hard_fail": has_hard_fail,
        "rule_score": rule_score,
    }


JUDGE_PROMPT = """You are evaluating a LinkedIn post by a platform engineer named Rishav.

Mechanical rule checks have already been run. Judge ONLY what rules cannot capture:
- authenticity (0-3): Sounds like a real practitioner, not marketing copy or AI text?
- specificity (0-3): Names a real, concrete scenario — not generic advice for any cloud workload?
- insight_density (0-3): Does a working engineer learn something actionable, or is it obvious/filler?
- tone_fit (0-1): Direct, no hedging, fits one-sentence format?

Reference:
GOOD: "Running more than two EKS node groups without Cluster Autoscaler means you're probably over-provisioning without realizing it."
GOOD: "Lambda's default timeout is 3 seconds, which causes silent failures for any function calling an external API under normal network latency."
BAD: "The more I dig into cloud architecture, the clearer it becomes: complexity often creeps in when we try to over-optimize."
BAD: "Spent the week tuning our Kubernetes HPA settings because the CPU utilization was spiking unexpectedly during peak traffic, and adjusting the thresholds made a significant difference."

Post to evaluate:
"{text}"

Reply with JSON only:
{{"authenticity": <0-3>, "specificity": <0-3>, "insight_density": <0-3>, "tone_fit": <0-1>, "total": <sum>, "reasoning": "<one sentence on the lowest-scoring dimension>"}}"""


def run_llm_judge(text: str, api_key: str) -> dict:
    client = OpenAI(api_key=api_key)
    resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": JUDGE_PROMPT.format(text=text)}],
        max_tokens=150,
        temperature=0.0,
        response_format={"type": "json_object"},
    )
    result = json.loads(resp.choices[0].message.content)
    llm_score = round((result.get("total", 0) / 10) * 100, 1)
    return {
        "authenticity": result.get("authenticity", 0),
        "specificity": result.get("specificity", 0),
        "insight_density": result.get("insight_density", 0),
        "tone_fit": result.get("tone_fit", 0),
        "total_raw": result.get("total", 0),
        "reasoning": result.get("reasoning", ""),
        "llm_score": llm_score,
    }
