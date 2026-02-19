variable "aws_region" {
  default = "us-east-1"
}

variable "project_name" {
  default = "post-automator"
}

variable "openai_api_key" {
  sensitive = true
}

variable "linkedin_access_token" {
  sensitive = true
}

variable "linkedin_person_urn" {
  sensitive = true
}

variable "schedule_expression" {
  description = "EventBridge cron or rate expression (UTC)"
  default     = "cron(0 13 ? * SUN *)"
}

variable "lambda_timeout" {
  default = 300
}

variable "lambda_memory_mb" {
  default = 512
}
