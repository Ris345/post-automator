resource "aws_ecr_repository" "this" {
  name                 = var.project_name
  image_tag_mutability = "MUTABLE"
}

# Keep only the last 3 images so ECR doesn't accumulate stale builds
resource "aws_ecr_lifecycle_policy" "this" {
  repository = aws_ecr_repository.this.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep last 3 images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 3
      }
      action = { type = "expire" }
    }]
  })
}

# Grant Lambda service principal pull access directly on the repo.
# This keeps the Lambda execution role minimal (CloudWatch Logs only).
resource "aws_ecr_repository_policy" "this" {
  repository = aws_ecr_repository.this.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "LambdaPull"
      Effect = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action = [
        "ecr:GetDownloadUrlForLayer",
        "ecr:BatchGetImage",
      ]
    }]
  })
}
