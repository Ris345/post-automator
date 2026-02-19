resource "aws_lambda_function" "this" {
  function_name = var.project_name
  description   = "Generates and publishes a weekly LinkedIn post"
  role          = aws_iam_role.lambda.arn

  package_type = "Image"
  image_uri    = "${aws_ecr_repository.this.repository_url}:latest"

  timeout     = var.lambda_timeout
  memory_size = var.lambda_memory_mb

  environment {
    variables = {
      OPENAI_API_KEY        = var.openai_api_key
      LINKEDIN_ACCESS_TOKEN = var.linkedin_access_token
      LINKEDIN_PERSON_URN   = var.linkedin_person_urn
    }
  }
}

resource "aws_lambda_permission" "scheduler" {
  statement_id  = "AllowEventBridgeScheduler"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.this.function_name
  principal     = "scheduler.amazonaws.com"
  source_arn    = aws_scheduler_schedule.weekly.arn
}
