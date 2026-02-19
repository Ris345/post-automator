output "ecr_repository_url" {
  value = aws_ecr_repository.this.repository_url
}

output "lambda_function_name" {
  value = aws_lambda_function.this.function_name
}
