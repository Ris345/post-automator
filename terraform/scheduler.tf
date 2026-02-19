resource "aws_scheduler_schedule" "weekly" {
  name        = "${var.project_name}-weekly"
  description = "Trigger LinkedIn post on schedule"

  flexible_time_window {
    mode = "OFF"
  }

  schedule_expression          = var.schedule_expression
  schedule_expression_timezone = "UTC"

  target {
    arn      = aws_lambda_function.this.arn
    role_arn = aws_iam_role.scheduler.arn
    input    = "{}"
  }
}
