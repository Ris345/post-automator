# post-automator

Generates and publishes a weekly LinkedIn post using OpenAI, triggered by EventBridge Scheduler and running on AWS Lambda.

## Architecture

```
EventBridge Scheduler (cron: Sunday 1PM UTC)
        │
        ▼
  Lambda (ECR container)
        │
        ├──▶ OpenAI API (generate post)
        └──▶ LinkedIn UGC API (publish post)
```

Secrets are stored as Lambda environment variables.

## Structure

```
├── lambda/
│   ├── handler.py
│   ├── openai_client.py
│   ├── linkedin_client.py
│   ├── secrets.py
│   ├── prompt.py
│   └── requirements.txt
├── terraform/
│   ├── main.tf
│   ├── variables.tf
│   ├── ecr.tf
│   ├── iam.tf
│   ├── lambda.tf
│   ├── scheduler.tf
│   └── outputs.tf
└── .env.example
```

## Deploy

```bash
# Build and push image
docker build --platform linux/amd64 --provenance=false -t <ecr-url>:latest ./lambda
docker push <ecr-url>:latest

# Provision infra
cd terraform
terraform init
terraform apply
```

## Prerequisites

- AWS IAM user with Lambda, ECR, EventBridge, and IAM permissions
- OpenAI API key
- LinkedIn OAuth token (`w_member_social` scope) + person URN

> LinkedIn tokens expire every 60 days — update `LINKEDIN_ACCESS_TOKEN` in Lambda env vars when they do.
