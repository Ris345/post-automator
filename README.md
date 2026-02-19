# post-automator

Posts to LinkedIn every Sunday at 1PM EST. Runs on AWS Lambda, triggered by EventBridge Scheduler, uses OpenAI to generate the content.

## Stack

- **Runtime** — Python 3.12 on Lambda (container image via ECR)
- **Trigger** — EventBridge Scheduler (`cron(0 13 ? * SUN *)`, `America/New_York`)
- **AI** — OpenAI `gpt-4o-mini`
- **Infra** — Terraform

## Setup

1. Copy `.env.example` to `.env` and fill in your keys
2. Build and push the image to ECR
3. Run `terraform apply`

## Deploying changes

```bash
docker build --platform linux/amd64 --provenance=false -t <ecr-url>:latest ./lambda
docker push <ecr-url>:latest
aws lambda update-function-code --function-name post-automator --image-uri <ecr-url>:latest
```

## Notes

- LinkedIn OAuth tokens expire every 60 days — update `LINKEDIN_ACCESS_TOKEN` in Lambda env vars
- Tune the post style in `lambda/prompt.py`
