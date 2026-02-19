# LinkedIn Post Automator

A serverless system that autonomously generates and publishes weekly LinkedIn posts using OpenAI and the LinkedIn API, orchestrated entirely on AWS.

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────┐
│                          AWS Cloud                           │
│                                                              │
│   ┌───────────────────────┐                                  │
│   │  EventBridge          │                                  │
│   │  Scheduler            │                                  │
│   │                       │                                  │
│   │  cron(0 13 ? * SUN *) │──── trigger ────┐               │
│   │  (Every Sunday 1PM UTC│                  │               │
│   └───────────────────────┘                  ▼               │
│                                  ┌───────────────────────┐   │
│                                  │    Lambda Function    │   │
│                                  │                       │   │
│                                  │  1. Fetch secrets     │   │
│                                  │  2. Generate post     │   │
│                                  │  3. Publish post      │   │
│                                  └───────────────────────┘   │
│                                      │             │         │
│                        fetch secrets │             │         │
│                                      ▼             │         │
│                          ┌─────────────────────┐   │         │
│                          │   Secrets Manager   │   │         │
│                          │                     │   │         │
│                          │  - OPENAI_API_KEY   │   │         │
│                          │  - LI_ACCESS_TOKEN  │   │         │
│                          │  - LI_PERSON_URN    │   │         │
│                          └─────────────────────┘   │         │
│                                                     │         │
└─────────────────────────────────────────────────────┼─────────┘
                                                      │
                          ┌───────────────────────────┘
                          │
              ┌───────────┴───────────┐
              │                       │
              ▼                       ▼
  ┌────────────────────┐   ┌────────────────────┐
  │    OpenAI API      │   │   LinkedIn API     │
  │                    │   │                    │
  │  gpt-4o-mini       │   │  UGC Posts API     │
  │  generates post    │   │  publishes post    │
  └────────────────────┘   └────────────────────┘
```

---

## Data Flow

```
EventBridge          Lambda              Secrets Manager
    │                  │                       │
    │─── trigger ──────▶                       │
    │                  │─── get_secret() ──────▶
    │                  │◀── openai_key,         │
    │                  │    li_token,           │
    │                  │    li_urn ────────────│
    │                  │
    │               Lambda                  OpenAI
    │                  │                       │
    │                  │─── chat.completions() ▶
    │                  │◀── post text ─────────│
    │                  │
    │               Lambda                 LinkedIn
    │                  │                       │
    │                  │─── POST /ugcPosts ────▶
    │                  │◀── 201 Created ───────│
```

---

## Project Structure

```
linkedin-automator/
│
├── README.md                    # This file
│
├── lambda/
│   ├── handler.py               # Lambda entrypoint
│   ├── openai_client.py         # OpenAI post generation
│   ├── linkedin_client.py       # LinkedIn API publisher
│   ├── secrets.py               # Secrets Manager wrapper
│   ├── prompt.py                # System + user prompt definitions
│   └── requirements.txt         # Python dependencies
│
├── terraform/
│   ├── main.tf                  # Root module, provider config
│   ├── variables.tf             # Input variables
│   ├── outputs.tf               # Stack outputs
│   ├── lambda.tf                # Lambda function + IAM role
│   ├── scheduler.tf             # EventBridge Scheduler
│   └── secrets.tf               # Secrets Manager resources
│
├── scripts/
│   ├── build_lambda.sh          # Package Lambda zip for deployment
│   └── rotate_token.sh          # Update LinkedIn token in Secrets Manager
│
└── .gitignore
```

---

## Prerequisites

| Requirement | Notes |
|---|---|
| AWS account | IAM user with permissions for Lambda, EventBridge, Secrets Manager, IAM |
| Terraform >= 1.6 | `brew install terraform` |
| Python 3.12 | Lambda runtime |
| OpenAI API key | `platform.openai.com` |
| LinkedIn access token | OAuth 2.0, `w_member_social` scope |
| LinkedIn person URN | `urn:li:person:<id>` — from `/v2/userinfo` |

---

## LinkedIn API Setup

LinkedIn OAuth tokens expire every **60 days**. Before deploying:

1. Create a LinkedIn Developer App at `developer.linkedin.com`
2. Request the `w_member_social` OAuth 2.0 scope
3. Generate an access token via the Authorization Code Flow
4. Get your person URN from the `/v2/userinfo` endpoint

> Use `scripts/rotate_token.sh` to update the token in Secrets Manager before it expires.

---

## Deployment

### 1. Build the Lambda package

```bash
./scripts/build_lambda.sh
```

### 2. Configure Terraform variables

```bash
cp terraform/terraform.tfvars.example terraform/terraform.tfvars
# Edit with your AWS region
```

### 3. Deploy infrastructure

```bash
cd terraform
terraform init
terraform plan
terraform apply
```

### 4. Populate secrets

```bash
aws secretsmanager put-secret-value \
  --secret-id linkedin-automator/openai-api-key \
  --secret-string '{"api_key":"sk-..."}'

aws secretsmanager put-secret-value \
  --secret-id linkedin-automator/linkedin-credentials \
  --secret-string '{"access_token":"AQ...","person_urn":"urn:li:person:XXXXX"}'
```

---

## Configuration

### Schedule

Every Sunday at 1:00 PM UTC. Change in `terraform/variables.tf`:

```hcl
variable "schedule_expression" {
  default = "cron(0 13 ? * SUN *)"
}
```

### Post Prompt

Tune in `lambda/prompt.py` — no infrastructure change needed.

The model is instructed to:
- Write as a senior infrastructure engineer
- Cover: AWS infrastructure, chaos engineering, SRE, platform engineering, cloud cost optimization, MLOps infrastructure
- Stay under 150 words, no hashtags, no hype, sound human
- End with one sharp question

---

## IAM Permissions

The Lambda execution role has least-privilege access:

| Service | Actions |
|---|---|
| Secrets Manager | `GetSecretValue` on `linkedin-automator/*` |

---

## Cost Estimate

| Service | Usage | Est. Monthly Cost |
|---|---|---|
| Lambda | 4 invocations/month, ~10s each | < $0.01 |
| EventBridge Scheduler | 4 invocations/month | < $0.01 |
| Secrets Manager | 2 secrets | ~$0.80 |
| OpenAI gpt-4o-mini | ~500 tokens/week | ~$0.01 |
| **Total** | | **~$0.82/month** |

---

## Local Testing

```bash
pip install -r lambda/requirements.txt

export AWS_PROFILE=your-profile
export AWS_REGION=us-east-1

python -c "from lambda.handler import handler; handler({}, {})"
```

---

## Roadmap

- [ ] LinkedIn OAuth token auto-refresh
- [ ] Post topic rotation to avoid repetition
- [ ] Slack notification on failure
