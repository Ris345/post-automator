# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Does

Generates and publishes a single-sentence infrastructure/system design insight to LinkedIn every Sunday at 1 PM EST, using OpenAI (`gpt-4o-mini`) for content generation. Runs as a Lambda container image triggered by EventBridge Scheduler.

Posts rotate across a weighted topic mix: AWS service behavior and Kubernetes most frequently, system design patterns occasionally, ML infrastructure (SageMaker, Bedrock, vector DBs) rarely. Persona is Rishav — an infrastructure engineer who understands distributed systems deeply.

## Architecture

```
EventBridge Scheduler (cron Sun 1PM EST)
  → Lambda (container image from ECR)
      → secrets.py      — reads env vars
      → openai_client.py — calls gpt-4o-mini with prompts from prompt.py
      → linkedin_client.py — POSTs to LinkedIn v2/ugcPosts API
```

All secrets (`OPENAI_API_KEY`, `LINKEDIN_ACCESS_TOKEN`, `LINKEDIN_PERSON_URN`) are Lambda env vars set via Terraform variables — never Secrets Manager.

ECR pull access is granted via a repository policy to the Lambda service principal (not the execution role). The Lambda execution role only has `AWSLambdaBasicExecutionRole`.

## Local Setup

Copy `.env.example` to `.env` and fill in all values. Prompt lab scripts auto-load it — no manual `source` needed.

```bash
pip install -r prompt_lab/requirements.txt   # openai + python-dotenv
```

## Deployment

**Build & push image** (after any lambda/ code change):
```bash
ECR_URL=$(cd terraform && terraform output -raw ecr_repository_url)
docker build --platform linux/amd64 --provenance=false -t $ECR_URL:latest ./lambda
docker push $ECR_URL:latest
```

**Update Lambda to use new image:**
```bash
aws lambda update-function-code --function-name post-automator \
  --image-uri $ECR_URL:latest \
  --query 'LastUpdateStatus' --output text
```

**Infrastructure changes:**
```bash
cd terraform && terraform apply
```

`--provenance=false` is required — without it, BuildKit produces a manifest list that Lambda rejects.

## AWS Safety Rule

Never print full Lambda function output — env vars contain secrets. Always use `--query` to filter:
```bash
# Safe
aws lambda get-function --function-name post-automator --query 'Configuration.FunctionName'
```

## Prompt Engineering (`lambda/prompt.py`)

Post style constraints:
- One sentence only, ending with a specific detail/number/outcome
- No em dashes, semicolons, passive voice, first-person stories, or corporate speak
- Start mid-thought (not "If..."), name real AWS services or tools
- No statistics/percentages unless well-known facts

`lambda/prompt.py` carries a `# prompt version: vN` comment marking which version is deployed. Do not add percentage-based statistics to USER_PROMPT good examples — this was a prior bug that caused the model to reproduce fabricated numbers.

## LinkedIn Token Rotation

LinkedIn access tokens expire every 60 days. To rotate, update the Lambda env var via Terraform:
```bash
cd terraform && terraform apply -var="linkedin_access_token=AQ..."
```

## Prompt Lab (`prompt_lab/`)

Local pipeline for evaluating, optimizing, and deploying prompt versions. Scripts auto-load `.env` from the repo root — no need to `source .env` manually.

```
prompt_lab/
├── eval.py          # generate N samples, score each, save results
├── generate.py      # generate one improved version from eval weakness data
├── optimize.py      # automated hill-climbing optimizer (cost-controlled)
├── score_history.py # comparison table across all runs and versions
├── export.py        # write a winning version back to lambda/prompt.py
├── core/            # scorer.py, runner.py, history.py, dataset.py
├── prompts/         # versioned prompt files: system_v1.txt, user_v1.txt, ...
├── dataset/         # examples.json — labeled good/bad posts
└── results/         # per-run JSON files + history.json index + optimize_log.json
```

**Prompt version resolution:** `v1` is special — eval/generate load directly from `lambda/prompt.py`. All other versions (`v2`, `v3`, ...) read from `prompt_lab/prompts/system_vN.txt` + `user_vN.txt`.

**Manual workflow:**
```bash
python prompt_lab/eval.py --version v1 --n 10            # eval current prompt
python prompt_lab/eval.py --version v1 --n 5 --no-llm-judge  # rule checks only, free
python prompt_lab/generate.py --base v1 --out v2         # generate one improved version
python prompt_lab/eval.py --version v2 --n 10            # eval the candidate
python prompt_lab/score_history.py                       # compare all versions
python prompt_lab/export.py --version v2 --dry-run       # preview before writing
python prompt_lab/export.py --version v2                 # deploy winner to lambda/prompt.py
```

**Warning — export.py strips `pick_topic()`:** `export.py` writes only `SYSTEM_PROMPT` and `USER_PROMPT` to `lambda/prompt.py`. The `TOPICS` list and `pick_topic()` function are lost. After export, manually restore the `TOPICS`/`pick_topic` block from git history — `openai_client.py` imports `pick_topic` and the lambda will fail without it.

**Automated optimization (cost-controlled):**
```bash
# Default: 5 iters, 5 samples each, two-phase scoring — ~$0.05 worst case
python prompt_lab/optimize.py --base v1 --max-iters 5

# Skip per-sample LLM judge (still needs ANTHROPIC_API_KEY for candidate generation)
python prompt_lab/optimize.py --base v1 --max-iters 5 --rules-only

# Stop early when score hits target
python prompt_lab/optimize.py --base v1 --max-iters 5 --target 88
```

**How optimize.py controls costs (two-phase scoring):**
- Phase 1: rule checks only — free, no API calls
- Phase 2: LLM judge runs only if rule score didn't drop
- Candidates that regress on rules are rejected at zero extra cost

**Scoring:** `final_score = 0.4 × rule_score + 0.6 × llm_score` (0–100). Pass threshold: 65. Hard fails (em dash, statistics, emoji) zero out `rule_score` regardless of LLM score.

**Known issue with generate.py:** the auto-generator sometimes drops good/bad examples from USER_PROMPT. Always check the diff output — if examples are missing, patch the file manually before running eval.

## Terraform Inputs

| Variable | Default |
|---|---|
| `schedule_expression` | `cron(0 13 ? * SUN *)` (1 PM UTC, but scheduler timezone is `America/New_York`) |
| `lambda_timeout` | 300s |
| `lambda_memory_mb` | 512 MB |
| `openai_api_key` | — (sensitive) |
| `linkedin_access_token` | — (sensitive) |
| `linkedin_person_urn` | — (sensitive) |

